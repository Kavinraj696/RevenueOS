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


# =============================================================================
# STAGE 8 SCHEMAS: BUSINESS VALIDATION, ROI & RECOVERY FUNNEL
# =============================================================================

class BusinessMetricsResponse(BaseModel):
    merchant_id: uuid.UUID
    merchant_name: str
    currency: str = "INR"

    # Phase 2 metrics
    total_transactions: int = Field(..., description="Total transactions evaluated")
    total_revenue: Decimal = Field(..., description="Total gross processed revenue")
    total_revenue_at_risk: Decimal = Field(..., description="Total revenue at risk across leaks and failures")
    detected_revenue_leaks: int = Field(..., description="Count of detected revenue leaks")
    recovery_opportunities: int = Field(..., description="Count of recovery opportunities generated")
    potential_recoverable_revenue: Decimal = Field(..., description="Total potentially recoverable revenue")
    approved_recoveries: int = Field(..., description="Count of recovery actions approved (or auto-approved)")
    executed_recoveries: int = Field(..., description="Count of recovery actions dispatched to provider")
    verified_recoveries: int = Field(..., description="Count of recoveries confirmed by provider/webhook/reconciliation")
    actual_recovered_revenue: Decimal = Field(..., description="Sum of verified recovered revenue")
    recovery_rate: float = Field(..., description="Actual recovered revenue / Total revenue at risk (%)")
    detection_rate: float = Field(..., description="Detected leaks / Total failed transactions (%)")
    false_positive_rate: float = Field(..., description="Non-recoverable opportunities flagged (%)")
    average_recovery_value: Decimal = Field(..., description="Average value per verified recovery")
    average_time_to_recovery_seconds: float = Field(..., description="Mean elapsed time from detection to verification")
    policy_denial_rate: float = Field(..., description="Percentage of actions denied by policy engine")
    approval_rate: float = Field(..., description="Percentage of approval-required actions approved")
    provider_success_rate: float = Field(..., description="Successful provider operations / Total attempts (%)")

    # Phase 3 ROI metrics
    system_cost: Decimal = Field(..., description="Nominal system and messaging cost")
    net_recovered_revenue: Decimal = Field(..., description="Actual recovered revenue minus system cost")
    roi_multiplier: float = Field(..., description="Net recovered revenue / System cost multiplier")
    roi_percentage: float = Field(..., description="Net ROI percentage")


class FunnelStageItem(BaseModel):
    stage_number: int = Field(..., description="Funnel stage index (1-9)")
    stage_name: str = Field(..., description="Name of the funnel stage")
    count: int = Field(..., description="Number of items reaching this stage")
    amount: Decimal = Field(..., description="Monetary volume at this stage in INR")
    conversion_from_previous: float = Field(..., description="Conversion rate from previous stage (%)")
    conversion_from_start: float = Field(..., description="Overall conversion rate from stage 1 (%)")
    description: str = Field(..., description="Contextual description of this stage")


class RecoveryFunnelResponse(BaseModel):
    merchant_id: uuid.UUID
    merchant_name: str
    currency: str = "INR"
    stages: List[FunnelStageItem]
    overall_recovery_yield: float = Field(..., description="Actual Recovered / Potential Recoverable (%)")
    overall_conversion_rate: float = Field(..., description="Verified Recoveries / Total Transactions (%)")


class LeakCategoryBreakdownItem(BaseModel):
    category: str
    count: int
    revenue_at_risk: Decimal
    potential_recovery: Decimal
    actual_recovery: Decimal
    recovery_rate: float


class ModelPerformanceMetrics(BaseModel):
    precision: float
    recall: float
    f1_score: float
    roc_auc: float
    calibration_score: float
    false_positives: int
    false_negatives: int
    business_impact_summary: str


class AgentPerformanceMetrics(BaseModel):
    agent_runs: int
    successful_investigations: int
    failed_investigations: int
    average_tool_calls: float
    average_execution_time_seconds: float
    recommendation_acceptance_rate: float
    policy_denial_rate_after_recommendation: float
    agent_failure_rate: float


class PolicyPerformanceMetrics(BaseModel):
    total_evaluations: int
    allow_count: int
    allow_percentage: float
    deny_count: int
    deny_percentage: float
    require_approval_count: int
    require_approval_percentage: float
    amount_protected_by_policy: Decimal
    high_risk_actions_blocked: int
    approval_required_revenue: Decimal


class LatencyBenchmark(BaseModel):
    step_name: str
    avg_ms: float
    median_ms: float
    p95_ms: float


class BusinessImpactReportResponse(BaseModel):
    merchant_id: uuid.UUID
    merchant_name: str
    generated_at: datetime
    currency: str = "INR"
    metrics: BusinessMetricsResponse
    funnel: RecoveryFunnelResponse
    leak_categories: List[LeakCategoryBreakdownItem]
    top_opportunities: List[Dict[str, Any]]
    model_performance: ModelPerformanceMetrics
    agent_performance: AgentPerformanceMetrics
    policy_performance: PolicyPerformanceMetrics
    recovery_success_rate: float
    recovery_yield: float
    latencies: List[LatencyBenchmark]
    executive_verdict: str

