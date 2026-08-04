from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Literal

from app.database import get_connection, rows_to_dicts

Period = Literal["day", "week", "month", "year"]


def period_bounds(period: Period, anchor: date | None = None) -> tuple[date, date]:
    anchor = anchor or date.today()
    if period == "day":
        return anchor, anchor
    if period == "week":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6)
    if period == "month":
        start = anchor.replace(day=1)
        end = anchor.replace(day=monthrange(anchor.year, anchor.month)[1])
        return start, end
    return date(anchor.year, 1, 1), date(anchor.year, 12, 31)


def _scope_clause(scope: str) -> tuple[str, list[str]]:
    if scope == "all":
        return "", []
    return " AND scope = ?", [scope]


def dashboard_summary(
    period: Period = "month", scope: str = "personal", anchor: date | None = None
) -> dict:
    start, end = period_bounds(period, anchor)
    scope_sql, scope_params = _scope_clause(scope)

    with get_connection() as connection:
        paid_rows = connection.execute(
            f"""
            SELECT * FROM transactions
            WHERE transaction_date BETWEEN ? AND ?
              AND status = 'paid'
              {scope_sql}
            ORDER BY transaction_date DESC, id DESC
            """,
            [start.isoformat(), end.isoformat(), *scope_params],
        ).fetchall()

        planned_rows = connection.execute(
            f"""
            SELECT * FROM transactions
            WHERE transaction_date BETWEEN ? AND ?
              AND status = 'planned'
              {scope_sql}
            ORDER BY transaction_date ASC, id ASC
            """,
            [start.isoformat(), end.isoformat(), *scope_params],
        ).fetchall()

        debt_rows = connection.execute(
            f"""
            SELECT * FROM debts
            WHERE status = 'active'
              {scope_sql}
            ORDER BY current_balance DESC, id DESC
            """,
            scope_params,
        ).fetchall()

        recent_rows = connection.execute(
            f"""
            SELECT * FROM transactions
            WHERE 1 = 1 {scope_sql}
            ORDER BY transaction_date DESC, id DESC
            LIMIT 20
            """,
            scope_params,
        ).fetchall()

    paid = rows_to_dicts(paid_rows)
    planned = rows_to_dicts(planned_rows)
    debts = rows_to_dicts(debt_rows)

    sums = {
        "income": 0.0,
        "expense": 0.0,
        "savings": 0.0,
        "debt_payment": 0.0,
        "transfer": 0.0,
    }
    expense_categories: dict[str, float] = {}
    for row in paid:
        amount = float(row["amount"])
        sums[row["entry_type"]] = sums.get(row["entry_type"], 0.0) + amount
        if row["entry_type"] == "expense":
            category = row["category"] or "อื่น ๆ"
            expense_categories[category] = expense_categories.get(category, 0.0) + amount

    total_outflow = sums["expense"] + sums["savings"] + sums["debt_payment"]
    operating_cash_flow = sums["income"] - sums["expense"]
    net_cash_flow = sums["income"] - total_outflow
    planned_outflow = sum(
        float(row["amount"])
        for row in planned
        if row["entry_type"] in {"expense", "savings", "debt_payment"}
    )
    days = max((end - start).days + 1, 1)
    average_daily_expense = sums["expense"] / days

    active_debt_balance = sum(float(row["current_balance"]) for row in debts)
    active_monthly_payment = sum(float(row["monthly_payment"]) for row in debts)

    return {
        "period": period,
        "scope": scope,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "income": round(sums["income"], 2),
        "expense": round(sums["expense"], 2),
        "savings": round(sums["savings"], 2),
        "debt_payment": round(sums["debt_payment"], 2),
        "transfer": round(sums["transfer"], 2),
        "total_outflow": round(total_outflow, 2),
        "operating_cash_flow": round(operating_cash_flow, 2),
        "net_cash_flow": round(net_cash_flow, 2),
        "planned_outflow": round(planned_outflow, 2),
        "average_daily_expense": round(average_daily_expense, 2),
        "projected_30_day_expense": round(average_daily_expense * 30, 2),
        "active_debt_balance": round(active_debt_balance, 2),
        "active_monthly_payment": round(active_monthly_payment, 2),
        "expense_categories": [
            {"category": category, "amount": round(amount, 2)}
            for category, amount in sorted(
                expense_categories.items(), key=lambda item: item[1], reverse=True
            )
        ],
        "planned_transactions": planned,
        "active_debts": debts,
        "recent_transactions": rows_to_dicts(recent_rows),
    }


def finance_context(period: Period = "month", scope: str = "personal") -> dict:
    """Return compact, factual context suitable for the CFO agent prompt."""
    summary = dashboard_summary(period=period, scope=scope)
    return {
        "period": {
            "name": summary["period"],
            "start": summary["start_date"],
            "end": summary["end_date"],
            "scope": summary["scope"],
        },
        "cash_flow": {
            "income": summary["income"],
            "expense": summary["expense"],
            "savings": summary["savings"],
            "debt_payment": summary["debt_payment"],
            "net_cash_flow": summary["net_cash_flow"],
            "planned_outflow": summary["planned_outflow"],
        },
        "debt": {
            "total_balance": summary["active_debt_balance"],
            "monthly_payment": summary["active_monthly_payment"],
            "items": summary["active_debts"],
        },
        "expense_categories": summary["expense_categories"][:10],
        "recent_transactions": summary["recent_transactions"][:15],
        "data_limitations": (
            "ข้อมูลนี้มาจากรายการที่ผู้ใช้บันทึกใน Cpadd เท่านั้น "
            "ยอดบัญชีจริงหรือรายการที่ยังไม่ได้บันทึกอาจทำให้ภาพรวมคลาดเคลื่อน"
        ),
    }
