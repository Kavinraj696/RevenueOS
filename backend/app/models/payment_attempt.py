import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, DateTime, ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDPrimaryKeyMixin, get_utc_now
from app.models.enums import PaymentAttemptStatus

class PaymentAttempt(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "payment_attempts"

    payment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("payments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=PaymentAttemptStatus.FAILED.value, nullable=False
    )
    failure_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), index=True, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now, nullable=False, index=True
    )

    # Relationships
    payment: Mapped["Payment"] = relationship("Payment", back_populates="attempts")

    __table_args__ = (
        Index("ix_payment_attempts_payment_attempt_num", "payment_id", "attempt_number"),
    )
