import uuid
from decimal import Decimal
from datetime import datetime
from typing import List, Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, Numeric, JSON, DateTime, ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin
from app.models.enums import ActionType, ActionStatus

if TYPE_CHECKING:
    from app.models.recovery_opportunity import RecoveryOpportunity
    from app.models.policy_decision import PolicyDecision
    from app.models.agent_decision import AgentDecision
    from app.models.audit_event import AuditEvent

class RecoveryAction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "recovery_actions"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("recovery_opportunities.id", ondelete="CASCADE"), index=True, nullable=False
    )
    agent_decision_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_decisions.id", ondelete="SET NULL"), index=True, nullable=True
    )
    policy_decision_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("policy_decisions.id", ondelete="SET NULL"), index=True, nullable=True
    )
    provider: Mapped[str] = mapped_column(
        String(50), default="mock", index=True, nullable=False
    )
    action_type: Mapped[str] = mapped_column(
        String(50), default=ActionType.CREATE_PAYMENT_LINK.value, index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30), default=ActionStatus.PENDING.value, index=True, nullable=False
    )
    amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    request: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True
    )
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON, nullable=True
    )
    reason: Mapped[Optional[str]] = mapped_column(
        Text, default="", nullable=True
    )
    predicted_outcome: Mapped[Optional[str]] = mapped_column(
        String(150), default="", nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(128), index=True, nullable=True
    )
    causal_trace_id: Mapped[Optional[str]] = mapped_column(
        String(64), index=True, nullable=True
    )
    verified_status: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    actual_recovered_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )

    # Convenience properties
    @property
    def action_id(self) -> uuid.UUID:
        return self.id

    @property
    def execution_result(self) -> Optional[Dict[str, Any]]:
        return self.result

    @execution_result.setter
    def execution_result(self, val: Optional[Dict[str, Any]]) -> None:
        self.result = val

    @property
    def notes(self) -> Optional[str]:
        if self.reason and "Notes: " in self.reason:
            return self.reason.split("Notes: ", 1)[1]
        return self.reason

    # Relationships
    opportunity: Mapped["RecoveryOpportunity"] = relationship("RecoveryOpportunity", back_populates="recovery_actions")
    policy_decision: Mapped[Optional["PolicyDecision"]] = relationship("PolicyDecision", back_populates="recovery_actions")
    agent_decision: Mapped[Optional["AgentDecision"]] = relationship("AgentDecision")
    audit_events: Mapped[List["AuditEvent"]] = relationship("AuditEvent", back_populates="action")

    __table_args__ = (
        Index("ix_rec_actions_opp_status", "opportunity_id", "status"),
        Index("ix_rec_actions_opp_type_status", "opportunity_id", "action_type", "status"),
    )
