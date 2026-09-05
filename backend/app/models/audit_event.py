import uuid
from datetime import datetime
from typing import Optional, Dict, Any, TYPE_CHECKING
from sqlalchemy import String, Text, ForeignKey, Index, Uuid, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, UUIDPrimaryKeyMixin, TimestampMixin
from app.models.enums import AuditActor

if TYPE_CHECKING:
    from app.models.merchant import Merchant
    from app.models.agent_decision import AgentDecision
    from app.models.recovery_action import RecoveryAction

class AuditEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "audit_events"

    merchant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), index=True, nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(50), default=AuditActor.SYSTEM.value, index=True, nullable=False)

    transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), index=True, nullable=True
    )
    opportunity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), index=True, nullable=True
    )
    action_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("recovery_actions.id", ondelete="SET NULL"), index=True, nullable=True
    )
    agent_decision_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("agent_decisions.id", ondelete="SET NULL"), index=True, nullable=True
    )
    policy_decision_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("policy_decisions.id", ondelete="SET NULL"), index=True, nullable=True
    )

    status: Mapped[str] = mapped_column(String(30), default="SUCCESS", index=True, nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Backward compatibility columns
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    related_entity_type: Mapped[Optional[str]] = mapped_column(String(50), index=True, nullable=True)
    related_entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid(as_uuid=True), index=True, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(100), default="", nullable=True)

    def __init__(self, **kwargs):
        # Auto-map message to summary and vice versa
        if "summary" in kwargs and "message" not in kwargs:
            kwargs["message"] = kwargs["summary"]
        elif "message" in kwargs and "summary" not in kwargs:
            kwargs["summary"] = kwargs["message"]

        # Auto-map metadata to metadata_json
        if "metadata" in kwargs:
            meta_val = kwargs.pop("metadata")
            if "metadata_json" not in kwargs:
                kwargs["metadata_json"] = meta_val

        # Map related_entity_id to specific FK if appropriate
        if "related_entity_id" in kwargs and kwargs.get("related_entity_id"):
            rel_type = kwargs.get("related_entity_type", "")
            if rel_type == "recovery_action" and "action_id" not in kwargs:
                kwargs["action_id"] = kwargs["related_entity_id"]
            elif rel_type == "payment" and "transaction_id" not in kwargs:
                kwargs["transaction_id"] = kwargs["related_entity_id"]
            elif rel_type == "recovery_opportunity" and "opportunity_id" not in kwargs:
                kwargs["opportunity_id"] = kwargs["related_entity_id"]

        super().__init__(**kwargs)

    @property
    def timestamp(self) -> datetime:
        return self.created_at


    # Relationships
    merchant: Mapped["Merchant"] = relationship("Merchant", back_populates="audit_events")
    agent_decision: Mapped[Optional["AgentDecision"]] = relationship("AgentDecision", back_populates="audit_events")
    action: Mapped[Optional["RecoveryAction"]] = relationship("RecoveryAction", back_populates="audit_events")

    __table_args__ = (
        Index("ix_audit_events_merchant_event", "merchant_id", "event_type"),
        Index("ix_audit_events_merchant_date", "merchant_id", "created_at"),
        Index("ix_audit_events_opp_action", "opportunity_id", "action_id"),
    )
