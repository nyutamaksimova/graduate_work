import hashlib

from fastapi import Request
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def make_sessions(url):
    return sessionmaker(create_engine(url, pool_pre_ping=True), expire_on_commit=False)


def get_session(request: Request):
    with request.app.state.sessions() as session:
        yield session


def lock_user(session, user_id):
    if session.bind.dialect.name == 'postgresql':
        key = int.from_bytes(hashlib.sha256(user_id.bytes).digest()[:8], 'big', signed=True)
        session.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': key})
