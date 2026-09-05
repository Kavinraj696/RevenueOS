import uuid
from decimal import Decimal
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field, model_validator


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="Unique audit event identifier")
    merchant_id: uuid.UUID = Field(..., description="Associated merchant ID")
    timestamp: datetime = Field(..., description="Timezone-aware UTC timestamp of event")
    event_type: str = Field(..., description="Standardized event type string")
    actor: str = Field(..., description="Actor entity: SYSTEM, AI_RECOVERY_AGENT, POLICY_ENGINE, etc.")
    agent_decision_id: Optional[uuid.UUID] = Field(None, description="Linked AI agent decision ID")
    transaction_id: Optional[uuid.UUID] = Field(None, description="Linked payment transaction ID")
    opportunity_id: Optional[uuid.UUID] = Field(None, description="Linked recovery opportunity ID")
    action_id: Optional[uuid.UUID] = Field(None, description="Linked recovery action ID")
    policy_decision_id: Optional[uuid.UUID] = Field(None, description="Linked policy decision ID")
    status: str = Field(..., description="Operational status: SUCCESS, FAILED, PENDING, BLOCKED, etc.")
    summary: str = Field(..., description="Human-readable summary description")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Redacted operational details")

    @model_validator(mode="before")
    @classmethod
    def handle_orm_audit_event(cls, data: Any) -> Any:
        if hasattr(data, "metadata_json"):
            return {
                "id": getattr(data, "id"),
                "merchant_id": getattr(data, "merchant_id"),
                "timestamp": getattr(data, "timestamp", getattr(data, "created_at", None)),
                "event_type": getattr(data, "event_type"),
                "actor": getattr(data, "actor"),
                "agent_decision_id": getattr(data, "agent_decision_id", None),
                "transaction_id": getattr(data, "transaction_id", None),
                "opportunity_id": getattr(data, "opportunity_id", None),
                "action_id": getattr(data, "action_id", None),
                "policy_decision_id": getattr(data, "policy_decision_id", None),
                "status": getattr(data, "status", "SUCCESS"),
                "summary": getattr(data, "summary", "") or getattr(data, "message", ""),
                "metadata": getattr(data, "metadata_json", {}) or {}
            }
        return data


class AuditEventListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[AuditEventResponse]


class ActionCausalityTimelineResponse(BaseModel):
    action_id: uuid.UUID
    opportunity_id: Optional[uuid.UUID] = None
    transaction_id: Optional[uuid.UUID] = None
    action_type: str
    status: str
    amount: Optional[Decimal] = None
    provider: str
    total_events: int
    timeline: List[AuditEventResponse]
