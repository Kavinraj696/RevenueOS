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
    affected_amount: Decimal
    revenue_at_risk: Decimal
    currency: str
    confidence: Decimal
    root_cause_candidates: List[str]
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
