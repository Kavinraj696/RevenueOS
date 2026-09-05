import uuid
from decimal import Decimal
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Numeric, DateTime, ForeignKey, Index, Uuid, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin, get_utc_now
from app.models.enums import OpportunityStatus

if TYPE_CHECKING:
    from app.models.revenue_leak import RevenueLeak
    from app.models.merchant import Merchant
    from app.models.customer import Customer
    from app.models.payment import Payment
    from app.models.agent_decision import AgentDecision
    from app.models.recovery_action import RecoveryAction

class RecoveryOpportunity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "recovery_opportunities"

    revenue_leak_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("revenue_leaks.id", ondelete="SET NULL"), index=True, nullable=True
    )
    merchant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), index=True, nullable=True
    )
    payment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("payments.id", ondelete="SET NULL"), index=True, nullable=True
    )

    gross_value_affected: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    potentially_recoverable_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    recovery_probability: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.0000"), nullable=False
    )
    expected_recovered_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0.00"), nullable=False
    )
    actual_recovered_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=OpportunityStatus.OPEN.value, index=True, nullable=False
    )
    priority: Mapped[str] = mapped_column(
        String(20), default="MEDIUM", index=True, nullable=False
    )
    priority_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), index=True, nullable=False
    )
    risk: Mapped[str] = mapped_column(
        String(20), default="low", nullable=False
    )
    failure_reason: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    explanation: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    recommended_actions_json: Mapped[Optional[list]] = mapped_column(
        JSON, nullable=True
    )
    model_version: Mapped[Optional[str]] = mapped_column(
        String(50), default="recovery_probability_v1", nullable=True
    )
    feature_version: Mapped[Optional[str]] = mapped_column(
        String(50), default="v1.0.0", nullable=True
    )
    prediction_time: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), default=get_utc_now, nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now, nullable=False
    )

    @property
    def transaction_id(self) -> Optional[uuid.UUID]:
        return self.payment_id

    @property
    def eligible_revenue(self) -> Decimal:
        return self.potentially_recoverable_value

    @property
    def expected_recovery_value(self) -> Decimal:
        return self.expected_recovered_value

    @property
    def opportunity_score(self) -> Decimal:
        return self.priority_score

    @property
    def rank(self) -> Optional[int]:
        return getattr(self, "_rank", None)

    @rank.setter
    def rank(self, val: Optional[int]):
        self._rank = val

    @property
    def transaction_amount(self) -> Decimal:
        return self.gross_value_affected

    @property
    def expected_recoverable_amount(self) -> Decimal:
        return self.expected_recovered_value

    @property
    def recommended_action_candidates(self) -> list:
        return self.recommended_actions_json or []

    @property
    def gross_affected_revenue(self) -> Decimal:
        return self.gross_value_affected

    @property
    def revenue_at_risk(self) -> Decimal:
        return self.potentially_recoverable_value

    @property
    def potentially_recoverable_revenue(self) -> Decimal:
        return self.potentially_recoverable_value

    @property
    def expected_recovery(self) -> Decimal:
        return self.expected_recovered_value

    @property
    def actual_recovery(self) -> Decimal:
        return self.actual_recovered_value or Decimal("0.00")

    @property
    def suggested_action(self) -> Optional[str]:
        if self.recommended_actions_json and len(self.recommended_actions_json) > 0:
            return self.recommended_actions_json[0].get("title")
        return "Automated recovery workflow"

    @property
    def description(self) -> Optional[str]:
        return self.explanation or f"Recovery opportunity for ₹{self.gross_value_affected}"

    @property
    def actions(self) -> List["RecoveryAction"]:
        return self.recovery_actions or []


    # Relationships
    revenue_leak: Mapped[Optional["RevenueLeak"]] = relationship("RevenueLeak", back_populates="opportunities")
    merchant: Mapped["Merchant"] = relationship("Merchant", back_populates="recovery_opportunities")
    customer: Mapped[Optional["Customer"]] = relationship("Customer")
    payment: Mapped[Optional["Payment"]] = relationship("Payment")
    agent_decisions: Mapped[List["AgentDecision"]] = relationship(
        "AgentDecision", back_populates="opportunity", cascade="all, delete-orphan"
    )
    recovery_actions: Mapped[List["RecoveryAction"]] = relationship(
        "RecoveryAction", back_populates="opportunity", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_rec_opps_merchant_priority", "merchant_id", "priority_score"),
        Index("ix_rec_opps_merchant_status", "merchant_id", "status"),
    )
