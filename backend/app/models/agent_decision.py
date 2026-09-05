import uuid
from decimal import Decimal
from typing import List, Optional, Dict, Any
from sqlalchemy import String, Text, Numeric, JSON, ForeignKey, Index, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

class AgentDecision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agent_decisions"

    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("recovery_opportunities.id", ondelete="CASCADE"), index=True, nullable=False
    )
    problem: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    estimated_impact: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    recovery_probability: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    recommended_action: Mapped[str] = mapped_column(String(30), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), default="low", nullable=False)
    expected_recovery: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    actual_recovery: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)

    # Relationships
    opportunity: Mapped["RecoveryOpportunity"] = relationship("RecoveryOpportunity", back_populates="agent_decisions")
    policy_decisions: Mapped[List["PolicyDecision"]] = relationship(
        "PolicyDecision", back_populates="agent_decision", cascade="all, delete-orphan"
    )
    audit_events: Mapped[List["AuditEvent"]] = relationship("AuditEvent", back_populates="agent_decision")

    __table_args__ = (
        Index("ix_agent_decisions_opp_id", "opportunity_id"),
    )
