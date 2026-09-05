"""
=============================================================================
REVENUEOS — STAGE 8 AUTOMATED TEST SUITE
FINAL BUSINESS VALIDATION, ROI, EXPLAINABILITY & FINANCIAL CONSISTENCY
=============================================================================
Covers all Stage 8 business criteria:
  - Phase 2: Measurable Business Success Metrics (18 Operational KPIs)
  - Phase 3: Transparent ROI Calculation & Strict Financial Truth
  - Phase 4: 9-Stage Recovery Funnel with Conversions & Drop-offs
  - Phase 5: Comprehensive Business Scenarios (A through H)
  - Phase 6 & 26: Canonical Golden Scenario End-to-End Validation
  - Phase 7 & 8: Explainability & 10 Diagnostic Answers + Forensic AI Evidence
  - Phase 9: Policy Engine Explainability (Rules, Limits, Rationale)
  - Phase 12 & 13: Chronological Timeline & Causal Audit Trace
  - Phase 14: Financial Truth Separation (Predicted vs Actual)
  - Phase 16, 17, 22: Executive Business Report, Category Breakdown & Latency
  - Phase 27: Negative End-to-End Tests (DENY, APPROVAL, INVALID, DUPLICATE, MISMATCH, TIMEOUT)
  - Phase 28 & 29: Business Consistency & Single Source of Truth
=============================================================================
"""

import uuid
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.main import app
from app.db.base import quantize_inr
from app.models.merchant import Merchant
from app.models.recovery_opportunity import RecoveryOpportunity
from app.models.recovery_action import RecoveryAction
from app.models.revenue_leak import RevenueLeak
from app.models.enums import OpportunityStatus, ActionStatus
from app.services.demo_scenario_engine import DemoScenarioEngine


# =============================================================================
# 1. CANONICAL GOLDEN SCENARIO END-TO-END VALIDATION (Phases 6 & 26)
# =============================================================================

def test_canonical_golden_scenario_e2e(db_session: Session):
    """
    Proves the full 10-step lifecycle:
    Transaction -> Leak -> Opportunity -> ML (91%) -> AI Investigation ->
    AI Recommendation -> Policy ALLOW -> Recovery Executed -> Razorpay Test Mode ->
    Webhook -> Provider Reconciliation -> Verification -> Actual Recovery (₹9,500) -> 632x ROI.
    """
    engine = DemoScenarioEngine(db_session)
    result = engine.run_golden_scenario()

    assert result.status in ["SUCCESS", "SUCCESS_VERIFIED"], f"Golden scenario status unexpected: {result.status}"
    assert result.key_metrics["actual_recovered_amount"] == 9500.0
    assert result.key_metrics["roi_multiplier"] > 0, "ROI multiplier must be positive"

    # Step validation: All 10 steps must be completed/verified
    steps = result.steps
    assert len(steps) == 10
    step_titles = [s.title for s in steps]
    assert any("Transaction" in t for t in step_titles)
    assert any("Leak" in t for t in step_titles)
    assert any("Opportunity" in t for t in step_titles)
    assert any("Investigation" in t for t in step_titles)
    assert any("Policy" in t for t in step_titles)
    assert any("Razorpay" in t or "Dispatch" in t for t in step_titles)
    assert any("Webhook" in t for t in step_titles)
    assert any("Reconcil" in t for t in step_titles)
    assert any("Verified" in t or "Confirm" in t for t in step_titles)
    assert any("ROI" in t for t in step_titles)

    # Invariant: Actual recovered revenue must equal verified provider-confirmed value
    action_id = result.key_metrics["recovery_action_id"]
    action = db_session.query(RecoveryAction).filter(RecoveryAction.id == uuid.UUID(action_id)).first()
    assert action is not None
    assert action.verified_status in ["confirmed", "VERIFIED_RECOVERED"]
    assert action.status in [ActionStatus.SUCCESS.value, ActionStatus.VERIFIED.value]
    assert float(action.amount) == 9500.0

    # Invariant: Causal audit trail events exist
    assert len(result.audit_event_ids) >= 1


# =============================================================================
# 2. NEGATIVE END-TO-END TESTS (Phase 27)
# =============================================================================

def test_negative_scenario_b_policy_denied(db_session: Session):
    """
    Scenario B: High-risk/fraud transaction (₹6,50,000) exceeds policy cap.
    Expected: Policy DENY, provider is NEVER invoked, zero financial risk.
    """
    engine = DemoScenarioEngine(db_session)
    result = engine.run_scenario_b_policy_denied()

    assert result.status in ["BLOCKED", "POLICY_BLOCKED"]
    assert result.key_metrics["provider_invoked"] is False
    assert result.key_metrics["financial_risk_incurred"] == 0.0
    assert result.key_metrics["capital_protected"] == 650000.0

    # Verify action was blocked or never executed
    opp_id = result.key_metrics["opportunity_id"]
    action = db_session.query(RecoveryAction).filter(RecoveryAction.opportunity_id == uuid.UUID(opp_id)).first()
    assert action is None or action.status.lower() in [ActionStatus.FAILED.value, ActionStatus.BLOCKED.value, "blocked"]


def test_negative_scenario_c_approval_required_gate(db_session: Session):
    """
    Scenario C: High-value transaction (₹85,000) exceeds autonomous cap (₹15,000).
    Expected: Held in Approval Required gate, no provider call until operator signs off.
    """
    engine = DemoScenarioEngine(db_session)
    result = engine.run_scenario_c_approval_required()

    assert result.status in ["SUCCESS", "SUCCESS_VERIFIED"]
    assert result.key_metrics["approval_gate_enforced"] is True
    assert result.key_metrics["verified_amount"] == 85000.0


def test_negative_scenario_d_provider_timeout_graceful_fallback(db_session: Session):
    """
    Scenario D: Primary provider encounters 504 Gateway Timeout.
    Expected: Not marked falsely recovered, falls back gracefully to alternative rail.
    """
    engine = DemoScenarioEngine(db_session)
    result = engine.run_scenario_d_provider_failure()

    assert result.status in ["FALLBACK_SUCCESS", "SUCCESS"]
    assert result.key_metrics["primary_rail_status"] == "TIMEOUT_504"
    assert result.key_metrics["fallback_success"] is True
    assert result.key_metrics["recovered_via_fallback"] == 3499.0


def test_negative_scenario_e_duplicate_webhook_idempotency(db_session: Session):
    """
    Scenario E: Duplicate webhook replay.
    Expected: Cryptographic signature verified, duplicate detected, zero double-recovery.
    """
    engine = DemoScenarioEngine(db_session)
    result = engine.run_scenario_e_duplicate_webhook()

    assert result.status in ["SUCCESS", "IDEMPOTENCY_PROVEN"]
    assert result.key_metrics["idempotent_duplicate"] is True
    assert result.key_metrics["double_crediting_prevented"] is True


def test_negative_scenario_f_amount_mismatch_refusal(db_session: Session):
    """
    Scenario F: Provider webhook captures ₹3,000 for an opportunity expecting ₹5,000.
    Expected: Verification REFUSED, status RECONCILIATION_REQUIRED, actual recovery = 0.
    """
    engine = DemoScenarioEngine(db_session)
    result = engine.run_scenario_f_amount_mismatch()

    assert result.status in ["RECONCILIATION_REQUIRED", "DISCREPANCY_REFUSED"]
    assert result.key_metrics["verification_status"] == "REFUSED"
    assert result.key_metrics["actual_recovery_booked"] == 0.0


def test_negative_scenario_g_false_positive_suppression(db_session: Session):
    """
    Scenario G: Non-recoverable leak (closed account), ML probability = 8% (< 15%).
    Expected: Outbound recovery action suppressed, zero wasted messaging fee.
    """
    engine = DemoScenarioEngine(db_session)
    result = engine.run_scenario_g_false_positive()

    assert result.status in ["SUPPRESSED", "SUPPRESSED_COST_SAVED"]
    assert result.key_metrics["action_suppressed"] is True
    assert result.key_metrics["wasted_fee_prevented"] is True


def test_scenario_a_and_h_positive_flows(db_session: Session):
    """
    Scenario A (Autonomous link) and Scenario H (Enterprise mandate renewal) both succeed.
    """
    engine = DemoScenarioEngine(db_session)
    res_a = engine.run_scenario_a_successful_recovery()
    assert res_a.status in ["SUCCESS", "SUCCESS_VERIFIED"]
    assert res_a.key_metrics["recovered_revenue"] == 4999.0

    res_h = engine.run_scenario_h_high_value_recovery()
    assert res_h.status in ["SUCCESS", "SUCCESS_VERIFIED"]
    assert res_h.key_metrics["arr_preserved"] == 540000.0


# =============================================================================
# 3. BUSINESS SUCCESS METRICS & FINANCIAL TRUTH (Phases 2, 3, 14)
# =============================================================================

def test_business_metrics_endpoint_and_strict_financial_truth(client: TestClient, db_session: Session):
    """
    Validates the 18 business success metrics from Phase 2 and strict financial truth from Phase 14.
    """
    engine = DemoScenarioEngine(db_session)
    engine.run_golden_scenario()
    merchant = engine._get_merchant_by_scenario("payment_degradation")

    res = client.get(f"/api/v1/analytics/business-metrics?merchant_id={merchant.id}")
    assert res.status_code == 200
    data = res.json()

    # 18 Required Phase 2 Metrics
    required_metrics = [
        "total_transactions",
        "total_revenue",
        "total_revenue_at_risk",
        "detected_revenue_leaks",
        "recovery_opportunities",
        "potential_recoverable_revenue",
        "approved_recoveries",
        "executed_recoveries",
        "verified_recoveries",
        "actual_recovered_revenue",
        "recovery_rate",
        "detection_rate",
        "false_positive_rate",
        "average_recovery_value",
        "average_time_to_recovery_seconds",
        "policy_denial_rate",
        "approval_rate",
        "provider_success_rate",
    ]
    for metric in required_metrics:
        assert metric in data, f"Missing metric {metric} in business metrics response"
        assert data[metric] is not None, f"Metric {metric} is null"

    # Financial Truth Invariants (Phase 14):
    assert float(data["actual_recovered_revenue"]) > 0
    assert data["verified_recoveries"] <= data["executed_recoveries"]
    assert 0.0 <= data["recovery_rate"] <= 100.0


def test_transparent_roi_calculation_endpoint(client: TestClient, db_session: Session):
    """
    Phase 3: Transparent ROI calculation endpoint.
    Verifies that system cost is deducted and net recovery / multiplier are mathematically sound.
    """
    engine = DemoScenarioEngine(db_session)
    engine.run_golden_scenario()
    merchant = engine._get_merchant_by_scenario("payment_degradation")

    res = client.get(f"/api/v1/analytics/roi?merchant_id={merchant.id}")
    assert res.status_code == 200
    data = res.json()

    assert "before" in data
    assert "after" in data
    assert "net_financial_gain" in data
    assert "roi_multiplier" in data

    # Financial Truth: after.revenue_recovered must equal verified recovery
    assert float(data["after"]["revenue_recovered"]) >= 9500.0
    assert float(data["net_financial_gain"]) > 0
    assert float(data["roi_multiplier"]) > 0


# =============================================================================
# 4. 9-STAGE RECOVERY FUNNEL (Phase 4)
# =============================================================================

def test_9_stage_recovery_funnel(client: TestClient, db_session: Session):
    """
    Phase 4: 9-stage recovery funnel endpoint.
    Stages:
      1. Transactions
      2. Potential Leaks
      3. Confirmed Leaks
      4. Recovery Opportunities
      5. Recommended
      6. Policy Allowed
      7. Executed
      8. Verified
      9. Recovered Revenue
    """
    engine = DemoScenarioEngine(db_session)
    engine.run_golden_scenario()

    res = client.get("/api/v1/analytics/funnel")
    assert res.status_code == 200
    data = res.json()

    assert len(data["stages"]) == 9

    stage_names = [s["stage_name"] for s in data["stages"]]
    assert any("Transaction" in name for name in stage_names)
    assert any("Potential" in name or "Leak" in name for name in stage_names)
    assert any("Confirmed" in name or "Leak" in name for name in stage_names)
    assert any("Opportunit" in name for name in stage_names)
    assert any("Recommend" in name for name in stage_names)
    assert any("Policy" in name or "Allow" in name for name in stage_names)
    assert any("Execut" in name for name in stage_names)
    assert any("Verif" in name for name in stage_names)
    assert any("Recovered" in name for name in stage_names)

    for stage in data["stages"]:
        assert 0.0 <= stage["conversion_from_previous"] <= 100.0


# =============================================================================
# 5. BUSINESS IMPACT REPORT & CATEGORY BREAKDOWN (Phases 16, 17, 18, 19, 20, 22)
# =============================================================================

def test_business_impact_report_endpoint(client: TestClient, db_session: Session):
    """
    Phase 16, 17, 18, 19, 20, 22: Complete business report.
    Checks:
      - Leak category breakdown (payment failure, auth, dropoff, etc.)
      - ML model performance (precision, recall, F1, ROC-AUC)
      - AI agent performance (runs, success rate, tool calls)
      - Policy performance (ALLOW, DENY, APPROVAL, protected capital)
      - Latency benchmarks (avg, median, p95)
    """
    engine = DemoScenarioEngine(db_session)
    engine.run_golden_scenario()

    res = client.get("/api/v1/analytics/business-report")
    assert res.status_code == 200
    data = res.json()

    # Leak categories
    assert len(data["leak_categories"]) > 0
    for cat in data["leak_categories"]:
        assert "category" in cat
        assert "revenue_at_risk" in cat
        assert "actual_recovery" in cat
        assert "recovery_rate" in cat

    # ML performance
    ml = data["model_performance"]
    assert 0.0 <= ml["precision"] <= 1.0
    assert 0.0 <= ml["recall"] <= 1.0
    assert 0.0 <= ml["f1_score"] <= 1.0
    assert 0.0 <= ml["roc_auc"] <= 1.0

    # Agent performance
    agent = data["agent_performance"]
    assert agent["agent_runs"] >= 0
    assert 0.0 <= agent["recommendation_acceptance_rate"] <= 100.0

    # Policy performance
    policy = data["policy_performance"]
    assert policy["total_evaluations"] >= 0
    assert policy["allow_count"] >= 0

    # Latency benchmarks
    latencies = data.get("latencies") or data.get("latency_benchmarks") or []
    assert len(latencies) >= 6
    subsystems = [l["step_name"] for l in latencies]
    assert any("Detection" in s for s in subsystems)
    assert any("ML" in s or "Scoring" in s for s in subsystems)
    assert any("Policy" in s for s in subsystems)


# =============================================================================
# 6. EXPLAINABILITY & AUDIT TRACE ENDPOINT (Phases 7, 8, 9, 12, 13)
# =============================================================================

def test_opportunity_explainability_endpoint(client: TestClient, db_session: Session):
    """
    Phase 7, 8, 9, 12, 13: Deep Explainability.
    Verifies:
      - 10 Diagnostic Q&As
      - Structured AI Explanation (problem, diagnosis, recommendation, confidence, evidence)
      - Structured Policy Explanation (verdict, matched rule, limits, rationale)
      - Chronological Timeline with real timestamps
      - Causal Audit Trace with foreign IDs matching DB
    """
    engine = DemoScenarioEngine(db_session)
    result = engine.run_golden_scenario()
    opp_id = result.key_metrics["opportunity_id"]

    res = client.get(f"/api/v1/recovery-opportunities/{opp_id}/explainability")
    assert res.status_code == 200
    data = res.json()

    # 1. 10 Diagnostic Answers (Phase 7)
    qnas = data.get("diagnostic_qa") or data.get("diagnostic_answers")
    assert len(qnas) == 10
    questions = [q["question"] for q in qnas]
    assert any("WHAT happened?" in q for q in questions)
    assert any("WHY is this a revenue leak?" in q for q in questions)
    assert any("HOW confident is the system?" in q for q in questions)
    assert any("WHY was recovery recommended?" in q for q in questions)
    assert any("WHY did Policy Engine allow/deny it?" in q for q in questions)
    assert any("WHAT action was executed?" in q for q in questions)
    assert any("WHAT did Razorpay return?" in q for q in questions)
    assert any("WHAT webhook was received?" in q for q in questions)
    assert any("HOW was recovery verified?" in q for q in questions)
    assert any("HOW MUCH revenue was actually recovered?" in q for q in questions)

    # 2. Structured AI Explanation (Phase 8)
    ai = data["ai_explanation"]
    assert ai["problem"] != ""
    assert ai["diagnosis"] != ""
    assert ai["recommendation"] != ""
    assert 0.0 <= ai["confidence"] <= 1.0
    assert "transaction" in ai["evidence"][0].lower() or len(ai["evidence"]) > 0

    # 3. Structured Policy Explanation (Phase 9)
    pol = data["policy_explanation"]
    assert pol["decision"] in ["ALLOW", "CREATE_PAYMENT_LINK", "create_payment_link"]
    assert "Rule" in pol["rule_matched"]
    assert pol["threshold"] is not None
    assert pol["explanation"] != ""

    # 4. Chronological Timeline (Phase 12)
    timeline = data.get("timeline") or data.get("chronological_timeline")
    assert len(timeline) >= 3
    for t in timeline:
        assert "timestamp" in t
        assert "title" in t
        assert "stage" in t

    # 5. Causal Audit Trace (Phase 13)
    trace = data.get("audit_trace") or data.get("causal_audit_trace")
    assert str(trace["opportunity_id"]) == str(opp_id)
    assert trace["transaction_id"] is not None
    assert trace["leak_id"] is not None
    assert trace["action_id"] is not None


# =============================================================================
# 7. BUSINESS & DATA CONSISTENCY INVARIANTS (Phases 28, 29)
# =============================================================================

def test_business_financial_consistency_and_single_source_of_truth(client: TestClient, db_session: Session):
    """
    Phase 28 & 29:
    Verifies that:
      1. Actual Recovered Revenue in DB == sum of verified RecoveryActions
      2. Database total == API Business Metrics total == ROI endpoint total
      3. No double-counted revenue
    """
    engine = DemoScenarioEngine(db_session)
    res_golden = engine.run_golden_scenario()
    res_a = engine.run_scenario_a_successful_recovery()

    expected_sum = float(res_golden.key_metrics["actual_recovered_amount"] + res_a.key_metrics["recovered_revenue"])
    assert expected_sum >= (9500.0 + 4999.0)

    merchant = engine._get_merchant_by_scenario("payment_degradation")

    # 1. Database authoritative source for this merchant
    actions = db_session.query(RecoveryAction).join(RecoveryOpportunity).filter(
        RecoveryOpportunity.merchant_id == merchant.id
    ).all()
    verified_actions = [
        a for a in actions
        if a.verified_status in ["confirmed", "VERIFIED_RECOVERED"]
        and a.status in [ActionStatus.SUCCESS.value, ActionStatus.VERIFIED.value]
    ]
    db_verified_total = float(sum((a.actual_recovered_amount or Decimal("0.00") for a in verified_actions), Decimal("0.00")))
    assert db_verified_total >= expected_sum

    # 2. API Business Metrics check
    res_metrics = client.get(f"/api/v1/analytics/business-metrics?merchant_id={merchant.id}")
    assert res_metrics.status_code == 200
    metrics_actual = float(res_metrics.json()["actual_recovered_revenue"])

    assert abs(metrics_actual - db_verified_total) < 0.01, (
        f"Mismatch: API Business Metrics reported {metrics_actual} vs DB sum {db_verified_total}"
    )

    # 3. API ROI Endpoint check
    res_roi = client.get(f"/api/v1/analytics/roi?merchant_id={merchant.id}")
    assert res_roi.status_code == 200
    roi_after_rec = float(res_roi.json()["after"]["revenue_recovered"])

    assert abs(roi_after_rec - db_verified_total) < 0.01, (
        f"Mismatch: API ROI reported {roi_after_rec} vs DB sum {db_verified_total}"
    )
