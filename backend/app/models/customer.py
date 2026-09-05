import uuid
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import String, Numeric, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin
from app.models.enums import RiskSegment

class Customer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "customers"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    external_ref: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    risk_segment: Mapped[str] = mapped_column(
        String(20), default=RiskSegment.LOW.value, nullable=False
    )
    lifetime_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )

    # Relationships
    merchant: Mapped["Merchant"] = relationship("Merchant", back_populates="customers")
    payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="customer")
    subscriptions: Mapped[List["Subscription"]] = relationship("Subscription", back_populates="customer")
    checkout_sessions: Mapped[List["CheckoutSession"]] = relationship("CheckoutSession", back_populates="customer")
