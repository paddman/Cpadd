from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import get_settings
from app.database import get_setting, set_setting
from app.schemas import QwenSettingsUpdate
from app.services.finance import finance_context


SYSTEM_PROMPT = """คุณคือ เชอรี่ CFO ผู้ช่วยบริหารการเงินบ้านของผู้ใช้
ตอบภาษาไทยแบบตรง กระชับ และอ้างอิงเฉพาะข้อมูลที่ได้รับ
หน้าที่หลัก:
- สรุป Cash Flow รายวัน รายสัปดาห์ รายเดือน และรายปี
- แยกเงินส่วนตัว เงินบริษัท และเงินสำรองจ่ายแทนบริษัทให้ชัด
- ช่วยตัดสินใจซื้อสด ผ่อน หรือเลื่อนซื้อโดยดูสภาพคล่องและภาระเดิม
- วิเคราะห์หนี้ ค่างวด เงินออม และรายการที่กำลังวางแผน
- เตือนเมื่อข้อมูลไม่ครบ ห้ามแต่งยอดเงิน ดอกเบี้ย รายได้ หรือยอดบัญชีขึ้นเอง
- รายการผ่อน 0% ยังถือเป็นหนี้เต็มจำนวน
- ไม่ให้คำแนะนำลงทุนแบบรับประกันผลตอบแทน

รูปแบบคำตอบ:
1. คำตัดสินหรือสถานะสั้น ๆ
2. ตัวเลขสำคัญ
3. สิ่งที่ควรทำต่อทันทีไม่เกิน 3 ข้อ
หากข้อมูลไม่พอ ให้ระบุข้อมูลที่ขาดอย่างเจาะจง
"""


def _stored_or_default(key: str, default: Any, cast: type = str) -> Any:
    stored = get_setting(f"qwen.{key}")
    if stored is None:
        return default
    try:
        return cast(stored)
    except (TypeError, ValueError):
        return default


def get_qwen_settings(include_secret: bool = False) -> dict:
    defaults = get_settings()
    data = {
        "base_url": _stored_or_default("base_url", defaults.qwen_base_url),
        "model": _stored_or_default("model", defaults.qwen_model),
        "api_key": _stored_or_default("api_key", defaults.qwen_api_key),
        "temperature": _stored_or_default(
            "temperature", defaults.qwen_temperature, float
        ),
        "max_tokens": _stored_or_default(
            "max_tokens", defaults.qwen_max_tokens, int
        ),
        "timeout_seconds": _stored_or_default(
            "timeout_seconds", defaults.qwen_timeout_seconds, int
        ),
    }
    if include_secret:
        return data
    secret = data.pop("api_key", "")
    data["api_key_configured"] = bool(secret)
    data["api_key_masked"] = "••••••••" if secret else ""
    return data


def save_qwen_settings(payload: QwenSettingsUpdate) -> dict:
    set_setting("qwen.base_url", payload.base_url.rstrip("/"))
    set_setting("qwen.model", payload.model)
    set_setting("qwen.temperature", str(payload.temperature))
    set_setting("qwen.max_tokens", str(payload.max_tokens))
    set_setting("qwen.timeout_seconds", str(payload.timeout_seconds))
    if payload.api_key is not None and payload.api_key.strip():
        set_setting("qwen.api_key", payload.api_key.strip())
    return get_qwen_settings(include_secret=False)


def _headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


async def test_qwen_connection() -> dict:
    config = get_qwen_settings(include_secret=True)
    url = f"{config['base_url'].rstrip('/')}/models"
    try:
        async with httpx.AsyncClient(timeout=config["timeout_seconds"]) as client:
            response = await client.get(url, headers=_headers(config["api_key"]))
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(f"เชื่อมต่อ Qwen ไม่สำเร็จ: {exc}") from exc

    models = [item.get("id") for item in payload.get("data", []) if item.get("id")]
    return {
        "ok": True,
        "base_url": config["base_url"],
        "configured_model": config["model"],
        "available_models": models[:30],
        "model_found": config["model"] in models if models else None,
    }


async def chat_with_cfo(message: str, period: str, scope: str) -> dict:
    config = get_qwen_settings(include_secret=True)
    context = finance_context(period=period, scope=scope)
    url = f"{config['base_url'].rstrip('/')}/chat/completions"
    request_payload = {
        "model": config["model"],
        "temperature": config["temperature"],
        "max_tokens": config["max_tokens"],
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": "ข้อมูลการเงินจริงจาก Cpadd:\n"
                + json.dumps(context, ensure_ascii=False, default=str),
            },
            {"role": "user", "content": message},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=config["timeout_seconds"]) as client:
            response = await client.post(
                url,
                headers=_headers(config["api_key"]),
                json=request_payload,
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise RuntimeError(
            f"Qwen ตอบกลับด้วย HTTP {exc.response.status_code}: {detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"เรียก Qwen ไม่สำเร็จ: {exc}") from exc

    try:
        answer = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("รูปแบบคำตอบจาก Qwen ไม่ตรง OpenAI-compatible API") from exc

    usage = payload.get("usage") or {}
    return {
        "answer": answer,
        "model": payload.get("model", config["model"]),
        "usage": usage,
        "period": period,
        "scope": scope,
    }
