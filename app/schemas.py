from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


EntryType = Literal["income", "expense", "savings", "debt_payment", "transfer"]
ScopeType = Literal["personal", "business", "company_advance"]
StatusType = Literal["paid", "planned"]
DebtStatus = Literal["active", "closed"]


class TransactionCreate(BaseModel):
    transaction_date: date = Field(default_factory=date.today)
    entry_type: EntryType
    category: str = Field(min_length=1, max_length=80)
    amount: float = Field(ge=0)
    account: str = Field(default="cash", min_length=1, max_length=80)
    scope: ScopeType = "personal"
    status: StatusType = "paid"
    merchant: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=500)

    @field_validator("category", "account", "merchant", "note")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class DebtCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    debt_type: str = Field(default="installment", max_length=50)
    original_amount: float = Field(default=0, ge=0)
    current_balance: float = Field(ge=0)
    monthly_payment: float = Field(default=0, ge=0)
    interest_rate: float = Field(default=0, ge=0, le=100)
    total_installments: int | None = Field(default=None, ge=1)
    paid_installments: int = Field(default=0, ge=0)
    due_day: int | None = Field(default=None, ge=1, le=31)
    scope: ScopeType = "personal"
    status: DebtStatus = "active"
    note: str = Field(default="", max_length=500)

    @field_validator("name", "debt_type", "note")
    @classmethod
    def strip_debt_text(cls, value: str) -> str:
        return value.strip()


class DebtUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    debt_type: str | None = Field(default=None, max_length=50)
    original_amount: float | None = Field(default=None, ge=0)
    current_balance: float | None = Field(default=None, ge=0)
    monthly_payment: float | None = Field(default=None, ge=0)
    interest_rate: float | None = Field(default=None, ge=0, le=100)
    total_installments: int | None = Field(default=None, ge=1)
    paid_installments: int | None = Field(default=None, ge=0)
    due_day: int | None = Field(default=None, ge=1, le=31)
    scope: ScopeType | None = None
    status: DebtStatus | None = None
    note: str | None = Field(default=None, max_length=500)


class QwenSettingsUpdate(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = Field(default=None, max_length=500)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=1200, ge=64, le=32768)
    timeout_seconds: int = Field(default=120, ge=5, le=600)

    @field_validator("base_url", "model")
    @classmethod
    def strip_qwen_text(cls, value: str) -> str:
        return value.strip().rstrip("/") if "http" in value else value.strip()


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    period: Literal["day", "week", "month", "year"] = "month"
    scope: ScopeType | Literal["all"] = "personal"


class StatementCommitRequest(BaseModel):
    selected_indices: list[int] | None = None
    scope: ScopeType | None = None
    account: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("selected_indices")
    @classmethod
    def unique_indices(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if any(index < 0 for index in value):
            raise ValueError("selected_indices ต้องไม่ติดลบ")
        return sorted(set(value))

    @field_validator("account")
    @classmethod
    def strip_account(cls, value: str | None) -> str | None:
        return value.strip() if value else value
