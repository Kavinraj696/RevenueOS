import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, DateTime, ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDPrimaryKeyMixin, get_utc_now
from app.models.enums import PaymentAttemptStatus

class SubscriptionAttempt(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "subscription_attempts"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("subscriptions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default=PaymentAttemptStatus.FAILED.value, nullable=False
    )
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now, nullable=False, index=True
    )

    # Relationships
    subscription: Mapped["Subscription"] = relationship("Subscription", back_populates="attempts")

    __table_args__ = (
        Index("ix_sub_attempts_sub_time", "subscription_id", "attempted_at"),
    )
