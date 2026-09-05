import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy import String, Text, DateTime, ForeignKey, Index, Uuid, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class AgentRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Persistent audit record of an AI Recovery Agent execution.
    Tracks state machine lifecycle, operational diagnosis, recommendations,
    policy evaluation, and complete causal trace.
    """
    __tablename__ = "agent_runs"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    trigger: Mapped[str] = mapped_column(
        String(50), default="auto", index=True, nullable=False
    )
    trigger_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    current_state: Mapped[str] = mapped_column(
        String(50), default="OBSERVE", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(30), default="RUNNING", index=True, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )
    model_version: Mapped[str] = mapped_column(
        String(64), default="recovery_probability_v1", nullable=False
    )
    causal_trace_id: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False
    )

    # Operational artifacts and diagnostics
    problem: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diagnosis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    policy_verdict: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    execution_logs_json: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    decision_summary: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    @property
    def agent_run_id(self) -> uuid.UUID:
        return self.id

    __table_args__ = (
        Index("ix_agent_runs_merchant_status", "merchant_id", "status"),
        Index("ix_agent_runs_causal_trace", "causal_trace_id"),
    )
