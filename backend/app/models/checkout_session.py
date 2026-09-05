import uuid
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, Numeric, ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin
from app.models.enums import CheckoutSessionStatus

if TYPE_CHECKING:
    from app.models.merchant import Merchant
    from app.models.customer import Customer

class CheckoutSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "checkout_sessions"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), index=True, nullable=True
    )
    cart_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=CheckoutSessionStatus.ABANDONED.value, index=True, nullable=False
    )
    stage_dropped: Mapped[Optional[str]] = mapped_column(String(50), index=True, nullable=True)
    device_type: Mapped[str] = mapped_column(String(30), default="mobile_web", nullable=False)

    # Relationships
    merchant: Mapped["Merchant"] = relationship("Merchant", back_populates="checkout_sessions")
    customer: Mapped[Optional["Customer"]] = relationship("Customer", back_populates="checkout_sessions")

    __table_args__ = (
        Index("ix_checkout_sessions_merchant_status", "merchant_id", "status"),
        Index("ix_checkout_sessions_merchant_stage", "merchant_id", "stage_dropped"),
    )
