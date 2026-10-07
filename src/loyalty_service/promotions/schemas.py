from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from .rules import validated_code


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', from_attributes=True)


class PlanInput(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    price_kopecks: int = Field(ge=0, le=100_000_000, strict=True)
    duration_days: int = Field(gt=0, le=3650, strict=True)


class BenefitInput(StrictModel):
    benefit_type: Literal['FIXED_PRICE', 'PERCENT_DISCOUNT', 'TRIAL']
    benefit_value: int = Field(default=0, ge=0, le=100_000_000, strict=True)
    trial_days: int | None = Field(default=None, gt=0, le=3650, strict=True)
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None
    active: bool = True
    max_redemptions: int | None = Field(default=None, gt=0, strict=True)
    per_user_limit: int = Field(default=1, gt=0, strict=True)
    plan_id: UUID | None = None
    assigned_user_id: UUID | None = None

    @model_validator(mode='after')
    def check_benefit(self):
        if self.benefit_type == 'PERCENT_DISCOUNT' and not 1 <= self.benefit_value <= 100:
            raise ValueError('Процент должен быть от 1 до 100')
        if self.benefit_type == 'TRIAL' and (self.trial_days is None or self.benefit_value != 0):
            raise ValueError('TRIAL требует trial_days и benefit_value=0')
        if self.benefit_type != 'TRIAL' and self.trial_days is not None:
            raise ValueError('trial_days допустим только для TRIAL')
        if self.valid_from and self.valid_until and self.valid_from >= self.valid_until:
            raise ValueError('valid_until должен быть позже valid_from')
        return self


class CodeInput(BenefitInput):
    code: str = Field(min_length=1, max_length=64)

    @field_validator('code')
    @classmethod
    def clean_code(cls, value):
        return validated_code(value)


class GenerateInput(BenefitInput):
    count: int = Field(ge=1, le=1000, strict=True)
    prefix: str = Field(default='', max_length=20, pattern=r'^[A-Za-z0-9_-]*$')


class PreviewInput(StrictModel):
    plan_id: UUID
    code: str = Field(min_length=1, max_length=64)

    @field_validator('code')
    @classmethod
    def clean_code(cls, value):
        return validated_code(value)


class CodePatch(StrictModel):
    active: bool
