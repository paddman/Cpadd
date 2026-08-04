from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import anyio
import pymupdf
import pytesseract
from PIL import Image, ImageEnhance, ImageOps, ImageSequence, UnidentifiedImageError

from app.config import get_settings
from app.services.qwen import call_qwen_chat


ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}
ALLOWED_ENTRY_TYPES = {"income", "expense", "savings", "debt_payment", "transfer"}
DATE_PATTERN = r"\d{1,2}[/-]\d{1,2}[/-](?:\d{2}|\d{4})"
MONEY_PATTERN = r"-?\d[\d,]*\.\d{2}"

STATEMENT_SYSTEM_PROMPT = """You extract structured financial statement data from OCR text.
Return one JSON object only. Do not use markdown and do not invent missing values.
The source may contain Thai and English OCR errors.

Required schema:
{
  "statement": {
    "bank": "",
    "card_type": "",
    "card_number_masked": "",
    "account_name": "",
    "currency": "THB",
    "statement_date": null,
    "previous_balance": null,
    "amount_due": null,
    "total_balance": null
  },
  "transactions": [
    {
      "transaction_date": "YYYY-MM-DD or null",
      "posting_date": "YYYY-MM-DD or null",
      "description": "",
      "amount": 0.0,
      "direction": "debit or credit",
      "entry_type": "expense, income, debt_payment, transfer, or savings",
      "category": "Thai short category",
      "merchant": "",
      "installment_current": null,
      "installment_total": null,
      "confidence": 0.0
    }
  ],
  "warnings": []
}

Rules:
- Amount must always be a positive number. Use direction=credit for negative values, payments, refunds, or credits.
- Credit-card purchases and fees are expense.
- PAYMENT / ชำระบัตร is transfer, not expense, to avoid double counting.
- Refund is income only when it is clearly a refund; otherwise use transfer.
- Ignore PREVIOUS BALANCE, TOTAL BALANCE, AMOUNT DUE, subtotals, page totals, and headings as transactions.
- For text like 03/10 after a merchant, set installment_current=3 and installment_total=10.
- Never infer a date that is not visible. Convert Buddhist years over 2400 to Gregorian by subtracting 543.
- Preserve merchant names and descriptions as closely as possible.
"""


def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text_score(text: str) -> int:
    return sum(character.isalnum() for character in text)


def _available_ocr_language(requested: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    try:
        available = set(pytesseract.get_languages(config=""))
    except pytesseract.TesseractError as exc:
        raise RuntimeError(f"Tesseract ใช้งานไม่ได้: {exc}") from exc

    requested_parts = [part.strip() for part in requested.split("+") if part.strip()]
    enabled = [part for part in requested_parts if part in available]
    missing = [part for part in requested_parts if part not in available]
    if missing:
        warnings.append(f"ไม่พบภาษา OCR: {', '.join(missing)}")
    if not enabled:
        if "eng" in available:
            enabled = ["eng"]
            warnings.append("ใช้ OCR ภาษาอังกฤษแทน")
        else:
            raise RuntimeError("Tesseract ไม่มี language data ที่ใช้งานได้")
    return "+".join(enabled), warnings


def _prepare_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image).convert("RGB")
    if image.width < 1600:
        ratio = 1600 / max(image.width, 1)
        image = image.resize(
            (1600, max(1, int(image.height * ratio))),
            Image.Resampling.LANCZOS,
        )
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    gray = ImageEnhance.Contrast(gray).enhance(1.25)
    return gray


def _ocr_pil_image(image: Image.Image, language: str) -> str:
    prepared = _prepare_image(image)
    try:
        return pytesseract.image_to_string(
            prepared,
            lang=language,
            config="--oem 1 --psm 6 preserve_interword_spaces=1",
        ).strip()
    except pytesseract.TesseractError as exc:
        raise RuntimeError(f"OCR ไม่สำเร็จ: {exc}") from exc


def _pixmap_to_image(pixmap: pymupdf.Pixmap) -> Image.Image:
    if pixmap.alpha:
        return Image.frombytes("RGBA", (pixmap.width, pixmap.height), pixmap.samples).convert(
            "RGB"
        )
    mode = "RGB" if pixmap.n >= 3 else "L"
    return Image.frombytes(mode, (pixmap.width, pixmap.height), pixmap.samples).convert(
        "RGB"
    )


def extract_text(data: bytes, filename: str) -> dict[str, Any]:
    settings = get_settings()
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("รองรับเฉพาะ PDF, PNG, JPG, WEBP และ TIFF")

    language, warnings = _available_ocr_language(settings.ocr_languages)
    pages: list[str] = []
    methods: list[str] = []

    if extension == ".pdf":
        try:
            document = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:
            raise ValueError(f"เปิด PDF ไม่สำเร็จ: {exc}") from exc
        if document.needs_pass:
            document.close()
            raise ValueError("PDF มีรหัสผ่าน กรุณาปลดรหัสก่อนอัปโหลด")
        if document.page_count > settings.ocr_max_pages:
            document.close()
            raise ValueError(
                f"PDF เกิน {settings.ocr_max_pages} หน้า ซึ่งมากเกินขอบเขต OCR ปัจจุบัน"
            )
        zoom = max(settings.ocr_dpi, 120) / 72
        matrix = pymupdf.Matrix(zoom, zoom)
        try:
            for page in document:
                native_text = page.get_text("text", sort=True).strip()
                if _text_score(native_text) >= 80:
                    pages.append(native_text)
                    methods.append("native-text")
                    continue
                pixmap = page.get_pixmap(matrix=matrix, alpha=False, colorspace=pymupdf.csRGB)
                pages.append(_ocr_pil_image(_pixmap_to_image(pixmap), language))
                methods.append("tesseract")
        finally:
            document.close()
    else:
        try:
            source = Image.open(io.BytesIO(data))
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("ไฟล์ภาพเสียหรือรูปแบบไม่รองรับ") from exc
        frames = list(ImageSequence.Iterator(source))
        if len(frames) > settings.ocr_max_pages:
            raise ValueError(
                f"ไฟล์ภาพมีเกิน {settings.ocr_max_pages} หน้า/เฟรม"
            )
        for frame in frames:
            pages.append(_ocr_pil_image(frame.copy(), language))
            methods.append("tesseract")

    raw_text = "\n\n".join(
        f"--- PAGE {index} ---\n{text}" for index, text in enumerate(pages, start=1)
    ).strip()
    if _text_score(raw_text) < 20:
        warnings.append("อ่านข้อความได้น้อยมาก ควรใช้ไฟล์ที่คมชัดหรือ PDF ต้นฉบับ")

    unique_methods = sorted(set(methods))
    return {
        "raw_text": raw_text,
        "page_count": len(pages),
        "ocr_engine": f"Tesseract ({language})",
        "extraction_method": "+".join(unique_methods),
        "warnings": warnings,
    }


def normalize_date(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    iso_match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if iso_match:
        year, month, day = map(int, iso_match.groups())
    else:
        match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2}|\d{4})", text)
        if not match:
            return None
        day, month, year = map(int, match.groups())

    if year >= 2400:
        year -= 543
    elif year < 100:
        year += 2000 if year <= 79 else 1900
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    cleaned = re.sub(r"[^0-9.\-]", "", str(value).replace(",", ""))
    if cleaned in {"", "-", ".", "-."}:
        return None
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def _category(description: str) -> str:
    text = description.upper()
    mappings = [
        (("KFC", "MCDONALD", "STARBUCKS", "CAFE", "COFFEE", "RESTAURANT", "FOOD"), "อาหาร"),
        (("FITNESS", "HOSPITAL", "CLINIC", "PHARMACY", "ACADEMY", "HEALTH"), "สุขภาพ"),
        (("OPENAI", "CHATGPT", "NETFLIX", "SPOTIFY", "GOOGLE", "APPLE.COM/BILL"), "สมาชิก/ซอฟต์แวร์"),
        (("XIAOMI", "TG FONE", "PHONE", "MOBILE", "ELECTRONIC"), "อุปกรณ์ไอที"),
        (("GRAB", "BOLT", "TAXI", "PTT", "SHELL", "ESSO"), "เดินทาง"),
        (("PAYMENT", "ชำระ", "TRANSFER"), "โอน/ชำระบัตร"),
    ]
    for keywords, category in mappings:
        if any(keyword in text for keyword in keywords):
            return category
    return "อื่น ๆ"


def _classify_transaction(description: str, signed_amount: float) -> tuple[str, str]:
    upper = description.upper()
    if "PAYMENT" in upper or "ชำระ" in description:
        return "credit", "transfer"
    if any(word in upper for word in ("REFUND", "REVERSAL", "CREDIT ADJUSTMENT")):
        return "credit", "income"
    if signed_amount < 0:
        return "credit", "transfer"
    return "debit", "expense"


def _extract_statement_metadata(text: str) -> dict[str, Any]:
    upper = text.upper()
    bank = ""
    if "KBANK" in upper or "KASIKORN" in upper or "กสิกร" in text:
        bank = "KBank"
    elif "SCB" in upper or "SIAM COMMERCIAL" in upper or "ไทยพาณิชย์" in text:
        bank = "SCB"
    elif "KRUNGSRI" in upper or "กรุงศรี" in text:
        bank = "Krungsri"
    elif "BANGKOK BANK" in upper or "กรุงเทพ" in text:
        bank = "Bangkok Bank"

    card_match = re.search(r"(?:\d{4}[ \-]){1,3}(?:[Xx*]{2,4}[ \-]){0,2}\d{4}", text)

    def amount_after(labels: tuple[str, ...]) -> float | None:
        for label in labels:
            match = re.search(
                rf"{label}[^\d\-]{{0,40}}({MONEY_PATTERN})",
                text,
                flags=re.IGNORECASE,
            )
            if match:
                return _to_float(match.group(1))
        return None

    return {
        "bank": bank,
        "card_type": "",
        "card_number_masked": card_match.group(0).strip() if card_match else "",
        "account_name": "",
        "currency": "THB",
        "statement_date": None,
        "previous_balance": amount_after((r"PREVIOUS\s+BALANCE", r"ยอดยกมา")),
        "amount_due": amount_after((r"AMOUNT\s+DUE", r"ยอดที่ต้องชำระ")),
        "total_balance": amount_after((r"TOTAL\s+BALANCE", r"ยอดรวม")),
    }


def parse_statement_rules(raw_text: str) -> dict[str, Any]:
    transactions: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str, float]] = set()

    patterns = [
        re.compile(
            rf"^\s*(?P<date>{DATE_PATTERN})\s+(?P<posting>{DATE_PATTERN})\s+"
            rf"(?P<description>.+?)\s+(?P<amount>{MONEY_PATTERN})\s*$",
            flags=re.IGNORECASE,
        ),
        re.compile(
            rf"^\s*(?P<date>{DATE_PATTERN})\s+(?P<description>.+?)\s+"
            rf"(?P<amount>{MONEY_PATTERN})\s*$",
            flags=re.IGNORECASE,
        ),
    ]

    for raw_line in raw_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line or line.startswith("--- PAGE"):
            continue
        upper = line.upper()
        if any(
            heading in upper
            for heading in (
                "PREVIOUS BALANCE",
                "TOTAL BALANCE",
                "AMOUNT DUE",
                "TRANS DATE",
                "POSTING DATE",
                "DESCRIPTION",
            )
        ):
            continue

        match = None
        for pattern in patterns:
            match = pattern.match(line)
            if match:
                break
        if not match:
            continue

        signed_amount = _to_float(match.group("amount"))
        if signed_amount is None:
            continue
        description = match.group("description").strip(" :-")
        trans_date = normalize_date(match.group("date"))
        posting_value = match.groupdict().get("posting")
        posting_date = normalize_date(posting_value) if posting_value else None
        key = (trans_date, description.upper(), abs(signed_amount))
        if key in seen:
            continue
        seen.add(key)

        installment_current = None
        installment_total = None
        installment = re.search(r"(?:[:\s])([0-9]{1,2})/([0-9]{1,2})(?:\s|$)", description)
        if installment:
            installment_current = int(installment.group(1))
            installment_total = int(installment.group(2))

        direction, entry_type = _classify_transaction(description, signed_amount)
        transactions.append(
            {
                "transaction_date": trans_date,
                "posting_date": posting_date,
                "description": description,
                "amount": abs(signed_amount),
                "direction": direction,
                "entry_type": entry_type,
                "category": _category(description),
                "merchant": re.sub(r"\s*:\s*\d{1,2}/\d{1,2}\s*$", "", description),
                "installment_current": installment_current,
                "installment_total": installment_total,
                "confidence": 0.68,
            }
        )

    return {
        "statement": _extract_statement_metadata(raw_text),
        "transactions": transactions,
        "warnings": (["ใช้ตัวแยกกฎพื้นฐาน เพราะไม่ได้ใช้ Qwen"] if transactions else ["ไม่พบรายการธุรกรรมจากข้อความ OCR"]),
        "parser": "rules",
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Qwen ไม่ได้ส่ง JSON object กลับมา")
    return json.loads(cleaned[start : end + 1])


def normalize_parsed_statement(payload: dict[str, Any]) -> dict[str, Any]:
    source_statement = payload.get("statement") if isinstance(payload.get("statement"), dict) else {}
    statement = _extract_statement_metadata("")
    for key in (
        "bank",
        "card_type",
        "card_number_masked",
        "account_name",
        "currency",
    ):
        value = source_statement.get(key)
        statement[key] = str(value).strip() if value is not None else statement[key]
    statement["statement_date"] = normalize_date(source_statement.get("statement_date"))
    for key in ("previous_balance", "amount_due", "total_balance"):
        statement[key] = _to_float(source_statement.get(key))

    transactions: list[dict[str, Any]] = []
    raw_transactions = payload.get("transactions")
    if not isinstance(raw_transactions, list):
        raw_transactions = []
    for item in raw_transactions[:500]:
        if not isinstance(item, dict):
            continue
        amount = _to_float(item.get("amount"))
        if amount is None or amount == 0:
            continue
        description = str(item.get("description") or item.get("merchant") or "").strip()
        if not description:
            continue
        entry_type = str(item.get("entry_type") or "expense").strip().lower()
        if entry_type not in ALLOWED_ENTRY_TYPES:
            entry_type = "expense"
        direction = str(item.get("direction") or "debit").strip().lower()
        if direction not in {"debit", "credit"}:
            direction = "credit" if entry_type in {"income", "transfer"} else "debit"
        confidence = _to_float(item.get("confidence"))
        confidence = min(max(confidence if confidence is not None else 0.75, 0), 1)

        current = item.get("installment_current")
        total = item.get("installment_total")
        try:
            current = int(current) if current not in (None, "") else None
        except (TypeError, ValueError):
            current = None
        try:
            total = int(total) if total not in (None, "") else None
        except (TypeError, ValueError):
            total = None
        if current is not None and current < 1:
            current = None
        if total is not None and total < 1:
            total = None

        transactions.append(
            {
                "transaction_date": normalize_date(item.get("transaction_date")),
                "posting_date": normalize_date(item.get("posting_date")),
                "description": description[:500],
                "amount": abs(amount),
                "direction": direction,
                "entry_type": entry_type,
                "category": str(item.get("category") or _category(description)).strip()[:80],
                "merchant": str(item.get("merchant") or description).strip()[:120],
                "installment_current": current,
                "installment_total": total,
                "confidence": confidence,
            }
        )

    warnings = payload.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    return {
        "statement": statement,
        "transactions": transactions,
        "warnings": [str(item)[:300] for item in warnings[:20]],
        "parser": "qwen",
    }


async def parse_statement_with_qwen(raw_text: str, filename: str) -> dict[str, Any]:
    max_chars = 60_000
    clipped = raw_text[:max_chars]
    result = await call_qwen_chat(
        [
            {"role": "system", "content": STATEMENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Filename: {filename}\n"
                    "Extract the statement below. Return JSON only.\n\n"
                    f"{clipped}"
                ),
            },
        ],
        temperature=0,
        max_tokens=5000,
    )
    parsed = normalize_parsed_statement(_extract_json_object(result["answer"]))
    parsed["model"] = result["model"]
    if len(raw_text) > max_chars:
        parsed["warnings"].append("ข้อความ OCR ถูกตัดก่อนส่ง Qwen เพราะยาวเกินขอบเขต")
    return parsed


async def analyze_statement(
    data: bytes,
    filename: str,
    *,
    use_qwen: bool,
) -> dict[str, Any]:
    extracted = await anyio.to_thread.run_sync(extract_text, data, filename)
    rules = parse_statement_rules(extracted["raw_text"])
    parsed = rules
    if use_qwen:
        try:
            parsed = await parse_statement_with_qwen(extracted["raw_text"], filename)
            for key, value in rules["statement"].items():
                if parsed["statement"].get(key) in (None, "") and value not in (None, ""):
                    parsed["statement"][key] = value
            if not parsed["transactions"] and rules["transactions"]:
                parsed["transactions"] = rules["transactions"]
                parsed["warnings"].append("Qwen ไม่คืนรายการ จึงใช้ตัวแยกกฎแทน")
                parsed["parser"] = "qwen+rules"
        except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
            parsed = rules
            parsed["warnings"].append(f"Qwen parse ไม่สำเร็จ: {exc}")
            parsed["parser"] = "rules-fallback"

    parsed["warnings"] = [*extracted["warnings"], *parsed.get("warnings", [])]
    return {
        **extracted,
        "statement": parsed["statement"],
        "transactions": parsed["transactions"],
        "warnings": parsed["warnings"],
        "parser": parsed.get("parser", "rules"),
        "model": parsed.get("model"),
    }
