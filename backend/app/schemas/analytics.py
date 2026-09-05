import uuid
from decimal import Decimal
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field


class RevenueTrendPoint(BaseModel):
    date: str = Field(..., description="Date label YYYY-MM-DD")
    processed: float = Field(..., description="Gross volume successfully processed in INR")
    failed: float = Field(..., description="Gross volume failed in INR")
    recovered: float = Field(..., description="Gross volume successfully recovered in INR")


class SuccessRatePoint(BaseModel):
    date: str = Field(..., description="Date label YYYY-MM-DD")
    success_rate: float = Field(..., description="Payment success rate percentage (0 - 100)")


class LeakageCategoryItem(BaseModel):
    category: str = Field(..., description="Leak category or root cause title")
    amount: float = Field(..., description="Total leaked volume in INR")
    percentage: float = Field(..., description="Share of total leakage percentage")


class RecoveryPerformanceItem(BaseModel):
    action_type: str = Field(..., description="Recovery action type name")
    attempted: int = Field(..., description="Total actions initiated")
    recovered: int = Field(..., description="Total actions that succeeded")
    success_rate: float = Field(..., description="Conversion rate percentage (0 - 100)")
    amount_recovered: float = Field(..., description="Total INR recovered")


class OverviewAnalyticsResponse(BaseModel):
    merchant_id: uuid.UUID
    merchant_name: str
    currency: str = "INR"

    # Top 5 Summary KPIs
    revenue_processed: Decimal = Field(..., description="Gross processed revenue")
    revenue_at_risk: Decimal = Field(..., description="Active revenue at risk from failures and churn")
    potentially_recoverable: Decimal = Field(..., description="Estimated recoverable revenue")
    recovered_revenue: Decimal = Field(..., description="Actual revenue recovered")
    recovery_rate: float = Field(..., description="Recovery conversion rate percentage")

    # 4 Chart Datasets
    revenue_trend: List[RevenueTrendPoint]
    success_rate_trend: List[SuccessRatePoint]
    leakage_breakdown: List[LeakageCategoryItem]
    recovery_performance: List[RecoveryPerformanceItem]


class RoiMetricGroup(BaseModel):
    revenue_lost: Decimal = Field(..., description="Total revenue lost to failures")
    revenue_recovered: Decimal = Field(..., description="Total revenue recovered")
    recovery_rate: float = Field(..., description="Recovery rate percentage")
    manual_interventions: int = Field(..., description="Number of manual operational tickets")
    automation_rate: float = Field(..., description="Percentage of recoveries automated")


class RoiAnalyticsResponse(BaseModel):
    merchant_id: uuid.UUID
    merchant_name: str
    currency: str = "INR"

    before: RoiMetricGroup
    after: RoiMetricGroup

    net_financial_gain: Decimal = Field(..., description="Net recovered revenue added to merchant bottom line")
    hours_saved: float = Field(..., description="Operational hours saved through automation")
    roi_multiplier: float = Field(..., description="Return on operational investment multiplier")


class EvidenceCard(BaseModel):
    id: str = Field(..., description="Card identifier")
    title: str = Field(..., description="Evidence title")
    metric: str = Field(..., description="Highlighted metric figure")
    subtitle: str = Field(..., description="Contextual subtitle")
    badge: str = Field(..., description="Status badge text")
    badge_type: str = Field("info", description="Badge style: danger, warning, success, info")
    details: Dict[str, Any] = Field(default_factory=dict, description="Granular evidence breakdown")


class AgentChatRequest(BaseModel):
    merchant_id: uuid.UUID
    message: str
    context: Optional[Dict[str, Any]] = None


class AgentChatResponse(BaseModel):
    merchant_id: uuid.UUID
    query: str
    response_text: str
    decision_explanation: str
    evidence_cards: List[EvidenceCard]
    recommended_actions: List[str]
    suggested_queries: List[str]
    timestamp: datetime
