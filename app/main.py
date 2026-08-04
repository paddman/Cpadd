from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import get_connection, init_db, row_to_dict, rows_to_dicts
from app.schemas import (
    ChatRequest,
    DebtCreate,
    DebtUpdate,
    QwenSettingsUpdate,
    TransactionCreate,
)
from app.services.finance import dashboard_summary
from app.services.qwen import (
    chat_with_cfo,
    get_qwen_settings,
    save_qwen_settings,
    test_qwen_connection,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": settings.app_name}


@app.get("/api/dashboard")
def get_dashboard(
    period: Literal["day", "week", "month", "year"] = "month",
    scope: Literal["personal", "business", "company_advance", "all"] = "personal",
) -> dict:
    return dashboard_summary(period=period, scope=scope)


@app.get("/api/transactions")
def list_transactions(
    scope: Literal["personal", "business", "company_advance", "all"] = "all",
    status: Literal["paid", "planned", "all"] = "all",
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict]:
    conditions = ["1 = 1"]
    params: list[object] = []
    if scope != "all":
        conditions.append("scope = ?")
        params.append(scope)
    if status != "all":
        conditions.append("status = ?")
        params.append(status)
    params.append(limit)

    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM transactions
            WHERE {' AND '.join(conditions)}
            ORDER BY transaction_date DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return rows_to_dicts(rows)


@app.post("/api/transactions", status_code=201)
def create_transaction(payload: TransactionCreate) -> dict:
    data = payload.model_dump(mode="json")
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO transactions(
                transaction_date, entry_type, category, amount, account,
                scope, status, merchant, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["transaction_date"],
                data["entry_type"],
                data["category"],
                data["amount"],
                data["account"],
                data["scope"],
                data["status"],
                data["merchant"],
                data["note"],
            ),
        )
        row = connection.execute(
            "SELECT * FROM transactions WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return row_to_dict(row) or {}


@app.delete("/api/transactions/{transaction_id}")
def delete_transaction(transaction_id: int) -> dict:
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM transactions WHERE id = ?", (transaction_id,)
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="ไม่พบรายการ")
    return {"ok": True}


@app.get("/api/debts")
def list_debts(
    scope: Literal["personal", "business", "company_advance", "all"] = "all",
    status: Literal["active", "closed", "all"] = "all",
) -> list[dict]:
    conditions = ["1 = 1"]
    params: list[object] = []
    if scope != "all":
        conditions.append("scope = ?")
        params.append(scope)
    if status != "all":
        conditions.append("status = ?")
        params.append(status)
    with get_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM debts
            WHERE {' AND '.join(conditions)}
            ORDER BY status ASC, current_balance DESC, id DESC
            """,
            params,
        ).fetchall()
    return rows_to_dicts(rows)


@app.post("/api/debts", status_code=201)
def create_debt(payload: DebtCreate) -> dict:
    data = payload.model_dump()
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO debts(
                name, debt_type, original_amount, current_balance,
                monthly_payment, interest_rate, total_installments,
                paid_installments, due_day, scope, status, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["name"],
                data["debt_type"],
                data["original_amount"],
                data["current_balance"],
                data["monthly_payment"],
                data["interest_rate"],
                data["total_installments"],
                data["paid_installments"],
                data["due_day"],
                data["scope"],
                data["status"],
                data["note"],
            ),
        )
        row = connection.execute(
            "SELECT * FROM debts WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return row_to_dict(row) or {}


@app.put("/api/debts/{debt_id}")
def update_debt(debt_id: int, payload: DebtUpdate) -> dict:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="ไม่มีข้อมูลให้แก้ไข")

    assignments = [f"{field} = ?" for field in changes]
    values = list(changes.values())
    assignments.append("updated_at = CURRENT_TIMESTAMP")
    values.append(debt_id)

    with get_connection() as connection:
        cursor = connection.execute(
            f"UPDATE debts SET {', '.join(assignments)} WHERE id = ?", values
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="ไม่พบหนี้")
        row = connection.execute("SELECT * FROM debts WHERE id = ?", (debt_id,)).fetchone()
    return row_to_dict(row) or {}


@app.delete("/api/debts/{debt_id}")
def delete_debt(debt_id: int) -> dict:
    with get_connection() as connection:
        cursor = connection.execute("DELETE FROM debts WHERE id = ?", (debt_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="ไม่พบหนี้")
    return {"ok": True}


@app.get("/api/settings/qwen")
def read_qwen_settings() -> dict:
    return get_qwen_settings(include_secret=False)


@app.put("/api/settings/qwen")
def update_qwen_settings(payload: QwenSettingsUpdate) -> dict:
    return save_qwen_settings(payload)


@app.post("/api/settings/qwen/test")
async def test_qwen() -> dict:
    try:
        return await test_qwen_connection()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/agent/chat")
async def cfo_chat(payload: ChatRequest) -> dict:
    try:
        return await chat_with_cfo(
            message=payload.message,
            period=payload.period,
            scope=payload.scope,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=503, detail="Frontend ยังไม่ถูกติดตั้ง")
    return FileResponse(index_file)
