import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from conftest import SECRET
from loyalty_service.config import Settings
from loyalty_service.models import PromoCode


def test_real_payment_mode_rejected():
    with pytest.raises(ValidationError):
        Settings(jwt_secret=SECRET, internal_api_token='test-internal-token', payment_mode='real')


def test_duplicate_code_database_constraint(system):
    with system[1]() as s:
        for _ in range(2):
            s.add(PromoCode(code='UNIQUE', benefit_type='FIXED_PRICE', benefit_value=0))
        with pytest.raises(IntegrityError):
            s.commit()


def test_invalid_percent_database_constraint(system):
    with system[1]() as s:
        s.add(PromoCode(code='BAD', benefit_type='PERCENT_DISCOUNT', benefit_value=101))
        with pytest.raises(IntegrityError):
            s.commit()
