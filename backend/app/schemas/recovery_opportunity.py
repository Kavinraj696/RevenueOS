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
    explanation: str = Field(..., description="Human-readable explanation of why this opportunity has this priority")
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

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

class RecoveryOpportunitiesListResponse(BaseModel):
    total: int
    total_gross_affected: Decimal
    total_revenue_at_risk: Decimal
    total_potentially_recoverable: Decimal
    total_expected_recovery: Decimal
    total_actual_recovery: Decimal
    items: List[RecoveryOpportunityResponse]
