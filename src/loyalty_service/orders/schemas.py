from uuid import UUID

from pydantic import Field, field_validator

from loyalty_service.promotions.rules import validated_code
from loyalty_service.promotions.schemas import StrictModel


class OrderInput(StrictModel):
    plan_id: UUID
    promo_code: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator('promo_code')
    @classmethod
    def clean(cls, value):
        return validated_code(value) if value is not None else None


class AdminOrderInput(OrderInput):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator('reason')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('Укажите причину')
        return value.strip()
