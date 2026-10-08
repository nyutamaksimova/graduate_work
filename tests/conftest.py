import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from loyalty_service.config import Settings
from loyalty_service.main import create_app
from loyalty_service.models import Base

SECRET = 'test-secret-for-loyalty-at-least-32-characters'


class AllowPromoAttempts:
    def admit(self, user_id, ip):
        pass

    def record_failure(self, user_id, ip):
        pass


def token(user_id, role='USER', expired=False):
    return jwt.encode({'sub': str(user_id), 'role': role, 'is_superuser': False,
        'exp': datetime.now(UTC) + timedelta(minutes=-1 if expired else 30)}, SECRET, algorithm='HS256')


@pytest.fixture
def system():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    settings = Settings(database_url='sqlite://', jwt_secret=SECRET,
        internal_api_token='test-internal-token', enable_mock_payment_control=True)
    sessions = sessionmaker(engine, expire_on_commit=False)
    app = create_app(settings, sessions, promo_guard=AllowPromoAttempts())
    user_id, admin_id = uuid4(), uuid4()
    with TestClient(app) as client:
        yield client, sessions, user_id, {'Authorization': 'Bearer '+token(user_id)}, {
            'Authorization': 'Bearer '+token(admin_id, 'ADMIN')}
    engine.dispose()


@pytest.fixture
def pg_sessions():
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to a dedicated disposable PostgreSQL database')
    engine = create_engine(url, pool_size=8)
    assert engine.dialect.name == 'postgresql'
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    Base.metadata.drop_all(engine)
    engine.dispose()
