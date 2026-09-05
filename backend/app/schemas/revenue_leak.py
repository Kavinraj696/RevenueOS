import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, ConfigDict, Field

class RevenueLeakEvidence(BaseModel):
    baseline_failure_rate: Optional[Decimal] = None
    current_failure_rate: Optional[Decimal] = None
    increase_percentage: Optional[Decimal] = None
    affected_payment_method: Optional[str] = None
    affected_bank: Optional[str] = None
    affected_device: Optional[str] = None
    peak_window: Optional[str] = None
    potential_revenue: Optional[Decimal] = None
    summary_text: Optional[str] = None
    breakdown: Optional[Dict[str, Any]] = None

class RevenueLeakResponse(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    type: str
    leak_type: str
    pattern_description: str
    severity: str
    severity_score: Decimal
    affected_transactions: int
    gross_value_affected: Optional[Decimal] = Decimal("0.00")
    affected_amount: Decimal
    revenue_at_risk: Decimal
    currency: str
    confidence: Decimal
    root_cause_candidates: List[Any] = Field(default_factory=list)
    evidence: Dict[str, Any]
    status: str
    created_at: datetime
    detection_window_start: datetime
    detection_window_end: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

class PaginatedRevenueLeaksResponse(BaseModel):
    total: int
    items: List[RevenueLeakResponse]
    limit: int
    offset: int

class LeakDetectionRequest(BaseModel):
    merchant_id: Optional[uuid.UUID] = Field(None, description="Target merchant ID. If omitted, runs for all merchants.")
    analysis_window_start: Optional[datetime] = Field(None, description="Start timestamp of incident/analysis window.")
    analysis_window_end: Optional[datetime] = Field(None, description="End timestamp of incident/analysis window.")
    baseline_window_start: Optional[datetime] = Field(None, description="Start timestamp of historical baseline window.")
    baseline_window_end: Optional[datetime] = Field(None, description="End timestamp of historical baseline window.")
    window_days: Optional[int] = Field(7, ge=1, le=90, description="Default window duration in days if explicit timestamps omitted.")

class LeakDetectionSummaryResponse(BaseModel):
    merchant_id: Optional[uuid.UUID] = None
    detected_leaks_count: int
    total_gross_affected_revenue: Decimal
    total_revenue_at_risk: Decimal
    analysis_window_start: datetime
    analysis_window_end: datetime
    leaks: List[RevenueLeakResponse]

