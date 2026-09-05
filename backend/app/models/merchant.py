from typing import List, Dict, Any
from sqlalchemy import String, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

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
