import uuid
from decimal import Decimal
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Numeric, ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin
from app.models.enums import PaymentStatus

if TYPE_CHECKING:
    from app.models.merchant import Merchant
    from app.models.customer import Customer
    from app.models.payment_attempt import PaymentAttempt

class Payment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "payments"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=PaymentStatus.PENDING.value, index=True, nullable=False
    )
    payment_method: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    bank: Mapped[Optional[str]] = mapped_column(String(30), index=True, nullable=True)
    device_type: Mapped[str] = mapped_column(String(30), nullable=False)
    route: Mapped[str] = mapped_column(String(50), nullable=False)

    # Provider References & Reconciliation
    provider_payment_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    provider_order_id: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    reconciliation_status: Mapped[Optional[str]] = mapped_column(String(50), default="PENDING", nullable=True)


    # Relationships
    merchant: Mapped["Merchant"] = relationship("Merchant", back_populates="payments")
    customer: Mapped["Customer"] = relationship("Customer", back_populates="payments")
    attempts: Mapped[List["PaymentAttempt"]] = relationship(
        "PaymentAttempt",
        back_populates="payment",
        cascade="all, delete-orphan",
        order_by="PaymentAttempt.attempt_number"
    )

    __table_args__ = (
        Index("ix_payments_merchant_status", "merchant_id", "status"),
        Index("ix_payments_merchant_created_at", "merchant_id", "created_at"),
    )
