import uuid
from decimal import Decimal
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy import String, Integer, Numeric, Text, JSON, DateTime, ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin
from app.models.enums import LeakType

class RevenueLeak(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "revenue_leaks"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    leak_type: Mapped[str] = mapped_column(
        String(50), default=LeakType.PAYMENT_FAILURE.value, index=True, nullable=False
    )
    pattern_description: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Financial metrics
    gross_value_affected: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    affected_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    revenue_at_risk: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("0.00"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    
    # Quantitative metrics
    affected_transactions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.9000"), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="high", index=True, nullable=False)
    severity_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("7.50"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="open", index=True, nullable=False)

    # Diagnostic data
    root_cause_candidates: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Detection window
    detection_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detection_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    merchant: Mapped["Merchant"] = relationship("Merchant", back_populates="revenue_leaks")
    opportunities: Mapped[List["RecoveryOpportunity"]] = relationship(
        "RecoveryOpportunity", back_populates="revenue_leak", cascade="all, delete-orphan"
    )

    @property
    def type(self) -> str:
        return self.leak_type

    __table_args__ = (
        Index("ix_revenue_leaks_merchant_type", "merchant_id", "leak_type"),
        Index("ix_revenue_leaks_merchant_status", "merchant_id", "status"),
        Index("ix_revenue_leaks_merchant_severity", "merchant_id", "severity"),
    )
