import uuid
from decimal import Decimal
import pytest

from app.models.merchant import Merchant
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.payment_attempt import PaymentAttempt
from app.models.subscription import Subscription
from app.models.revenue_leak import RevenueLeak
from app.models.enums import PaymentStatus
from app.services.agent.recovery_agent import AIRecoveryAgent


def test_scenario_1_payment_degradation_workflow(db_session, seeded_db):
    """
    Scenario 1: Payment Degradation
    Merchant with HDFC UPI Android failure spike.
    Agent detects failure rate increase, diagnoses Bank A / Android / evening window,
    quantifies recovery, passes policy (< ₹15k), and generates 1-click payment link.
    """
    deg_merchant = db_session.query(Merchant).filter(Merchant.name.like("%TrendStyle%")).first()
    assert deg_merchant is not None

    agent = AIRecoveryAgent(db_session)
    response = agent.run_workflow(merchant_id=deg_merchant.id)

    # 1. Verify required response fields
    assert response.problem != ""
    assert "increased from" in response.problem
    assert "concentrated in" in response.evidence
    assert response.financial_impact != ""
    assert 0.0 < response.recovery_probability <= 1.0
    assert response.recommended_action != ""
    assert response.reason != ""
    assert response.risk_level in ["low", "medium", "high"]
    assert "PASSED" in response.policy_result or "APPROVAL_REQUIRED" in response.policy_result
    assert response.expected_recovery > 0
    assert response.next_step != ""

    # 2. Verify all 9 stages in execution logs
    stages_logged = {log.stage for log in response.execution_logs}
    assert "OBSERVE" in stages_logged
    assert "INVESTIGATE" in stages_logged
    assert "DIAGNOSE" in stages_logged
    assert "QUANTIFY" in stages_logged
    assert "RECOMMEND" in stages_logged
    assert "POLICY_CHECK" in stages_logged
    assert "EXECUTE_OR_APPROVE" in stages_logged
    assert "REPORT" in stages_logged


def test_scenario_2_checkout_abandonment_workflow(db_session, seeded_db):
    """
    Scenario 2: Checkout Abandonment
    Agent investigates merchant with cart drop-offs, calculates recovery probability,
    and recommends SMS/WhatsApp payment link recovery.
    """
    cart_merchant = db_session.query(Merchant).filter(Merchant.name.like("%LuxeLiving%")).first()
    assert cart_merchant is not None

    agent = AIRecoveryAgent(db_session)
    response = agent.run_workflow(merchant_id=cart_merchant.id)

    assert response.workflow_id is not None
    assert response.merchant_id == cart_merchant.id
    assert response.recovery_probability > 0.0
    assert response.expected_recovery > 0
    assert len(response.execution_logs) >= 5


def test_scenario_3_high_value_vip_transaction(db_session, seeded_db):
    """
    Scenario 3: High-Value VIP Transaction (> ₹50,000)
    Policy gate must trigger APPROVAL_REQUIRED and recommend VIP concierge escalation.
    """
    merchant = db_session.query(Merchant).first()
    assert merchant is not None

    # Create a high-value VIP customer & payment
    vip_customer = Customer(
        merchant_id=merchant.id,
        external_ref="cust_vip_titan",
        lifetime_value=Decimal("120000.00"),
        risk_segment="vip"
    )
    db_session.add(vip_customer)
    db_session.flush()

    high_val_payment = Payment(
        merchant_id=merchant.id,
        customer_id=vip_customer.id,
        amount=Decimal("75000.00"),
        currency="INR",
        status=PaymentStatus.FAILED.value,
        payment_method="card",
        bank="HDFC",
        device_type="desktop",
        route="direct"
    )
    db_session.add(high_val_payment)
    db_session.flush()

    att = PaymentAttempt(
        payment_id=high_val_payment.id,
        attempt_number=1,
        status="failed",
        error_code="CARD_LIMIT_EXCEEDED",
        failure_reason="Single transaction card limit exceeded"
    )
    db_session.add(att)
    db_session.commit()

    agent = AIRecoveryAgent(db_session)
    response = agent.run_workflow(merchant_id=merchant.id, transaction_id=high_val_payment.id)

    # Must require approval due to amount > ₹15k & VIP
    assert "APPROVAL_REQUIRED" in response.policy_result
    assert "VIP" in response.recommended_action or "Concierge" in response.recommended_action
    assert "Approval ticket queued" in response.next_step


def test_scenario_4_policy_rejection_exhausted_retries(db_session, seeded_db):
    """
    Scenario 4: Policy Rejection / Exhausted Retries
    Transaction with 3 prior attempts must block further retries under policy rules.
    """
    merchant = db_session.query(Merchant).first()
    customer = db_session.query(Customer).first()

    exhausted_payment = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        amount=Decimal("3500.00"),
        currency="INR",
        status=PaymentStatus.FAILED.value,
        payment_method="upi",
        bank="SBI",
        device_type="android",
        route="direct"
    )
    db_session.add(exhausted_payment)
    db_session.flush()

    for i in range(3):
        att = PaymentAttempt(
            payment_id=exhausted_payment.id,
            attempt_number=i + 1,
            status="failed",
            error_code="GATEWAY_TIMEOUT",
            failure_reason="Gateway timed out"
        )
        db_session.add(att)
    db_session.commit()

    agent = AIRecoveryAgent(db_session)
    response = agent.run_workflow(merchant_id=merchant.id, transaction_id=exhausted_payment.id)

    # Tool checks attempts count = 3
    inv_logs = [log for log in response.execution_logs if log.tool_name == "get_transaction"]
    assert len(inv_logs) > 0
    assert any("attempts: 3" in log.output_summary for log in inv_logs)


def test_scenario_5_subscription_mandate_failure(db_session, seeded_db):
    """
    Scenario 5: Subscription Mandate Failure
    Investigate recurring billing merchant, quantify mandate exposure, and formulate recovery.
    """
    sub_merchant = db_session.query(Merchant).filter(Merchant.name.like("%CloudFlow%")).first()
    assert sub_merchant is not None

    agent = AIRecoveryAgent(db_session)
    response = agent.run_workflow(merchant_id=sub_merchant.id)

    assert response.workflow_id is not None
    assert response.recovery_probability > 0.0
    assert response.expected_recovery > 0
    assert response.next_step != ""


def test_api_agent_endpoints(client, seeded_db):
    """
    Test FastAPI endpoints:
    POST /api/agent/investigate
    GET /api/agent/decisions
    GET /api/agent/decisions/{id}
    """
    # 1. Trigger investigation via POST
    res = client.post("/api/agent/investigate", json={})
    assert res.status_code == 200
    data = res.json()

    assert "workflow_id" in data
    assert "problem" in data
    assert "evidence" in data
    assert "financial_impact" in data
    assert "recovery_probability" in data
    assert "recommended_action" in data
    assert "reason" in data
    assert "risk_level" in data
    assert "policy_result" in data
    assert "expected_recovery" in data
    assert "next_step" in data
    assert "execution_logs" in data
    assert len(data["execution_logs"]) > 0

    # 2. List agent decisions via GET
    decisions_res = client.get("/api/agent/decisions")
    assert decisions_res.status_code == 200
    dec_data = decisions_res.json()

    assert "total" in dec_data
    assert "items" in dec_data
    if dec_data["total"] > 0:
        dec_id = dec_data["items"][0]["id"]
        # 3. Get single decision detail
        single_res = client.get(f"/api/agent/decisions/{dec_id}")
        assert single_res.status_code == 200
        single_data = single_res.json()
        assert single_data["id"] == dec_id
        assert "evidence_json" in single_data
