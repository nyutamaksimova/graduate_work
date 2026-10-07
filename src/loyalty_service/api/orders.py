from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.orm import Session

from loyalty_service.auth import Principal, get_current_user
from loyalty_service.db import get_session
from loyalty_service.errors import DomainError
from loyalty_service.orders.schemas import OrderInput
from loyalty_service.orders.service import create_order, get_order
from loyalty_service.promotions.service import record_attempt
from .common import serialize

router = APIRouter(prefix='/api/v1/orders', tags=['Orders'])


def submit_order(session, request, payload, key, user_id, actor_id, reason=None):
    try:
        order, created = create_order(session, user_id, payload, key, actor_id, reason,
            request.app.state.settings.reservation_minutes)
        if created and payload.promo_code:
            record_attempt(session, user_id, payload.promo_code, True, None, request.state.request_id)
        session.commit()
        return serialize(order), created
    except DomainError as exc:
        session.rollback()
        if payload.promo_code:
            record_attempt(session, user_id, payload.promo_code, False, exc.code, request.state.request_id)
            session.commit()
        raise


@router.post('', status_code=201)
def purchase(payload: OrderInput, request: Request, response: Response,
             idempotency_key: str = Header(min_length=1, max_length=128),
             user: Principal = Depends(get_current_user), session: Session = Depends(get_session)):
    result, created = submit_order(session, request, payload, idempotency_key, user.user_id, user.user_id)
    response.status_code = 201 if created else 200
    return result


@router.get('/{order_id}')
def read_order(order_id: UUID, user: Principal = Depends(get_current_user), session: Session = Depends(get_session)):
    return serialize(get_order(session, order_id, user))
