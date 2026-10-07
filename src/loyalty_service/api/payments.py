from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from loyalty_service.auth import Principal, require_admin
from loyalty_service.db import get_session
from loyalty_service.errors import DomainError
from loyalty_service.payments.schemas import ResolveInput
from loyalty_service.payments.service import resolve_payment
from .common import serialize

router = APIRouter(prefix='/api/v1/admin/payments', tags=['Mock payments'])


@router.post('/{order_id}/resolve')
def resolve(order_id: UUID, payload: ResolveInput, request: Request,
            actor: Principal = Depends(require_admin), session: Session = Depends(get_session)):
    settings = request.app.state.settings
    if settings.payment_mode != 'mock' or not settings.enable_mock_payment_control:
        raise DomainError('MOCK_CONTROL_DISABLED', 'Управление тестовыми платежами отключено', 403)
    order, error = resolve_payment(session, order_id, payload.outcome, actor.user_id)
    session.commit()
    if error:
        raise error
    return serialize(order)
