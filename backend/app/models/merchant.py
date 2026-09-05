from typing import List, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.payment import Payment
    from app.models.subscription import Subscription
    from app.models.checkout_session import CheckoutSession
    from app.models.revenue_leak import RevenueLeak
    from app.models.recovery_opportunity import RecoveryOpportunity
    from app.models.audit_event import AuditEvent

class Merchant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "merchants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    settings_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Relationships
    customers: Mapped[List["Customer"]] = relationship(
        "Customer", back_populates="merchant", cascade="all, delete-orphan"
    )
    payments: Mapped[List["Payment"]] = relationship(
        "Payment", back_populates="merchant", cascade="all, delete-orphan"
    )
    subscriptions: Mapped[List["Subscription"]] = relationship(
        "Subscription", back_populates="merchant", cascade="all, delete-orphan"
    )
    checkout_sessions: Mapped[List["CheckoutSession"]] = relationship(
        "CheckoutSession", back_populates="merchant", cascade="all, delete-orphan"
    )
    revenue_leaks: Mapped[List["RevenueLeak"]] = relationship(
        "RevenueLeak", back_populates="merchant", cascade="all, delete-orphan"
    )
    recovery_opportunities: Mapped[List["RecoveryOpportunity"]] = relationship(
        "RecoveryOpportunity", back_populates="merchant", cascade="all, delete-orphan"
    )
    audit_events: Mapped[List["AuditEvent"]] = relationship(
        "AuditEvent", back_populates="merchant", cascade="all, delete-orphan"
    )
