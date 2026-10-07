from typing import Protocol

from loyalty_service.models import Order, Payment


class PaymentAdapter(Protocol):
    def create(self, order: Order) -> Payment: ...


class MockPaymentAdapter:
    def create(self, order: Order) -> Payment:
        return Payment(order_id=order.id, amount_kopecks=order.final_price_kopecks, currency=order.currency)
