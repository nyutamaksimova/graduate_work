from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint, \
    Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow():
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError('timezone-aware datetime required')
            return value.astimezone(UTC)
        return None

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class Identity:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Plan(Identity, Base):
    __tablename__ = 'plans'
    __table_args__ = (CheckConstraint('price_kopecks >= 0 AND duration_days > 0'),)
    name: Mapped[str] = mapped_column(String(100))
    price_kopecks: Mapped[int] = mapped_column(Integer)
    duration_days: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PromoCode(Identity, Base):
    __tablename__ = 'promo_codes'
    __table_args__ = (
        CheckConstraint("benefit_type IN ('FIXED_PRICE','PERCENT_DISCOUNT','TRIAL')"),
        CheckConstraint('benefit_value >= 0'),
        CheckConstraint("benefit_type != 'PERCENT_DISCOUNT' OR benefit_value BETWEEN 1 AND 100"),
        CheckConstraint("benefit_type != 'TRIAL' OR (trial_days IS NOT NULL AND trial_days > 0 AND benefit_value = 0)"),
        CheckConstraint('max_redemptions IS NULL OR max_redemptions > 0'),
        CheckConstraint('per_user_limit > 0'),
        CheckConstraint('valid_from IS NULL OR valid_until IS NULL OR valid_from < valid_until'),
    )
    code: Mapped[str] = mapped_column(String(64), unique=True)
    benefit_type: Mapped[str] = mapped_column(String(24))
    benefit_value: Mapped[int] = mapped_column(Integer)
    trial_days: Mapped[int | None] = mapped_column(Integer)
    valid_from: Mapped[datetime | None] = mapped_column(UTCDateTime)
    valid_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_redemptions: Mapped[int | None] = mapped_column(Integer)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)
    plan_id: Mapped[UUID | None] = mapped_column(ForeignKey('plans.id'))
    assigned_user_id: Mapped[UUID | None] = mapped_column(Uuid)


class Order(Identity, Base):
    __tablename__ = 'orders'
    __table_args__ = (
        UniqueConstraint('user_id', 'idempotency_key'),
        CheckConstraint('base_price_kopecks >= 0 AND final_price_kopecks >= 0 AND duration_days > 0'),
        CheckConstraint("status IN ('PENDING','PAID','COMPLETED_FREE','FAILED','CANCELLED')"),
        Index('ix_orders_pending_expiry', 'status', 'expires_at'),
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey('plans.id'))
    promo_code_id: Mapped[UUID | None] = mapped_column(ForeignKey('promo_codes.id'))
    base_price_kopecks: Mapped[int] = mapped_column(Integer)
    final_price_kopecks: Mapped[int] = mapped_column(Integer)
    duration_days: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default='RUB')
    status: Mapped[str] = mapped_column(String(24), default='PENDING')
    idempotency_key: Mapped[str] = mapped_column(String(128))
    fingerprint: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PromoRedemption(Identity, Base):
    __tablename__ = 'promo_redemptions'
    __table_args__ = (CheckConstraint("status IN ('RESERVED','APPLIED','RELEASED')"),
                      Index('ix_redemptions_limits', 'promo_code_id', 'user_id', 'status'))
    promo_code_id: Mapped[UUID] = mapped_column(ForeignKey('promo_codes.id'))
    user_id: Mapped[UUID] = mapped_column(Uuid)
    order_id: Mapped[UUID] = mapped_column(ForeignKey('orders.id'), unique=True)
    status: Mapped[str] = mapped_column(String(16), default='RESERVED')
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    reason: Mapped[str | None] = mapped_column(String(500))


class Payment(Identity, Base):
    __tablename__ = 'payments'
    __table_args__ = (CheckConstraint("status IN ('PENDING','SUCCEEDED','FAILED','CANCELLED')"),)
    order_id: Mapped[UUID] = mapped_column(ForeignKey('orders.id'), unique=True)
    status: Mapped[str] = mapped_column(String(16), default='PENDING')
    amount_kopecks: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default='RUB')


class Subscription(Identity, Base):
    __tablename__ = 'subscriptions'
    user_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime)


class SubscriptionGrant(Identity, Base):
    __tablename__ = 'subscription_grants'
    order_id: Mapped[UUID] = mapped_column(ForeignKey('orders.id'), unique=True)
    user_id: Mapped[UUID] = mapped_column(Uuid)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PromoAttempt(Identity, Base):
    __tablename__ = 'promo_attempts'
    user_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    code: Mapped[str] = mapped_column(String(64))
    success: Mapped[bool] = mapped_column(Boolean)
    error_code: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str] = mapped_column(String(64))


class AuditLog(Identity, Base):
    __tablename__ = 'audit_log'
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[UUID] = mapped_column(Uuid)
    reason: Mapped[str | None] = mapped_column(String(500))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
