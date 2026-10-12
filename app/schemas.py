import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.models import Currency, PaymentStatus


class PaymentCreate(BaseModel):
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    currency: Currency
    description: str | None = Field(None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: HttpUrl

    @field_validator("amount")
    @classmethod
    def quantize_amount(cls, v: Decimal) -> Decimal:
        return v.quantize(Decimal("0.01"))


class PaymentCreated(BaseModel):
    payment_id: uuid.UUID
    status: PaymentStatus
    created_at: datetime


class PaymentDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount: Decimal
    currency: Currency
    description: str | None
    metadata: dict[str, Any] = Field(validation_alias="payment_metadata")
    status: PaymentStatus
    webhook_url: str
    created_at: datetime
    processed_at: datetime | None