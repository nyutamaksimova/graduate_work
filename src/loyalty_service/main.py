import logging
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .api import admin, orders, payments, promotions, subscriptions
from .config import Settings
from .db import get_session, make_sessions
from .errors import DomainError

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, sessions=None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title='Cinema Loyalty Service', version='0.1.0')
    app.state.settings = settings
    app.state.sessions = sessions or make_sessions(settings.database_url)

    @app.middleware('http')
    async def request_id(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers['X-Request-Id'] = request.state.request_id
        return response

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status_code, content={'error': {
            'code': exc.code, 'message': exc.message, 'request_id': request.state.request_id}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        details = [{'location': list(error['loc']), 'message': error['msg']} for error in exc.errors()]
        return JSONResponse(status_code=422, content={'error': {'code': 'VALIDATION_ERROR',
            'message': 'Некорректные параметры запроса', 'request_id': request.state.request_id,
            'details': details}})

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        logger.error('database_error request_id=%s type=%s', request.state.request_id, type(exc).__name__)
        return JSONResponse(status_code=503, content={'error': {'code': 'DATABASE_UNAVAILABLE',
            'message': 'Ошибка хранилища; повторите запрос с тем же Idempotency-Key',
            'request_id': request.state.request_id}})

    @app.get('/health', tags=['Health'])
    def health():
        return {'status': 'ok', 'payment_mode': settings.payment_mode}

    @app.get('/ready', tags=['Health'])
    def ready(session: Session = Depends(get_session)):
        session.execute(text('SELECT 1'))
        return {'status': 'ready'}

    for router in (promotions.router, orders.router, admin.router, payments.router, subscriptions.router):
        app.include_router(router)
    return app
