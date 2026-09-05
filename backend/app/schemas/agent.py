import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, ConfigDict, Field
from app.services.agent.state import AgentLogEntry


class AgentInvestigationRequest(BaseModel):
    merchant_id: Optional[uuid.UUID] = Field(None, description="Merchant to investigate")
    leak_id: Optional[uuid.UUID] = Field(None, description="Target revenue leak to investigate")
    opportunity_id: Optional[uuid.UUID] = Field(None, description="Target opportunity to investigate")
    transaction_id: Optional[uuid.UUID] = Field(None, description="Specific failed transaction to investigate")
    auto_execute: bool = Field(True, description="Whether to auto-execute approved low-risk actions")


class AgentInvestigationResponse(BaseModel):
    workflow_id: uuid.UUID
    merchant_id: Optional[uuid.UUID] = None
    problem: str = Field(..., description="Concise statement of the identified revenue leak or failure")
    evidence: str = Field(..., description="Evidence-based telemetry breakdown (rates, banks, devices, window)")
    financial_impact: str = Field(..., description="Affected revenue and exposure details")
    recovery_probability: float = Field(..., description="Calibrated ML probability between 0 and 1")
    recommended_action: str = Field(..., description="Recommended recovery intervention")
    reason: str = Field(..., description="Justification grounded in probability and operational risk")
    risk_level: str = Field(..., description="'low', 'medium', or 'high'")
    policy_result: str = Field(..., description="Policy check outcome (PASSED / BLOCKED / APPROVAL_REQUIRED)")
    expected_recovery: Decimal = Field(..., description="Actuarial expected recovery in INR")
    next_step: str = Field(..., description="Immediate execution outcome or pending approval task")
    execution_logs: List[AgentLogEntry] = Field(default_factory=list, description="Audit trace of tools called")
    policy_decision: Optional[Dict[str, Any]] = Field(default=None, description="Detailed policy decision payload")
    pipeline: Optional[Dict[str, Any]] = Field(default=None, description="4-step UI pipeline: AI Recommendation -> Policy Decision -> Approval Gate -> Execution")
    causal_trace_id: Optional[str] = Field(default=None, description="Unique end-to-end causal trace identifier")
    agent_run_id: Optional[uuid.UUID] = Field(default=None, description="Unique agent run identifier")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = ConfigDict(from_attributes=True)


class AgentDecisionResponse(BaseModel):
    id: uuid.UUID
    opportunity_id: uuid.UUID
    problem: str
    evidence_json: Dict[str, Any]
    estimated_impact: Decimal
    recovery_probability: float
    recommended_action: str
    reason: str
    risk_level: str
    expected_recovery: Decimal
    actual_recovery: Optional[Decimal] = None
    currency: str = "INR"
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentDecisionsListResponse(BaseModel):
    total: int
    items: List[AgentDecisionResponse]


class AgentRunResponse(BaseModel):
    id: uuid.UUID
    agent_run_id: uuid.UUID
    merchant_id: uuid.UUID
    trigger: str
    trigger_id: Optional[str] = None
    current_state: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    model_version: str
    causal_trace_id: str
    problem: Optional[str] = None
    diagnosis: Optional[str] = None
    recommended_action: Optional[str] = None
    policy_verdict: Optional[str] = None
    decision_summary: Dict[str, Any] = Field(default_factory=dict)
    execution_logs_json: List[Dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AgentRunsListResponse(BaseModel):
    total: int
    items: List[AgentRunResponse]
