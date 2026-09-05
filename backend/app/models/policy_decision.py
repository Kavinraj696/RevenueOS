import uuid
from decimal import Decimal
from typing import List, Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, Numeric, Integer, Boolean, ForeignKey, Index, Uuid, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.agent_decision import AgentDecision
    from app.models.recovery_opportunity import RecoveryOpportunity
    from app.models.recovery_action import RecoveryAction

class PolicyDecision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "policy_decisions"

    agent_decision_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_decisions.id", ondelete="CASCADE"), index=True, nullable=True
    )
    opportunity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("recovery_opportunities.id", ondelete="CASCADE"), index=True, nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(60), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="low", nullable=False)
    max_amount_allowed: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("15000.00"), nullable=False
    )
    retry_limit: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=14400, nullable=False)
    confidence_threshold: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.6000"), nullable=False
    )
    limits_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    decision_reason: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    agent_decision: Mapped[Optional["AgentDecision"]] = relationship("AgentDecision", back_populates="policy_decisions")
    opportunity: Mapped[Optional["RecoveryOpportunity"]] = relationship("RecoveryOpportunity")
    recovery_actions: Mapped[List["RecoveryAction"]] = relationship(
        "RecoveryAction", back_populates="policy_decision"
    )

    __table_args__ = (
        Index("ix_policy_decisions_agent_allowed", "agent_decision_id", "allowed"),
        Index("ix_policy_decisions_opp_allowed", "opportunity_id", "allowed"),
    )

