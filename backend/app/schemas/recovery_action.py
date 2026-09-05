import uuid
from decimal import Decimal
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field


class RecoveryActionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action_id: uuid.UUID = Field(..., description="Unique action identifier")
    opportunity_id: uuid.UUID = Field(..., description="Linked recovery opportunity")
    agent_decision_id: Optional[uuid.UUID] = Field(None, description="Linked AI agent decision")
    policy_decision_id: Optional[uuid.UUID] = Field(None, description="Linked policy evaluation decision")
    provider: str = Field(..., description="Active payment provider: 'mock' or 'razorpay_test'")
    action_type: str = Field(..., description="Action type")
    status: str = Field(..., description="Status: PENDING, APPROVED, EXECUTING, SUCCESS, FAILED, BLOCKED, EXPIRED")
    amount: Optional[Decimal] = Field(None, description="Recoverable monetary amount")
    request: Optional[Dict[str, Any]] = Field(None, description="Structured request payload")
    result: Optional[Dict[str, Any]] = Field(None, description="Structured execution result")
    reason: Optional[str] = Field(None, description="Justification reason")
    created_at: datetime = Field(..., description="Creation timestamp")
    completed_at: Optional[datetime] = Field(None, description="Completion timestamp")


class RecoveryActionListResponse(BaseModel):
    total: int
    items: List[RecoveryActionResponse]


class RecoveryPipelineExecutionRequest(BaseModel):
    opportunity_id: Optional[uuid.UUID] = None
    transaction_id: Optional[uuid.UUID] = None
    merchant_id: Optional[uuid.UUID] = None
    action_type: Optional[str] = None
    simulate_failure: bool = False
    failure_type: Optional[str] = "GATEWAY_TIMEOUT"
    auto_execute: bool = True
    metadata: Optional[Dict[str, Any]] = None


class RecoveryPipelineExecutionResponse(BaseModel):
    pipeline_id: uuid.UUID
    opportunity_id: uuid.UUID
    status: str
    action: RecoveryActionResponse
    policy_verdict: str
    approval_required: bool
    audit_event_id: Optional[uuid.UUID] = None
    fallback_action: Optional[RecoveryActionResponse] = None
    execution_trail: List[str] = Field(default_factory=list)


class RecoveryActionApprovalRequest(BaseModel):
    approved: bool = True
    notes: Optional[str] = "Approved by merchant operations"


class RecoveryFallbackDemoResponse(BaseModel):
    demo_name: str = "Resilient Recovery Fallback & Alternative Route Execution"
    opportunity_id: uuid.UUID
    stage_1_initial_action: RecoveryActionResponse
    stage_2_failure_simulation: Dict[str, Any]
    stage_3_graceful_handling: str
    stage_4_alternative_action: RecoveryActionResponse
    overall_recovery_status: str
    audit_events_recorded: int
