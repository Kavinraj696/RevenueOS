"""
Automated tests for the RevenueOS Demo Scenario Engine.
Verifies all 5 scenarios:
1. Payment Degradation
2. Checkout Abandonment
3. Subscription Failures
4. Recovery Failure & Fallback
5. Unsafe Action & Deterministic Policy Block
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_demo_data():
    """Ensure seeded demo data exists with seed=42 before running scenario tests."""
    res = client.post("/api/v1/demo/reset", json={"seed": 42})
    assert res.status_code == 200


def test_demo_scenarios_catalog_api():
    """Verify GET /api/v1/demo/scenarios/catalog returns all 5 demonstration scenarios."""
    res = client.get("/api/v1/demo/scenarios/catalog")
    assert res.status_code == 200
    data = res.json()

    assert "scenarios" in data
    assert len(data["scenarios"]) == 5

    scenario_ids = [s["id"] for s in data["scenarios"]]
    assert "payment_degradation" in scenario_ids
    assert "checkout_abandonment" in scenario_ids
    assert "subscription_failures" in scenario_ids
    assert "recovery_failure" in scenario_ids
    assert "unsafe_action" in scenario_ids


def test_scenario_1_payment_degradation():
    """Verify Scenario 1: Detect anomaly -> method/bank/time -> RAR -> recoverable -> recommend -> execute -> recovered."""
    res = client.post("/api/v1/demo/scenarios/run/payment_degradation")
    if res.status_code != 200:
        print("ERROR RESPONSE:", res.text)
    assert res.status_code == 200
    data = res.json()

    assert data["scenario_id"] == "payment_degradation"
    assert data["status"] == "SUCCESS"
    assert len(data["steps"]) >= 6

    # Step 1: Detect anomaly
    step1 = data["steps"][0]
    assert "Detect Anomaly" in step1["title"]
    assert step1["status"] == "completed"

    # Step 2: Identify Method/Bank/Time
    step2 = data["steps"][1]
    assert "Method / Bank / Time" in step2["title"]
    assert "HDFC" in step2["evidence"]["bank"]
    assert "upi" in step2["evidence"]["method"].lower()
    assert "18:00 - 22:00" in step2["evidence"]["peak_hours"]

    # Step 3: Calculate Revenue at Risk
    step3 = data["steps"][2]
    assert "Revenue at Risk" in step3["title"]
    assert step3["evidence"]["revenue_at_risk"] > 0

    # Step 6 & 7: Execute & Show Recovered Revenue
    step7 = data["steps"][-1]
    assert "Recovered Revenue" in step7["title"]
    assert step7["status"] == "completed"
    assert step7["evidence"]["gross_recovered"] > 0
    assert step7["evidence"]["opportunity_status"] == "RECOVERED"


def test_scenario_2_checkout_abandonment():
    """Verify Scenario 2: Detect abandonment -> identify high-value -> estimate prob -> prioritize -> link -> simulate payment -> update ROI."""
    res = client.post("/api/v1/demo/scenarios/run/checkout_abandonment")
    if res.status_code != 200:
        print("SCENARIO 2 ERROR:", res.text)
    assert res.status_code == 200
    data = res.json()

    assert data["scenario_id"] == "checkout_abandonment"
    assert data["status"] == "SUCCESS"
    assert len(data["steps"]) >= 6

    # Step 1: Detect abandonment
    assert "Abandonment" in data["steps"][0]["title"]
    assert data["steps"][0]["evidence"]["total_abandoned_sessions"] > 0

    # Step 2: Identify High-Value
    assert data["steps"][1]["evidence"]["cart_value"] >= 15000.0

    # Step 3: Recovery Probability
    assert 0.0 < data["steps"][2]["evidence"]["recovery_probability"] <= 1.0

    # Step 5: Create Link
    assert "Link" in data["steps"][4]["title"]

    # Step 6: Simulate Payment Capture
    assert data["steps"][5]["evidence"]["webhook_event"] == "payment.captured"

    # Step 7: Update ROI
    step7 = data["steps"][6]
    assert "ROI" in step7["title"]
    assert step7["evidence"]["net_financial_gain"] >= 0


def test_scenario_3_subscription_failures():
    """Verify Scenario 3: Detect failure spike -> identify affected subscriptions -> estimate recoverability -> trigger safe workflow -> show result."""
    res = client.post("/api/v1/demo/scenarios/run/subscription_failures")
    if res.status_code != 200:
        print("SCENARIO 3 ERROR:", res.text)
    assert res.status_code == 200
    data = res.json()

    assert data["scenario_id"] == "subscription_failures"
    assert data["status"] == "SUCCESS"
    assert len(data["steps"]) >= 5

    # Step 1: Detect Failure Spike
    assert "Mandate Failure Spike" in data["steps"][0]["title"]
    assert data["steps"][0]["evidence"]["mandate_failures"] > 0

    # Step 2: Identify Subscriptions & MRR
    assert data["steps"][1]["evidence"]["mrr_at_risk"] > 0

    # Step 4: Safe Workflow
    assert data["steps"][3]["status"] == "completed"

    # Step 5: Show Result & Preserved MRR
    assert data["steps"][4]["evidence"]["subscription_status"] == "ACTIVE"
    assert data["steps"][4]["evidence"]["mrr_preserved"] > 0


def test_scenario_4_recovery_failure():
    """Verify Scenario 4: Primary action fails -> explain failure -> choose alternative bounded action -> execute -> succeed."""
    res = client.post("/api/v1/demo/scenarios/run/recovery_failure")
    if res.status_code != 200:
        print("SCENARIO 4 ERROR:", res.text)
    assert res.status_code == 200
    data = res.json()

    assert data["scenario_id"] == "recovery_failure"
    assert data["status"] == "FALLBACK_SUCCESS"

    # Step 1: AI recommends primary action
    assert "Primary Action" in data["steps"][0]["title"]

    # Step 2: Primary action encounters gateway failure
    step2 = data["steps"][1]
    assert step2["status"] == "failed"
    assert "GATEWAY_SERVICE_UNAVAILABLE" in step2["evidence"]["error"]

    # Step 3: Explain Failure & Forensic Diagnosis
    step3 = data["steps"][2]
    assert "Forensic" in step3["title"]
    assert step3["evidence"]["is_fatal"] is False

    # Step 4: Policy Engine evaluates alternative action
    step4 = data["steps"][3]
    assert step4["evidence"]["allowed"] is True
    assert step4["evidence"]["alternative_action"].lower() == "recommend_alternative_payment"

    # Step 5: Execute Alternative Action & Succeed
    step5 = data["steps"][4]
    assert step5["status"] == "fallback_success"
    assert step5["evidence"]["status"] == "SUCCESS"
    assert step5["evidence"]["recovered_amount"] > 0


def test_scenario_5_unsafe_action_policy_block():
    """Verify Scenario 5: High-value low-confidence opportunity -> AI recommends action -> policy blocks automatic execution -> merchant approval required."""
    res = client.post("/api/v1/demo/scenarios/run/unsafe_action")
    if res.status_code != 200:
        print("SCENARIO 5 ERROR:", res.text)
    assert res.status_code == 200
    data = res.json()

    assert data["scenario_id"] == "unsafe_action"
    assert data["status"] == "SAFETY_BLOCKED"
    assert data["safety_system_proven"] is True

    # Step 1: High-value low-confidence candidate
    assert data["steps"][0]["evidence"]["transaction_value"] == 125000.0
    assert data["steps"][0]["evidence"]["recovery_probability"] == 0.35

    # Step 2: AI Recommends Action
    assert data["steps"][1]["status"] == "completed"

    # Step 3: Deterministic Policy Engine intercepts
    step3 = data["steps"][2]
    assert step3["status"] == "safety_enforced"
    assert step3["evidence"]["policy_allowed"] is False
    assert step3["evidence"]["approval_required"] is True

    # Step 4: Autonomous Execution strictly BLOCKED
    step4 = data["steps"][3]
    assert step4["status"] == "blocked"
    assert step4["evidence"]["execution_status"] == "BLOCKED"
    assert step4["evidence"]["automated_debit_prevented"] is True

    # Step 5: Merchant approval required (Safety verified)
    step5 = data["steps"][4]
    assert step5["status"] == "pending_approval"
    assert step5["evidence"]["safety_system_verified"] is True
