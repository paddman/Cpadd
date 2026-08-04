from __future__ import annotations

import json
from typing import Any

from app.database import get_connection, row_to_dict, rows_to_dicts


def get_statement_import(import_id: int, *, include_raw_text: bool = True) -> dict | None:
    with get_connection() as connection:
        statement_row = connection.execute(
            "SELECT * FROM statement_imports WHERE id = ?", (import_id,)
        ).fetchone()
        if statement_row is None:
            return None
        item_rows = connection.execute(
            """
            SELECT * FROM statement_import_items
            WHERE import_id = ?
            ORDER BY item_index ASC
            """,
            (import_id,),
        ).fetchall()

    statement = row_to_dict(statement_row) or {}
    parsed_json = statement.pop("parsed_json", "{}")
    if not include_raw_text:
        statement.pop("raw_text", None)
    try:
        parsed = json.loads(parsed_json)
    except json.JSONDecodeError:
        parsed = {}
    statement["warnings"] = parsed.get("warnings", [])
    statement["parser"] = parsed.get("parser", "")
    statement["model"] = parsed.get("model")
    statement["transactions"] = rows_to_dicts(item_rows)
    statement["transaction_count"] = len(item_rows)
    statement["imported_count"] = sum(
        1 for item in item_rows if item["imported_transaction_id"] is not None
    )
    return statement


def find_statement_by_hash(file_hash: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT id FROM statement_imports WHERE file_sha256 = ?", (file_hash,)
        ).fetchone()
    return get_statement_import(row["id"]) if row else None


def save_statement_preview(
    *,
    filename: str,
    file_hash: str,
    mime_type: str,
    scope: str,
    account: str,
    analysis: dict[str, Any],
) -> dict:
    statement = analysis.get("statement") or {}
    parsed_meta = {
        "warnings": analysis.get("warnings") or [],
        "parser": analysis.get("parser") or "",
        "model": analysis.get("model"),
    }
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO statement_imports(
                filename, file_sha256, mime_type, scope, account, bank,
                card_type, card_number_masked, account_name, statement_date,
                previous_balance, amount_due, total_balance, currency,
                ocr_engine, extraction_method, page_count, raw_text,
                parsed_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'previewed')
            """,
            (
                filename,
                file_hash,
                mime_type,
                scope,
                account,
                statement.get("bank") or "",
                statement.get("card_type") or "",
                statement.get("card_number_masked") or "",
                statement.get("account_name") or "",
                statement.get("statement_date"),
                statement.get("previous_balance"),
                statement.get("amount_due"),
                statement.get("total_balance"),
                statement.get("currency") or "THB",
                analysis.get("ocr_engine") or "",
                analysis.get("extraction_method") or "",
                int(analysis.get("page_count") or 0),
                analysis.get("raw_text") or "",
                json.dumps(parsed_meta, ensure_ascii=False),
            ),
        )
        import_id = int(cursor.lastrowid)
        for index, item in enumerate(analysis.get("transactions") or []):
            transaction_date = item.get("transaction_date")
            amount = float(item.get("amount") or 0)
            selected = 1 if transaction_date and amount > 0 else 0
            connection.execute(
                """
                INSERT INTO statement_import_items(
                    import_id, item_index, transaction_date, posting_date,
                    description, amount, direction, entry_type, category,
                    merchant, installment_current, installment_total,
                    confidence, selected
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_id,
                    index,
                    transaction_date,
                    item.get("posting_date"),
                    str(item.get("description") or "")[:500],
                    amount,
                    item.get("direction") or "debit",
                    item.get("entry_type") or "expense",
                    str(item.get("category") or "อื่น ๆ")[:80],
                    str(item.get("merchant") or item.get("description") or "")[:120],
                    item.get("installment_current"),
                    item.get("installment_total"),
                    float(item.get("confidence") or 0),
                    selected,
                ),
            )
    result = get_statement_import(import_id)
    if result is None:
        raise RuntimeError("บันทึกผล OCR แล้วแต่ไม่สามารถอ่านกลับได้")
    return result


def list_statement_imports(limit: int = 30) -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT s.id, s.filename, s.scope, s.account, s.bank,
                   s.statement_date, s.total_balance, s.amount_due,
                   s.status, s.ocr_engine, s.extraction_method,
                   s.page_count, s.created_at, s.imported_at,
                   COUNT(i.id) AS transaction_count,
                   SUM(CASE WHEN i.imported_transaction_id IS NOT NULL THEN 1 ELSE 0 END)
                       AS imported_count
            FROM statement_imports s
            LEFT JOIN statement_import_items i ON i.import_id = s.id
            GROUP BY s.id
            ORDER BY s.created_at DESC, s.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return rows_to_dicts(rows)


def commit_statement_import(
    import_id: int,
    *,
    selected_indices: list[int] | None,
    scope: str | None,
    account: str | None,
) -> dict:
    with get_connection() as connection:
        statement = connection.execute(
            "SELECT * FROM statement_imports WHERE id = ?", (import_id,)
        ).fetchone()
        if statement is None:
            raise LookupError("ไม่พบผล OCR นี้")
        if statement["status"] == "imported":
            raise RuntimeError("Statement นี้ถูกนำเข้าแล้ว เพื่อกันยอดซ้ำ")

        params: list[Any] = [import_id]
        where = "import_id = ? AND imported_transaction_id IS NULL"
        if selected_indices is None:
            where += " AND selected = 1"
        else:
            if not selected_indices:
                raise ValueError("ยังไม่ได้เลือกรายการที่จะนำเข้า")
            placeholders = ",".join("?" for _ in selected_indices)
            where += f" AND item_index IN ({placeholders})"
            params.extend(selected_indices)
        rows = connection.execute(
            f"SELECT * FROM statement_import_items WHERE {where} ORDER BY item_index",
            params,
        ).fetchall()
        if not rows:
            raise ValueError("ไม่มีรายการพร้อมนำเข้า")

        target_scope = scope or statement["scope"]
        target_account = account or statement["account"]
        imported_ids: list[int] = []
        skipped: list[dict] = []
        for item in rows:
            if not item["transaction_date"] or float(item["amount"]) <= 0:
                skipped.append(
                    {"item_index": item["item_index"], "reason": "วันที่หรือยอดเงินไม่ครบ"}
                )
                continue
            note_parts = [f"Statement OCR #{import_id}"]
            if item["posting_date"]:
                note_parts.append(f"posting {item['posting_date']}")
            if item["installment_current"] and item["installment_total"]:
                note_parts.append(
                    f"งวด {item['installment_current']}/{item['installment_total']}"
                )
            cursor = connection.execute(
                """
                INSERT INTO transactions(
                    transaction_date, entry_type, category, amount, account,
                    scope, status, merchant, note
                ) VALUES (?, ?, ?, ?, ?, ?, 'paid', ?, ?)
                """,
                (
                    item["transaction_date"],
                    item["entry_type"],
                    item["category"],
                    item["amount"],
                    target_account,
                    target_scope,
                    item["merchant"],
                    " • ".join(note_parts)[:500],
                ),
            )
            transaction_id = int(cursor.lastrowid)
            imported_ids.append(transaction_id)
            connection.execute(
                """
                UPDATE statement_import_items
                SET imported_transaction_id = ?, selected = 1
                WHERE id = ?
                """,
                (transaction_id, item["id"]),
            )

        if not imported_ids:
            raise ValueError("ไม่มีรายการที่นำเข้าได้")
        connection.execute(
            """
            UPDATE statement_imports
            SET status = 'imported', imported_at = CURRENT_TIMESTAMP,
                scope = ?, account = ?
            WHERE id = ?
            """,
            (target_scope, target_account, import_id),
        )

    return {
        "ok": True,
        "import_id": import_id,
        "imported_count": len(imported_ids),
        "transaction_ids": imported_ids,
        "skipped": skipped,
        "scope": target_scope,
        "account": target_account,
    }
