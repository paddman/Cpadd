import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import get_settings


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_date TEXT NOT NULL,
    entry_type TEXT NOT NULL CHECK(entry_type IN (
        'income', 'expense', 'savings', 'debt_payment', 'transfer'
    )),
    category TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount >= 0),
    account TEXT NOT NULL DEFAULT 'cash',
    scope TEXT NOT NULL DEFAULT 'personal' CHECK(scope IN (
        'personal', 'business', 'company_advance'
    )),
    status TEXT NOT NULL DEFAULT 'paid' CHECK(status IN ('paid', 'planned')),
    merchant TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transactions_date
ON transactions(transaction_date);

CREATE INDEX IF NOT EXISTS idx_transactions_scope_status
ON transactions(scope, status);

CREATE TABLE IF NOT EXISTS debts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    debt_type TEXT NOT NULL DEFAULT 'installment',
    original_amount REAL NOT NULL DEFAULT 0 CHECK(original_amount >= 0),
    current_balance REAL NOT NULL CHECK(current_balance >= 0),
    monthly_payment REAL NOT NULL DEFAULT 0 CHECK(monthly_payment >= 0),
    interest_rate REAL NOT NULL DEFAULT 0 CHECK(interest_rate >= 0),
    total_installments INTEGER,
    paid_installments INTEGER NOT NULL DEFAULT 0,
    due_day INTEGER CHECK(due_day BETWEEN 1 AND 31),
    scope TEXT NOT NULL DEFAULT 'personal' CHECK(scope IN (
        'personal', 'business', 'company_advance'
    )),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'closed')),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    database_path = Path(get_settings().database_path).expanduser()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(SCHEMA)


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def get_setting(key: str) -> str | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO app_settings(key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, value),
        )
