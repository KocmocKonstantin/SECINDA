from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from app.db.models import Currency, PaymentStatus


class PaymentCreate(BaseModel):
    amount: Decimal
    currency: Currency
    description: str = Field(min_length=1, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: HttpUrl
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("amount")
    @classmethod
    def normalize_amount(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("amount must be positive")
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class PaymentCreateResponse(BaseModel):
    payment_id: UUID
    status: PaymentStatus
    created_at: datetime


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    amount: Decimal
    currency: Currency
    description: str
    metadata: dict[str, Any]
    status: PaymentStatus
    idempotency_key: str
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None = None
    webhook_sent_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def convert_orm(cls, data: Any) -> Any:
        # ORM-объект Payment имеет атрибут meta, а в API отдаём metadata.
        if hasattr(data, "meta"):
            return {
                "id": data.id,
                "amount": data.amount,
                "currency": data.currency,
                "description": data.description,
                "metadata": data.meta,
                "status": data.status,
                "idempotency_key": data.idempotency_key,
                "webhook_url": data.webhook_url,
                "created_at": data.created_at,
                "processed_at": data.processed_at,
                "webhook_sent_at": data.webhook_sent_at,
            }
        return data