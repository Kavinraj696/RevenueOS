import uuid
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field
from app.models.enums import PolicyAction, RiskSegment


class PolicyLimitsConfig(BaseModel):
    max_auto_amount: Decimal = Field(default=Decimal("15000.00"), description="Max amount eligible for autonomous execution (INR)")
    medium_auto_amount: Decimal = Field(default=Decimal("50000.00"), description="Max medium amount eligible only for passive links (INR)")
    min_confidence: Decimal = Field(default=Decimal("0.6000"), description="Minimum recovery probability required for auto action")
    max_attempts: int = Field(default=3, description="Maximum allowed payment retry attempts before hard block")
    cooldown_seconds: int = Field(default=14400, description="Minimum cooldown between recovery actions (14,400s = 4h)")
    allowed_passive_actions: List[str] = Field(
        default=[
            PolicyAction.CREATE_PAYMENT_LINK.value,
            PolicyAction.RECOMMEND_ALTERNATIVE_PAYMENT.value,
            PolicyAction.SEND_RECOVERY_NOTIFICATION.value,
        ],
        description="Safe passive actions permitted up to medium amount threshold"
    )


class PolicyEvaluationRequest(BaseModel):
    action: str = Field(..., description="Action to evaluate (e.g. CREATE_PAYMENT_LINK, RETRY_ALLOWED_PAYMENT)")
    transaction_amount: Decimal = Field(default=Decimal("0.00"), description="Transaction or opportunity amount in INR")
    recovery_confidence: float = Field(default=0.80, ge=0.0, le=1.0, description="Recovery probability/confidence score")
    previous_attempts: int = Field(default=0, ge=0, description="Number of previous payment/retry attempts")
    is_vip: bool = Field(default=False, description="Whether the customer has VIP status")
    customer_risk_tier: str = Field(default="low", description="Customer risk tier: low, medium, high, blacklisted, dispute")
    cooldown_seconds: Optional[int] = Field(default=14400, description="Cooldown period window in seconds")
    last_action_timestamp: Optional[datetime] = Field(default=None, description="Timestamp of the most recent recovery action")
    last_action_type: Optional[str] = Field(default=None, description="Type of the most recent recovery action")
    opportunity_id: Optional[str] = Field(default=None, description="Related recovery opportunity ID if present")
    opportunity_status: Optional[str] = Field(default="open", description="Current opportunity status (open, recovered, dismissed, etc.)")
    is_expired: bool = Field(default=False, description="Whether the opportunity or session has expired")
    risk_level: Optional[str] = Field(default=None, description="Assessed operational/financial risk level")
    merchant_id: Optional[str] = Field(default=None, description="Merchant identifier")
    ai_recommendation: Optional[Dict[str, Any]] = Field(default=None, description="Optional upstream AI recommendation details")


class PipelineStageAIRecommendation(BaseModel):
    stage: str = "1_ai_recommendation"
    title: str = "AI Recommendation"
    recommended_action: str
    recovery_probability: float
    estimated_impact: Decimal
    reason: str
    risk_level: str


class PipelineStagePolicyDecision(BaseModel):
    stage: str = "2_policy_decision"
    title: str = "Policy Decision"
    policy_decision_id: uuid.UUID
    action: str
    allowed: bool
    risk_level: str
    reason: str


class PipelineStageApprovalGate(BaseModel):
    stage: str = "3_approval_gate"
    title: str = "Approval Required or Automatic"
    mode: str = Field(..., description="'automatic', 'approval_required', or 'blocked'")
    approval_required: bool
    explanation: str


class PipelineStageExecution(BaseModel):
    stage: str = "4_execution"
    title: str = "Execution"
    status: str = Field(..., description="'executed', 'pending_approval', 'blocked', or 'ready'")
    action_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class PolicyPipelineUI(BaseModel):
    stage_1_ai_recommendation: PipelineStageAIRecommendation
    stage_2_policy_decision: PipelineStagePolicyDecision
    stage_3_approval_gate: PipelineStageApprovalGate
    stage_4_execution: PipelineStageExecution


class PolicyDecisionResponse(BaseModel):
    policy_decision_id: uuid.UUID
    action: str
    allowed: bool
    reason: str
    risk_level: str
    approval_required: bool
    limits: Dict[str, Any]
    timestamp: datetime
    pipeline: PolicyPipelineUI
