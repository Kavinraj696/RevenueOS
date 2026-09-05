import uuid
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient

from app.main import app
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.recovery_opportunity import RecoveryOpportunity
from app.models.recovery_action import RecoveryAction
from app.models.agent_decision import AgentDecision
from app.models.policy_decision import PolicyDecision
from app.models.audit_event import AuditEvent
from app.models.enums import (
    ActionType,
    ActionStatus,
    OpportunityStatus,
    PaymentStatus,
)
from app.services.recovery_executor import (
    RecoveryExecutor,
    DuplicateActionError,
    RecoveryExecutionError,
)


@pytest.fixture
def setup_opportunity(db_session, seeded_db):
    """Fixture providing a fresh test merchant and opportunity."""
    merchant = db_session.query(Merchant).first()
    assert merchant is not None

    cust = db_session.query(Customer).filter(Customer.merchant_id == merchant.id).first()

    payment = Payment(
        id=uuid.uuid4(),
        merchant_id=merchant.id,
        customer_id=cust.id if cust else None,
        amount=Decimal("4999.00"),
        currency="INR",
        status=PaymentStatus.FAILED.value,
        payment_method="upi",
        bank="HDFC",
        device_type="android",
        route="direct"
    )
    db_session.add(payment)
    db_session.flush()

    opp = RecoveryOpportunity(
        id=uuid.uuid4(),
        merchant_id=merchant.id,
        customer_id=cust.id if cust else None,
        payment_id=payment.id,
        gross_value_affected=Decimal("4999.00"),
        potentially_recoverable_value=Decimal("4099.00"),
        recovery_probability=Decimal("0.8200"),
        expected_recovered_value=Decimal("4099.00"),
        priority="HIGH",
        priority_score=Decimal("84.00"),
        risk="low",
        explanation="Payment failed on UPI HDFC. High probability of recovery."
    )
    db_session.add(opp)
    db_session.commit()
    return opp


def test_11_required_fields_and_payment_link(setup_opportunity, db_session):
    """
    Test 1: CREATE_PAYMENT_LINK action execution and verify all 11 required fields:
    action_id, opportunity_id, agent_decision_id, policy_decision_id, provider,
    request, result, status, amount, created_at, completed_at.
    """
    opp = setup_opportunity
    executor = RecoveryExecutor(db_session)

    action = executor.execute_action(
        opportunity_id=opp.id,
        action_type=ActionType.CREATE_PAYMENT_LINK.value,
        amount=Decimal("4999.00")
    )

    # Verify 11 required fields
    assert action.action_id is not None
    assert action.id == action.action_id
    assert action.opportunity_id == opp.id
    assert action.provider in ["mock", "razorpay_test"]
    assert action.request is not None
    assert action.result is not None
    assert action.status == ActionStatus.SUCCESS.value
    assert action.amount == Decimal("4999.00")
    assert action.created_at is not None
    assert action.completed_at is not None

    # Check provider results
    assert "rzp.io" in action.result.get("short_url", "")
    assert action.result.get("status") == "created"


def test_all_5_recovery_actions(setup_opportunity, db_session):
    """
    Test 2: Test all 5 required recovery action types:
    1. Create payment link
    2. Send recovery notification
    3. Recommend alternative payment method
    4. Subscription recovery workflow
    5. Merchant escalation
    """
    opp = setup_opportunity
    executor = RecoveryExecutor(db_session)

    # 1. Payment link
    act1 = executor.execute_action(
        opportunity_id=opp.id,
        action_type=ActionType.CREATE_PAYMENT_LINK.value
    )
    assert act1.status == ActionStatus.SUCCESS.value
    assert "short_url" in act1.result

    # 2. Recovery notification
    act2 = executor.execute_action(
        opportunity_id=opp.id,
        action_type=ActionType.SEND_RECOVERY_NOTIFICATION.value
    )
    assert act2.status == ActionStatus.SUCCESS.value
    assert act2.result.get("status") == "delivered"

    # 3. Alternative payment method
    act3 = executor.execute_action(
        opportunity_id=opp.id,
        action_type=ActionType.RECOMMEND_ALTERNATIVE_PAYMENT.value
    )
    assert act3.status == ActionStatus.SUCCESS.value
    assert "recommended_method" in act3.result

    # 4. Subscription recovery workflow
    act4 = executor.execute_action(
        opportunity_id=opp.id,
        action_type=ActionType.SUBSCRIPTION_RECOVERY.value
    )
    assert act4.status == ActionStatus.SUCCESS.value
    assert act4.result.get("mandate_reauth_ready") is True

    # 5. Merchant escalation
    act5 = executor.execute_action(
        opportunity_id=opp.id,
        action_type=ActionType.MERCHANT_ESCALATION.value,
        bypass_policy=True
    )
    assert act5.status == ActionStatus.SUCCESS.value
    assert act5.result.get("priority") == "P1_VIP"


def test_prevent_duplicate_actions(setup_opportunity, db_session):
    """Test 3: Prevent duplicate active actions on the same opportunity."""
    opp = setup_opportunity
    executor = RecoveryExecutor(db_session)

    # First execution succeeds
    act1 = executor.execute_action(
        opportunity_id=opp.id,
        action_type=ActionType.CREATE_PAYMENT_LINK.value
    )
    assert act1.status == ActionStatus.SUCCESS.value

    # Attempting to execute identical active action type must raise DuplicateActionError
    with pytest.raises(DuplicateActionError) as exc_info:
        executor.execute_action(
            opportunity_id=opp.id,
            action_type=ActionType.CREATE_PAYMENT_LINK.value
        )
    assert "Duplicate action prevented" in str(exc_info.value)


def test_7_lifecycle_states(setup_opportunity, db_session):
    """
    Test 4: Verify all 7 states:
    PENDING, APPROVED, EXECUTING, SUCCESS, FAILED, BLOCKED, EXPIRED.
    """
    opp = setup_opportunity
    executor = RecoveryExecutor(db_session)

    # 1. SUCCESS
    act_success = executor.execute_action(opp.id, ActionType.CREATE_PAYMENT_LINK.value)
    assert act_success.status == ActionStatus.SUCCESS.value

    # 2. FAILED (via failure simulation)
    act_failed = executor.execute_action(
        opp.id,
        ActionType.SEND_RECOVERY_NOTIFICATION.value,
        simulate_failure=True,
        failure_type="RATE_LIMITED"
    )
    assert act_failed.status == ActionStatus.FAILED.value
    assert act_failed.result.get("error") == "RATE_LIMITED"

    # 3. PENDING (Action created needing approval, e.g. amount > max_auto_amount)
    act_pending = RecoveryAction(
        id=uuid.uuid4(),
        opportunity_id=opp.id,
        provider="mock",
        action_type=ActionType.MERCHANT_ESCALATION.value,
        status=ActionStatus.PENDING.value,
        amount=Decimal("75000.00")
    )
    db_session.add(act_pending)

    # 4. APPROVED
    act_approved = RecoveryAction(
        id=uuid.uuid4(),
        opportunity_id=opp.id,
        provider="mock",
        action_type="custom_approved",
        status=ActionStatus.APPROVED.value,
        amount=Decimal("10000.00")
    )
    db_session.add(act_approved)

    # 5. EXECUTING
    act_executing = RecoveryAction(
        id=uuid.uuid4(),
        opportunity_id=opp.id,
        provider="mock",
        action_type="custom_executing",
        status=ActionStatus.EXECUTING.value,
        amount=Decimal("10000.00")
    )
    db_session.add(act_executing)

    # 6. BLOCKED
    act_blocked = RecoveryAction(
        id=uuid.uuid4(),
        opportunity_id=opp.id,
        provider="mock",
        action_type="custom_blocked",
        status=ActionStatus.BLOCKED.value,
        amount=Decimal("100000.00"),
        reason="Blocked by risk policy"
    )
    db_session.add(act_blocked)

    # 7. EXPIRED
    act_expired = RecoveryAction(
        id=uuid.uuid4(),
        opportunity_id=opp.id,
        provider="mock",
        action_type="custom_expired",
        status=ActionStatus.EXPIRED.value,
        amount=Decimal("5000.00"),
        reason="Action TTL expired"
    )
    db_session.add(act_expired)
    db_session.commit()

    # Query and verify all 7 states
    for expected_status in [
        ActionStatus.PENDING.value,
        ActionStatus.APPROVED.value,
        ActionStatus.EXECUTING.value,
        ActionStatus.SUCCESS.value,
        ActionStatus.FAILED.value,
        ActionStatus.BLOCKED.value,
        ActionStatus.EXPIRED.value,
    ]:
        found = db_session.query(RecoveryAction).filter(
            RecoveryAction.opportunity_id == opp.id,
            RecoveryAction.status == expected_status
        ).first()
        assert found is not None, f"Expected to find action with status '{expected_status}'"


def test_merchant_approval_flow(setup_opportunity, db_session):
    """Test 5: Merchant approval transitions PENDING -> APPROVED -> SUCCESS."""
    opp = setup_opportunity
    executor = RecoveryExecutor(db_session)

    # Create a pending action
    pending_act = RecoveryAction(
        id=uuid.uuid4(),
        opportunity_id=opp.id,
        provider="mock",
        action_type=ActionType.CREATE_PAYMENT_LINK.value,
        status=ActionStatus.PENDING.value,
        amount=Decimal("60000.00")
    )
    db_session.add(pending_act)
    db_session.commit()

    # Approve action
    approved_act = executor.approve_action(
        action_id=pending_act.id,
        notes="High-value VIP order approved by CFO."
    )

    assert approved_act.status == ActionStatus.SUCCESS.value
    assert "approved by CFO" in approved_act.reason
    assert approved_act.completed_at is not None

    # Audit event logged
    audit = db_session.query(AuditEvent).filter(
        AuditEvent.related_entity_id == pending_act.id,
        AuditEvent.event_type == "recovery_action_approved"
    ).first()
    assert audit is not None


def test_demo_scenario_failure_and_graceful_fallback(setup_opportunity, db_session):
    """
    Test 6 (Critical Demo Requirement):
    AI recommends action
    -> action fails (simulated)
    -> system handles failure gracefully
    -> alternative action is recommended and succeeds!
    """
    opp = setup_opportunity
    executor = RecoveryExecutor(db_session)

    # 1. Primary action fails (e.g. Gateway Timeout on UPI Payment Link)
    act1 = executor.execute_action(
        opportunity_id=opp.id,
        action_type=ActionType.CREATE_PAYMENT_LINK.value,
        simulate_failure=True,
        failure_type="RAZORPAY_GATEWAY_TIMEOUT"
    )
    assert act1.status == ActionStatus.FAILED.value
    assert act1.result.get("error") == "RAZORPAY_GATEWAY_TIMEOUT"

    # 2. System handles failure gracefully and routes to alternative action
    failed_act, alt_act = executor.handle_action_failure_and_fallback(
        failed_action_id=act1.id,
        alternative_action_type=ActionType.RECOMMEND_ALTERNATIVE_PAYMENT.value
    )

    assert failed_act.id == act1.id
    assert alt_act.status == ActionStatus.SUCCESS.value
    assert alt_act.action_type == ActionType.RECOMMEND_ALTERNATIVE_PAYMENT.value
    assert alt_act.opportunity_id == opp.id

    # Verify opportunity state updated to RECOVERED
    refreshed_opp = db_session.query(RecoveryOpportunity).filter(RecoveryOpportunity.id == opp.id).first()
    assert refreshed_opp.status == OpportunityStatus.RECOVERED.value
    assert refreshed_opp.actual_recovered_value == alt_act.amount

    # Verify audit trail for fallback
    audit_fallback = db_session.query(AuditEvent).filter(
        AuditEvent.merchant_id == opp.merchant_id,
        AuditEvent.event_type == "recovery_fallback_succeeded"
    ).first()
    assert audit_fallback is not None


def test_full_pipeline_orchestrator(setup_opportunity, db_session):
    """
    Test 7: Complete end-to-end pipeline:
    Recovery Opportunity -> AI Agent -> Policy Engine -> Recovery Executor
    -> Provider -> Verification & Audit -> Dashboard Update.
    """
    opp = setup_opportunity
    executor = RecoveryExecutor(db_session)

    pipeline_res = executor.run_pipeline(opportunity_id=opp.id)

    assert pipeline_res["status"] in ["completed", "success"]
    assert pipeline_res["action"] is not None
    assert pipeline_res["action"].status == ActionStatus.SUCCESS.value
    assert len(pipeline_res["execution_trail"]) >= 8
    assert pipeline_res["audit_event_id"] is not None


def test_api_recovery_endpoints(setup_opportunity, db_session, client):
    """Test 8: REST API endpoints under /api/recovery/*."""
    opp = setup_opportunity

    # 1. POST /api/recovery/execute
    resp = client.post("/api/recovery/execute", json={
        "opportunity_id": str(opp.id),
        "action_type": "create_payment_link"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["opportunity_id"] == str(opp.id)
    assert data["action"]["status"] == "success"
    action_id = data["action"]["action_id"]

    # 2. GET /api/recovery/actions/{id}
    resp_get = client.get(f"/api/recovery/actions/{action_id}")
    assert resp_get.status_code == 200
    act_data = resp_get.json()
    assert act_data["action_id"] == action_id
    assert act_data["opportunity_id"] == str(opp.id)

    # 3. GET /api/recovery/actions
    resp_list = client.get(f"/api/recovery/actions?opportunity_id={opp.id}")
    assert resp_list.status_code == 200
    assert resp_list.json()["total"] >= 1

    # 4. POST /api/recovery/demo/failure-fallback
    resp_demo = client.post(f"/api/recovery/demo/failure-fallback?opportunity_id={opp.id}")
    assert resp_demo.status_code == 200
    demo_data = resp_demo.json()
    assert demo_data["stage_1_initial_action"]["status"] == "failed"
    assert demo_data["stage_4_alternative_action"]["status"] == "success"
    assert "caught the failure gracefully" in demo_data["stage_3_graceful_handling"]
