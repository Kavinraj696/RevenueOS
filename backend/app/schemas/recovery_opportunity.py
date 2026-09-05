import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, ConfigDict, Field

class ActionCandidate(BaseModel):
    type: str
    title: str
    channel: str
    risk: str
    feasibility: float
    expected_recovery: Optional[float] = None
    policy_check: Optional[str] = None
    recommended_delay_seconds: Optional[int] = None
    expiry_minutes: Optional[int] = None

class RevenueBreakdown(BaseModel):
    gross_affected_revenue: Decimal
    revenue_at_risk: Decimal
    potentially_recoverable_revenue: Decimal
    expected_recovery: Decimal
    actual_recovery: Decimal

class RecoveryOpportunityResponse(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    payment_id: Optional[uuid.UUID] = None
    customer_id: Optional[uuid.UUID] = None
    revenue_leak_id: Optional[uuid.UUID] = None
    transaction_amount: Decimal = Field(..., description="Nominal transaction amount / cart value")
    failure_reason: Optional[str] = Field(None, description="Detailed gateway failure reason or dropped stage")
    recovery_probability: float = Field(..., description="Calibrated ML probability between 0 and 1")
    expected_recoverable_amount: Decimal = Field(..., description="transaction_value * recovery_probability")
    risk: str = Field(..., description="'low', 'medium', or 'high'")
    priority: str = Field(..., description="'CRITICAL', 'HIGH', 'MEDIUM', or 'LOW'")
    priority_score: Decimal = Field(..., description="Deterministic priority score between 0 and 100")
    priority_rank: Optional[int] = Field(None, description="Ordinal rank (1 = highest priority opportunity)")
    explanation: Optional[str] = Field(None, description="Human-readable explanation of why this opportunity has this priority")
    description: Optional[str] = Field(None, description="Description summary")
    suggested_action: Optional[str] = Field(None, description="Primary recommended action title")
    recommended_action_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    status: str
    currency: str = "INR"
    
    # Financial breakdown dimensions
    gross_affected_revenue: Decimal
    revenue_at_risk: Decimal
    potentially_recoverable_revenue: Decimal
    expected_recovery: Decimal
    actual_recovery: Decimal

    created_at: datetime
    updated_at: datetime

    # Stage 4 ML Traceability
    model_version: Optional[str] = Field(None, description="Active model version that generated prediction")
    feature_version: Optional[str] = Field(None, description="Feature pipeline contract version")
    prediction_time: Optional[datetime] = Field(None, description="Exact decision point-in-time timestamp")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class RecoveryOpportunitiesListResponse(BaseModel):
    total: int
    total_gross_affected: Decimal
    total_revenue_at_risk: Decimal
    total_potentially_recoverable: Decimal
    total_expected_recovery: Decimal
    total_actual_recovery: Decimal
    items: List[RecoveryOpportunityResponse]


# =============================================================================
# STAGE 8 EXPLAINABILITY & AUDIT TRACE SCHEMAS (Phases 7, 8, 9, 11, 12, 13)
# =============================================================================

class DiagnosticQuestionAnswer(BaseModel):
    question: str
    answer: str
    evidence: Optional[Dict[str, Any]] = None


class StructuredAiExplanation(BaseModel):
    problem: str
    evidence: List[str]
    diagnosis: str
    recommendation: str
    confidence: float
    confidence_percentage: str
    policy: str
    result: str
    verification: str
    recovery_amount: Decimal


class PolicyExplanationDetail(BaseModel):
    decision: str  # ALLOW, DENY, REQUIRE_APPROVAL
    rule_matched: str
    threshold: Optional[str] = None
    actual_value: Optional[str] = None
    retry_count: int = 0
    cooldown_seconds: int = 0
    risk_level: str = "low"
    explanation: str


class TimelineEventItem(BaseModel):
    timestamp: datetime
    title: str
    description: str
    stage: str
    entity_type: str
    entity_id: str
    badge_type: str = "info"


class CausalAuditTrace(BaseModel):
    transaction_id: Optional[str] = None
    leak_id: Optional[str] = None
    opportunity_id: str
    agent_decision_id: Optional[str] = None
    policy_decision_id: Optional[str] = None
    action_id: Optional[str] = None
    provider_operation_id: Optional[str] = None
    webhook_event_id: Optional[str] = None
    reconciliation_status: str
    verification_status: str
    audit_event_ids: List[str] = Field(default_factory=list)


class OpportunityExplainabilityResponse(BaseModel):
    opportunity_id: uuid.UUID
    merchant_id: uuid.UUID
    merchant_name: str
    currency: str = "INR"

    # 10 Diagnostic Answers (Phase 7)
    diagnostic_qa: List[DiagnosticQuestionAnswer]

    # Structured AI Explanation (Phase 8)
    ai_explanation: StructuredAiExplanation

    # Policy Explanation (Phase 9)
    policy_explanation: PolicyExplanationDetail

    # Phase 11 Fields
    transaction_id: Optional[uuid.UUID] = None
    amount: Decimal
    leak_type: str
    leak_reason: str
    ml_probability: float
    expected_recovery: Decimal
    ai_diagnosis: str
    ai_recommendation: str
    policy_decision: str
    approval_status: str
    action_status: str
    provider_status: str
    webhook_status: str
    verification_status: str
    actual_recovery: Decimal
    roi: str

    # Chronological Timeline (Phase 12)
    timeline: List[TimelineEventItem]

    # Full Audit Trace with IDs (Phase 13)
    audit_trace: CausalAuditTrace

