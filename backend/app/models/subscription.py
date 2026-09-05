import uuid
from decimal import Decimal
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Numeric, ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin
from app.models.enums import SubscriptionStatus

if TYPE_CHECKING:
    from app.models.merchant import Merchant
    from app.models.customer import Customer
    from app.models.subscription_attempt import SubscriptionAttempt

class Subscription(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "subscriptions"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    plan_name: Mapped[str] = mapped_column(String(100), default="Pro Tier", nullable=False)
    plan_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    billing_cycle: Mapped[str] = mapped_column(String(20), default="monthly", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=SubscriptionStatus.ACTIVE.value, index=True, nullable=False
    )

    @property
    def amount(self) -> Decimal:
        return self.plan_amount

    # Relationships
    merchant: Mapped["Merchant"] = relationship("Merchant", back_populates="subscriptions")
    customer: Mapped["Customer"] = relationship("Customer", back_populates="subscriptions")
    attempts: Mapped[List["SubscriptionAttempt"]] = relationship(
        "SubscriptionAttempt",
        back_populates="subscription",
        cascade="all, delete-orphan",
        order_by="SubscriptionAttempt.attempted_at.desc()"
    )

    __table_args__ = (
        Index("ix_subscriptions_merchant_status", "merchant_id", "status"),
    )
