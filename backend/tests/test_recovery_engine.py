import uuid
from decimal import Decimal
import pytest

from app.models import (
    Merchant,
    Payment,
    Customer,
    PaymentAttempt,
    PaymentStatus,
    RecoveryOpportunity,
)
from app.services.recovery_engine import RecoveryOpportunityEngine
from app.synthetic.generator import SyntheticDataGenerator

def test_recovery_opportunity_engine_evaluation(db_session):
    """
    Test RecoveryOpportunityEngine evaluation, ML probability synthesis,
    expected recovery calculation, priority scoring, and explanation generation.
    """
    gen = SyntheticDataGenerator(seed=42)
    gen.generate_all(db_session)

    engine = RecoveryOpportunityEngine(db_session)
    opps = engine.evaluate_and_sync()

    assert len(opps) >= 10, "Engine must evaluate and sync at least 10 realistic opportunities"

    for opp in opps:
        # 1. Required fields presence
        assert opp.id is not None
        assert opp.merchant_id is not None
        assert opp.gross_value_affected > Decimal("0.00")
        assert opp.transaction_amount == opp.gross_value_affected
        assert opp.expected_recovered_value >= Decimal("0.00")
        assert opp.expected_recoverable_amount == opp.expected_recovered_value
        assert 0.0 <= float(opp.recovery_probability) <= 1.0
        assert opp.priority in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
        assert 0.0 <= float(opp.priority_score) <= 100.0
        assert opp.risk in ("low", "medium", "high")
        assert opp.failure_reason is not None

        # 2. Formula verification: expected_recovery = transaction_value * recovery_probability
        calculated_expected = Decimal(str(round(float(opp.transaction_amount) * float(opp.recovery_probability), 2)))
        # Within rounding tolerance of 0.05
        assert abs(opp.expected_recoverable_amount - calculated_expected) <= Decimal("0.05")

        # 3. Explanation text verification
        assert opp.explanation is not None
        assert "transaction" in opp.explanation or "checkout" in opp.explanation
        assert "Recovery probability:" in opp.explanation
        assert "Expected recovery:" in opp.explanation
        assert f"Priority: {opp.priority}" in opp.explanation

        # 4. Recommended action candidates verification
        actions = opp.recommended_action_candidates
        assert isinstance(actions, list)
        assert len(actions) > 0
        for action in actions:
            assert "type" in action
            assert "title" in action
            assert "channel" in action
            assert "risk" in action
            assert "feasibility" in action
            assert "policy_check" in action

def test_policy_constraints_and_risk(db_session):
    """
    Test policy constraints: max attempts block, high-value concierge routing,
    and contact frequency checks.
    """
    merchant = Merchant(name="Policy Test Store", email="policy@test.com")
    db_session.add(merchant)
    db_session.flush()

    customer = Customer(merchant_id=merchant.id, external_ref="cust_vip", lifetime_value=Decimal("150000.00"))
    db_session.add(customer)
    db_session.flush()

    # Create a payment with 3 prior failed attempts (should hit retry limit policy)
    payment_exhausted = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        amount=Decimal("65000.00"),
        currency="INR",
        status=PaymentStatus.FAILED.value,
        payment_method="card",
        bank="HDFC",
        device_type="desktop",
        route="direct"
    )
    db_session.add(payment_exhausted)
    db_session.flush()

    for i in range(3):
        att = PaymentAttempt(
            payment_id=payment_exhausted.id,
            attempt_number=i + 1,
            status="failed",
            error_code="BAD_REQUEST_GATEWAY_TIMEOUT",
            failure_reason="Gateway timed out after 30s"
        )
        db_session.add(att)
    db_session.commit()

    engine = RecoveryOpportunityEngine(db_session)
    opps = engine.evaluate_and_sync(merchant_id=merchant.id)

    matched = next((o for o in opps if o.payment_id == payment_exhausted.id), None)
    assert matched is not None

    actions = matched.recommended_action_candidates
    action_types = [a["type"] for a in actions]

    # Smart retry should be blocked or omitted due to attempt count >= 3
    retry_action = next((a for a in actions if a["type"] == "smart_retry"), None)
    assert retry_action is None or "BLOCKED" in retry_action.get("policy_check", "")

    # High value concierge should be present because amount >= ₹50,000 and VIP
    assert "escalate" in action_types
    concierge_act = next(a for a in actions if a["type"] == "escalate")
    assert "VIP" in concierge_act["title"]
    assert "PASSED" in concierge_act["policy_check"]

def test_demo_mode_opportunity_count(db_session):
    """
    Verify at least 10 realistic opportunities are available in demo mode.
    """
    gen = SyntheticDataGenerator(seed=42)
    gen.generate_all(db_session)

    engine = RecoveryOpportunityEngine(db_session)
    opps = engine.evaluate_and_sync()

    assert len(opps) >= 10, f"Expected at least 10 demo opportunities, got {len(opps)}"
    
    # Check diversity of priorities
    priorities = {o.priority for o in opps}
    assert len(priorities) >= 2, "Opportunities should feature multiple priority tiers"

def test_api_recovery_opportunities_endpoints(client, db_session, seeded_db):
    """
    Test GET /api/recovery-opportunities and GET /api/recovery-opportunities/{id}.
    """
    # 1. GET /api/recovery-opportunities (List)
    res = client.get("/api/recovery-opportunities")
    assert res.status_code == 200
    data = res.json()

    assert "total" in data
    assert data["total"] >= 10
    assert "total_gross_affected" in data
    assert "total_expected_recovery" in data
    assert "items" in data
    assert len(data["items"]) > 0

    first_item = data["items"][0]
    assert "id" in first_item
    assert "transaction_amount" in first_item
    assert "failure_reason" in first_item
    assert "recovery_probability" in first_item
    assert "expected_recoverable_amount" in first_item
    assert "risk" in first_item
    assert "priority" in first_item
    assert "priority_score" in first_item
    assert "explanation" in first_item
    assert "recommended_action_candidates" in first_item

    # Verify explanation format
    explanation = first_item["explanation"]
    assert "Recovery probability:" in explanation
    assert "Expected recovery:" in explanation
    assert "Priority:" in explanation

    opp_id = first_item["id"]

    # 2. GET /api/recovery-opportunities/{id} (Single Detail)
    detail_res = client.get(f"/api/recovery-opportunities/{opp_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()

    assert detail["id"] == opp_id
    assert detail["transaction_amount"] == first_item["transaction_amount"]
    assert detail["expected_recoverable_amount"] == first_item["expected_recoverable_amount"]
    assert detail["explanation"] == first_item["explanation"]
    assert len(detail["recommended_action_candidates"]) > 0

    # 3. Filtering by priority
    filter_res = client.get("/api/recovery-opportunities?priority=CRITICAL")
    assert filter_res.status_code == 200
    crit_data = filter_res.json()
    for item in crit_data["items"]:
        assert item["priority"] == "CRITICAL"

    # 4. 404 for non-existent ID
    bad_res = client.get(f"/api/recovery-opportunities/{uuid.uuid4()}")
    assert bad_res.status_code == 404
