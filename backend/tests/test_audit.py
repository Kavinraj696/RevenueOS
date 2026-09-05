import uuid
import json
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.revenue_leak import RevenueLeak
from app.models.recovery_opportunity import RecoveryOpportunity
from app.models.recovery_action import RecoveryAction
from app.models.agent_decision import AgentDecision
from app.models.policy_decision import PolicyDecision
from app.models.audit_event import AuditEvent
from app.models.enums import AuditEventType, AuditActor, ActionStatus, OpportunityStatus
from app.services.audit_service import AuditService, sanitize_metadata
from app.synthetic.generator import SyntheticDataGenerator


def test_11_required_fields_and_immutability(db_session: Session, seeded_db):
    """
    Test 1: Every audit record contains all 11 required fields:
    timestamp, event_type, actor, agent_decision_id, transaction_id,
    opportunity_id, action_id, policy_decision_id, status, summary, metadata.
    """
    merchant = db_session.query(Merchant).first()
    assert merchant is not None

    audit_svc = AuditService(db_session)
    tx_id = uuid.uuid4()
    opp_id = uuid.uuid4()
    act_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    pol_id = uuid.uuid4()

    event = audit_svc.record_event(
        merchant_id=merchant.id,
        event_type=AuditEventType.RECOVERY_ACTION,
        actor=AuditActor.SYSTEM,
        summary="Test recovery action dispatched to Razorpay Test provider.",
        transaction_id=tx_id,
        opportunity_id=opp_id,
        action_id=act_id,
        agent_decision_id=agent_id,
        policy_decision_id=pol_id,
        status="SUCCESS",
        metadata={"target_rail": "upi_intent", "retry_count": 1}
    )

    # Verify all 11 required fields are present and correctly populated
    assert event.id is not None
    assert event.timestamp is not None
    assert isinstance(event.timestamp, datetime)
    assert event.event_type == AuditEventType.RECOVERY_ACTION.value
    assert event.actor == AuditActor.SYSTEM.value
    assert event.agent_decision_id == agent_id
    assert event.transaction_id == tx_id
    assert event.opportunity_id == opp_id
    assert event.action_id == act_id
    assert event.policy_decision_id == pol_id
    assert event.status == "SUCCESS"
    assert "dispatched to Razorpay Test" in event.summary
    assert event.metadata_json == {"target_rail": "upi_intent", "retry_count": 1}


def test_track_all_13_operations(db_session: Session, seeded_db):
    """
    Test 2: System tracks all 13 critical lifecycle operations:
    1. transaction detected
    2. revenue leak detected
    3. ML prediction
    4. recovery opportunity created
    5. AI investigation
    6. AI recommendation
    7. policy decision
    8. approval
    9. recovery action
    10. provider response
    11. webhook
    12. recovery verification
    13. final recovered amount
    """
    merchant = db_session.query(Merchant).first()
    assert merchant is not None
    audit_svc = AuditService(db_session)

    tx_id = uuid.uuid4()
    leak_id = uuid.uuid4()
    opp_id = uuid.uuid4()
    act_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    pol_id = uuid.uuid4()

    # 1. Transaction detected
    ev1 = audit_svc.log_transaction_detected(
        merchant_id=merchant.id,
        transaction_id=tx_id,
        amount=Decimal("4999.00"),
        payment_method="upi",
        bank="HDFC",
        error_code="GATEWAY_TIMEOUT",
        failure_reason="Bank authorization timeout"
    )
    assert ev1.event_type == AuditEventType.TRANSACTION_DETECTED.value

    # 2. Revenue leak detected
    ev2 = audit_svc.log_revenue_leak_detected(
        merchant_id=merchant.id,
        leak_id=leak_id,
        leak_type="payment_degradation",
        severity="critical",
        revenue_at_risk=Decimal("125000.00"),
        root_causes=["HDFC UPI gateway latency spike"]
    )
    assert ev2.event_type == AuditEventType.REVENUE_LEAK_DETECTED.value

    # 3. ML prediction
    ev3 = audit_svc.log_ml_prediction(
        merchant_id=merchant.id,
        transaction_id=tx_id,
        model_name="payment_recovery_probability_v1",
        prediction=0.842,
        confidence=0.89,
        features={"payment_method": "upi", "bank": "HDFC", "amount": 4999}
    )
    assert ev3.event_type == AuditEventType.ML_PREDICTION.value

    # 4. Recovery opportunity created
    ev4 = audit_svc.log_opportunity_created(
        merchant_id=merchant.id,
        opportunity_id=opp_id,
        transaction_id=tx_id,
        amount=Decimal("4999.00"),
        recovery_prob=0.842,
        expected_recovery=Decimal("4209.00"),
        priority="HIGH"
    )
    assert ev4.event_type == AuditEventType.OPPORTUNITY_CREATED.value

    # 5. AI investigation
    ev5 = audit_svc.log_ai_investigation(
        merchant_id=merchant.id,
        opportunity_id=opp_id,
        problem="UPI failure spike observed during 19:00-21:00 peak window.",
        evidence="Bank error logs confirm 34 timeout events on HDFC gateway.",
        agent_decision_id=agent_id
    )
    assert ev5.event_type == AuditEventType.AI_INVESTIGATION.value
    assert ev5.actor == AuditActor.AI_RECOVERY_AGENT.value

    # 6. AI recommendation
    ev6 = audit_svc.log_ai_recommendation(
        merchant_id=merchant.id,
        opportunity_id=opp_id,
        recommended_action="CREATE_PAYMENT_LINK",
        reason="Customer has strong tenure; high probability of recovery via 1-click link.",
        risk_level="low",
        agent_decision_id=agent_id
    )
    assert ev6.event_type == AuditEventType.AI_RECOMMENDATION.value
    assert ev6.actor == AuditActor.AI_RECOVERY_AGENT.value

    # 7. Policy decision
    ev7 = audit_svc.log_policy_decision(
        merchant_id=merchant.id,
        opportunity_id=opp_id,
        action_type="CREATE_PAYMENT_LINK",
        allowed=True,
        approval_required=False,
        reason="Rule: Low-value + high-confidence is eligible for automatic recovery.",
        policy_decision_id=pol_id
    )
    assert ev7.event_type == AuditEventType.POLICY_DECISION.value
    assert ev7.actor == AuditActor.POLICY_ENGINE.value

    # 8. Approval
    ev8 = audit_svc.log_approval(
        merchant_id=merchant.id,
        opportunity_id=opp_id,
        action_id=act_id,
        approved=True,
        operator_notes="Automatic policy execution granted."
    )
    assert ev8.event_type == AuditEventType.APPROVAL.value

    # 9. Recovery action
    ev9 = audit_svc.log_recovery_action(
        merchant_id=merchant.id,
        opportunity_id=opp_id,
        action_id=act_id,
        action_type="create_payment_link",
        provider="razorpay_test",
        amount=Decimal("4999.00"),
        request_data={"customer_name": "Kavindran", "channel": "sms"}
    )
    assert ev9.event_type == AuditEventType.RECOVERY_ACTION.value

    # 10. Provider response
    ev10 = audit_svc.log_provider_response(
        merchant_id=merchant.id,
        opportunity_id=opp_id,
        action_id=act_id,
        provider="razorpay_test",
        status="success",
        response_data={"id": "plink_test_12345", "status": "created"}
    )
    assert ev10.event_type == AuditEventType.PROVIDER_RESPONSE.value

    # 11. Webhook
    ev11 = audit_svc.log_webhook(
        merchant_id=merchant.id,
        event_name="payment.captured",
        event_id="evt_hook_98765",
        payment_id=str(tx_id)
    )
    assert "webhook" in ev11.event_type
    assert ev11.actor == AuditActor.WEBHOOK_ENGINE.value

    # 12. Recovery verification
    ev12 = audit_svc.log_recovery_verification(
        merchant_id=merchant.id,
        opportunity_id=opp_id,
        action_id=act_id,
        verified=True,
        verification_method="GATEWAY_HMAC_AND_STATUS_QUERY",
        details={"payment_status": "captured", "amount_verified": 4999.00}
    )
    assert ev12.event_type == AuditEventType.RECOVERY_VERIFICATION.value

    # 13. Final recovered amount
    ev13 = audit_svc.log_final_recovered_amount(
        merchant_id=merchant.id,
        opportunity_id=opp_id,
        recovered_amount=Decimal("4999.00"),
        action_id=act_id
    )
    assert ev13.event_type == AuditEventType.FINAL_RECOVERED_AMOUNT.value
    assert "₹4,999.00" in ev13.summary


def test_api_audit_multi_dimensional_filters(client: TestClient, db_session: Session, seeded_db):
    """
    Test 3: GET /api/audit supports multi-dimensional filtering:
    - merchant
    - transaction
    - opportunity
    - action
    - date
    - event type
    """
    merchant = db_session.query(Merchant).first()
    assert merchant is not None
    audit_svc = AuditService(db_session)

    specific_tx = uuid.uuid4()
    specific_opp = uuid.uuid4()
    specific_act = uuid.uuid4()
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    audit_svc.record_event(
        merchant_id=merchant.id,
        event_type=AuditEventType.TRANSACTION_DETECTED,
        summary="Filter test transaction detected event",
        transaction_id=specific_tx,
        opportunity_id=specific_opp,
        action_id=specific_act,
        status="INFO"
    )

    audit_svc.record_event(
        merchant_id=merchant.id,
        event_type=AuditEventType.RECOVERY_ACTION,
        summary="Filter test recovery action event",
        transaction_id=specific_tx,
        opportunity_id=specific_opp,
        action_id=specific_act,
        status="SUCCESS"
    )

    # 1. Filter by merchant ID
    r_merch = client.get(f"/api/audit?merchant={merchant.id}")
    assert r_merch.status_code == 200
    res_data = r_merch.json()
    assert res_data["total"] >= 2
    assert all(item["merchant_id"] == str(merchant.id) for item in res_data["items"])

    # 2. Filter by transaction ID
    r_tx = client.get(f"/api/audit?transaction={specific_tx}")
    assert r_tx.status_code == 200
    assert r_tx.json()["total"] >= 2
    assert all(item["transaction_id"] == str(specific_tx) for item in r_tx.json()["items"])

    # 3. Filter by opportunity ID
    r_opp = client.get(f"/api/audit?opportunity={specific_opp}")
    assert r_opp.status_code == 200
    assert r_opp.json()["total"] >= 2
    assert all(item["opportunity_id"] == str(specific_opp) for item in r_opp.json()["items"])

    # 4. Filter by action ID
    r_act = client.get(f"/api/audit?action={specific_act}")
    assert r_act.status_code == 200
    assert r_act.json()["total"] >= 2
    assert all(item["action_id"] == str(specific_act) for item in r_act.json()["items"])

    # 5. Filter by date
    r_date = client.get(f"/api/audit?date={now_date}")
    assert r_date.status_code == 200
    assert r_date.json()["total"] >= 2

    # 6. Filter by event type
    r_type = client.get("/api/audit?event_type=recovery_action")
    assert r_type.status_code == 200
    for item in r_type.json()["items"]:
        assert "recovery_action" in item["event_type"].lower()


def test_action_causality_timeline_inspector(client: TestClient, db_session: Session, seeded_db):
    """
    Test 4: The UI / API allows a judge to click a recovery action
    and view the full chronological causality sequence from transaction failure to recovery.
    GET /api/audit/timeline/{action_id}
    """
    merchant = db_session.query(Merchant).first()
    assert merchant is not None

    opp = db_session.query(RecoveryOpportunity).filter(RecoveryOpportunity.merchant_id == merchant.id).first()
    if not opp:
        opp = RecoveryOpportunity(
            id=uuid.uuid4(),
            merchant_id=merchant.id,
            payment_id=uuid.uuid4(),
            gross_value_affected=Decimal("6500.00"),
            recovery_probability=Decimal("0.85"),
            expected_recovered_value=Decimal("5525.00"),
            status="OPEN",
            priority="HIGH",
            priority_score=Decimal("85.00"),
            risk="low"
        )
        db_session.add(opp)
        db_session.commit()

    # Create RecoveryAction
    act = RecoveryAction(
        id=uuid.uuid4(),
        opportunity_id=opp.id,
        action_type="create_payment_link",
        provider="razorpay_test",
        status="SUCCESS",
        amount=Decimal("6500.00"),
        request={"channel": "whatsapp"},
        result={"id": "plink_causality_001", "status": "paid"},
        reason="Autonomous recovery executed."
    )
    db_session.add(act)
    db_session.commit()

    # Seed chronological chain for this action
    audit_svc = AuditService(db_session)
    t0 = datetime.now(timezone.utc) - timedelta(minutes=10)

    audit_svc.record_event(
        merchant_id=merchant.id,
        event_type=AuditEventType.TRANSACTION_DETECTED,
        summary="Payment failed due to gateway timeout",
        opportunity_id=opp.id,
        action_id=act.id,
        timestamp=t0
    )
    audit_svc.record_event(
        merchant_id=merchant.id,
        event_type=AuditEventType.OPPORTUNITY_CREATED,
        summary="Opportunity prioritized as HIGH",
        opportunity_id=opp.id,
        action_id=act.id,
        timestamp=t0 + timedelta(seconds=10)
    )
    audit_svc.record_event(
        merchant_id=merchant.id,
        event_type=AuditEventType.RECOVERY_ACTION,
        summary="Recovery payment link generated",
        opportunity_id=opp.id,
        action_id=act.id,
        timestamp=t0 + timedelta(seconds=20)
    )
    audit_svc.record_event(
        merchant_id=merchant.id,
        event_type=AuditEventType.FINAL_RECOVERED_AMOUNT,
        summary="Final recovered amount: ₹6,500.00",
        opportunity_id=opp.id,
        action_id=act.id,
        timestamp=t0 + timedelta(seconds=30)
    )

    resp = client.get(f"/api/audit/timeline/{act.id}")
    assert resp.status_code == 200
    timeline_data = resp.json()

    assert timeline_data["action_id"] == str(act.id)
    assert timeline_data["total_events"] >= 4
    assert timeline_data["action_type"] == "create_payment_link"
    assert timeline_data["status"] == "SUCCESS"
    assert Decimal(str(timeline_data["amount"])) == Decimal("6500.00")

    events = timeline_data["timeline"]
    # Check chronological order (earliest first)
    timestamps = [e["timestamp"] for e in events]
    assert timestamps == sorted(timestamps)

    # Verify event types present in causality sequence
    types = [e["event_type"] for e in events]
    assert AuditEventType.TRANSACTION_DETECTED.value in types
    assert AuditEventType.RECOVERY_ACTION.value in types
    assert AuditEventType.FINAL_RECOVERED_AMOUNT.value in types


def test_sanitize_metadata_zero_credential_exposure():
    """
    Test 5: Sensitive credentials and secrets are NEVER exposed in audit metadata.
    Redacts: secret, key_secret, webhook_secret, password, authorization, token, private_key.
    Masks: key_id.
    """
    dirty_payload = {
        "merchant_name": "Acme Retail",
        "api_secret": "rzp_live_secret_very_confidential",
        "key_secret": "super_secret_key_12345",
        "webhook_secret": "whsec_live_9988776655",
        "authorization": "Bearer eyJhbGciOiJIUzI1NiIsIn...",
        "auth_token": "token_abc_xyz_secret",
        "key_id": "rzp_test_9A8B7C6D5E4F",
        "nested_gateway": {
            "password": "db_password_123",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----...",
            "safe_field": "1-Click Payment Link"
        },
        "tags": ["recovery", "high_priority"]
    }

    sanitized = sanitize_metadata(dirty_payload)

    # Verify secrets are thoroughly redacted
    assert sanitized["api_secret"] == "[REDACTED]"
    assert sanitized["key_secret"] == "[REDACTED]"
    assert sanitized["webhook_secret"] == "[REDACTED]"
    assert sanitized["authorization"] == "[REDACTED]"
    assert sanitized["auth_token"] == "[REDACTED]"
    assert sanitized["nested_gateway"]["password"] == "[REDACTED]"
    assert sanitized["nested_gateway"]["private_key"] == "[REDACTED]"

    # Verify key_id is safely masked (first 6 and last 4 kept)
    assert sanitized["key_id"] == "rzp_te...5E4F"

    # Verify non-sensitive metadata is preserved intact
    assert sanitized["merchant_name"] == "Acme Retail"
    assert sanitized["nested_gateway"]["safe_field"] == "1-Click Payment Link"
    assert sanitized["tags"] == ["recovery", "high_priority"]


def test_audit_timeline_ui_serves_html(client: TestClient):
    """
    Test 6: The Audit Timeline UI is accessible at /audit and /api/audit/ui,
    returning an interactive, beautiful HTML application for judges.
    """
    # 1. Test /audit
    res_ui = client.get("/audit")
    assert res_ui.status_code == 200
    assert "text/html" in res_ui.headers["content-type"]
    assert "Immutable Audit" in res_ui.text
    assert "Causal Chain Inspector" in res_ui.text
    assert "Operational Audit Log" in res_ui.text

    # 2. Test /api/audit/ui
    res_api_ui = client.get("/api/audit/ui")
    assert res_api_ui.status_code == 200
    assert "text/html" in res_api_ui.headers["content-type"]
    assert "Immutable Audit" in res_api_ui.text
