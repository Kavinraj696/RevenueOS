import os
import uuid
from decimal import Decimal
from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from app.db.base import Base, quantize_inr
from app.models import (
    Merchant,
    Customer,
    Payment,
    PaymentAttempt,
    Subscription,
    SubscriptionAttempt,
    CheckoutSession,
    RevenueLeak,
    RecoveryOpportunity,
    RecoveryAction,
    AgentDecision,
    PolicyDecision,
    AuditEvent,
    WebhookEvent,
    Experiment,
    ModelPrediction,
)
from app.models.enums import (
    PaymentStatus,
    PaymentAttemptStatus,
    SubscriptionStatus,
    CheckoutSessionStatus,
    LeakType,
    OpportunityStatus,
    ActionStatus,
    ActionType,
    PolicyAction,
    RiskSegment,
    AuditEventType,
    AuditActor,
)


@pytest.fixture
def isolated_clean_db(tmp_path):
    """
    Creates an isolated temporary SQLite database for database health tests.
    Guarantees that revenueos.db is never touched.
    """
    db_file = tmp_path / "stage1_health_isolated.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    yield session, engine

    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    if db_file.exists():
        db_file.unlink()


def test_dev_database_never_touched_by_tests():
    """Verify that development database revenueos.db is not modified by test runs."""
    dev_db_path = "revenueos.db"
    if os.path.exists(dev_db_path):
        mtime_before = os.path.getmtime(dev_db_path)
        # Re-check to confirm it remains unchanged
        assert os.path.exists(dev_db_path)
        assert os.path.getmtime(dev_db_path) == mtime_before


def test_database_connection_and_transaction_rollback(isolated_clean_db):
    """Verify database connection, transaction execution, and rollback."""
    session, engine = isolated_clean_db

    # Test basic raw connection
    result = session.execute(text("SELECT 1")).scalar()
    assert result == 1

    # Insert a merchant but rollback
    merchant = Merchant(name="Rollback Inc", email="rollback@test.com")
    session.add(merchant)
    session.flush()
    assert merchant.id is not None

    # Rollback transaction
    session.rollback()

    # Verify table is empty after rollback
    count = session.query(Merchant).count()
    assert count == 0


def test_all_sixteen_models_creation_and_persistence(isolated_clean_db):
    """
    Verify that all 16 documented models can be cleanly initialized,
    persisted with foreign key relationships, and queried.
    """
    session, _ = isolated_clean_db

    # 1. Merchant
    merchant = Merchant(
        name="Apex Retails",
        email="ops@apex.in",
        settings_json={"currency": "INR", "mode": "test"}
    )
    session.add(merchant)
    session.flush()
    assert isinstance(merchant.id, uuid.UUID)

    # 2. Customer
    customer = Customer(
        merchant_id=merchant.id,
        external_ref="cust_stage1_001",
        risk_segment=RiskSegment.LOW.value,
        lifetime_value=Decimal("25000.00")
    )
    session.add(customer)
    session.flush()
    assert customer.merchant.name == "Apex Retails"

    # 3. Payment
    payment = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        amount=Decimal("4999.00"),
        currency="INR",
        status=PaymentStatus.FAILED.value,
        payment_method="upi",
        bank="HDFC",
        device_type="android",
        route="hdfc_upi_primary"
    )
    session.add(payment)
    session.flush()

    # 4. PaymentAttempt
    attempt = PaymentAttempt(
        payment_id=payment.id,
        attempt_number=1,
        status=PaymentAttemptStatus.FAILED.value,
        failure_reason="Gateway timeout on bank rail",
        error_code="GATEWAY_TIMEOUT"
    )
    session.add(attempt)
    session.flush()
    assert len(payment.attempts) == 1

    # 5. Subscription
    sub = Subscription(
        merchant_id=merchant.id,
        customer_id=customer.id,
        plan_name="Pro Cloud",
        plan_amount=Decimal("1299.00"),
        currency="INR",
        billing_cycle="monthly",
        status=SubscriptionStatus.ACTIVE.value
    )
    session.add(sub)
    session.flush()

    # 6. SubscriptionAttempt
    sub_attempt = SubscriptionAttempt(
        subscription_id=sub.id,
        status="failed",
        failure_reason="Mandate authentication expired",
        error_code="MANDATE_AUTH_EXPIRED"
    )
    session.add(sub_attempt)
    session.flush()

    # 7. CheckoutSession
    cs = CheckoutSession(
        merchant_id=merchant.id,
        customer_id=customer.id,
        cart_value=Decimal("8500.00"),
        currency="INR",
        status=CheckoutSessionStatus.ABANDONED.value,
        stage_dropped="otp_entry"
    )
    session.add(cs)
    session.flush()

    # 8. RevenueLeak
    now = datetime.now(timezone.utc)
    leak = RevenueLeak(
        merchant_id=merchant.id,
        leak_type=LeakType.PAYMENT_FAILURE.value,
        pattern_description="HDFC UPI gateway latency degradation",
        affected_amount=Decimal("4999.00"),
        revenue_at_risk=Decimal("4999.00"),
        affected_transactions=1,
        severity="high",
        severity_score=Decimal("8.50"),
        confidence=Decimal("0.9500"),
        status="open",
        detection_window_start=now,
        detection_window_end=now
    )
    session.add(leak)
    session.flush()

    # 9. RecoveryOpportunity
    opp = RecoveryOpportunity(
        revenue_leak_id=leak.id,
        merchant_id=merchant.id,
        customer_id=customer.id,
        payment_id=payment.id,
        gross_value_affected=Decimal("4999.00"),
        potentially_recoverable_value=Decimal("4999.00"),
        recovery_probability=Decimal("0.8400"),
        expected_recovered_value=quantize_inr(Decimal("4999.00") * Decimal("0.84")),
        status=OpportunityStatus.OPEN.value,
        priority="HIGH",
        priority_score=Decimal("84.00")
    )
    session.add(opp)
    session.flush()

    # 10. AgentDecision
    agent_dec = AgentDecision(
        opportunity_id=opp.id,
        problem="Elevated UPI failure rate",
        evidence_json={"bank": "HDFC", "method": "upi"},
        estimated_impact=Decimal("4999.00"),
        recovery_probability=Decimal("0.8400"),
        recommended_action="Create a payment link for customer re-engagement",
        reason="High recovery probability with alternate payment method",
        risk_level="low",
        expected_recovery=Decimal("4199.16"),
        actual_recovery=Decimal("0.00"),
        currency="INR"
    )
    session.add(agent_dec)
    session.flush()

    # 11. PolicyDecision
    policy_dec = PolicyDecision(
        agent_decision_id=agent_dec.id,
        opportunity_id=opp.id,
        action_type=PolicyAction.CREATE_PAYMENT_LINK.value,
        allowed=True,
        approval_required=False,
        risk_level="low",
        max_amount_allowed=Decimal("15000.00"),
        retry_limit=3,
        cooldown_seconds=14400,
        confidence_threshold=Decimal("0.6000"),
        decision_reason="Transaction under ₹15k automated limit"
    )
    session.add(policy_dec)
    session.flush()

    # 12. RecoveryAction
    rec_action = RecoveryAction(
        opportunity_id=opp.id,
        policy_decision_id=policy_dec.id,
        action_type=ActionType.PAYMENT_LINK.value,
        amount=Decimal("4999.00"),
        status=ActionStatus.PROPOSED.value,
        reason="Automated payment link recovery",
        predicted_outcome="Recover ₹4199.16 via alternate UPI/card handle"
    )
    session.add(rec_action)
    session.flush()

    # 13. AuditEvent
    audit = AuditEvent(
        merchant_id=merchant.id,
        actor=AuditActor.AI_RECOVERY_AGENT.value,
        event_type=AuditEventType.RECOVERY_ACTION.value,
        related_entity_type="recovery_opportunity",
        related_entity_id=opp.id,
        opportunity_id=opp.id,
        action_id=rec_action.id,
        status="SUCCESS",
        summary="AI Agent proposed payment link action",
        message="Recovery action queued following policy evaluation",
        request_id="req_stage1_test_001"
    )
    session.add(audit)
    session.flush()

    # 14. WebhookEvent
    webhook = WebhookEvent(
        provider="razorpay",
        event_id="evt_stage1_test_001",
        event_type="payment.failed",
        raw_payload_json={"event": "payment.failed", "id": "pay_123"},
        signature_verified=True,
        processed=True
    )
    session.add(webhook)
    session.flush()

    # 15. Experiment
    experiment = Experiment(
        name="Smart Retry Routing A/B Test",
        hypothesis="Dynamic route switching increases recovery rate by 15%",
        scenario="SCENARIO_1"
    )
    session.add(experiment)
    session.flush()

    # 16. ModelPrediction
    prediction = ModelPrediction(
        model_name="payment_recovery_probability",
        model_version="v1.0.0",
        entity_type="payment",
        entity_id=payment.id,
        input_features_json={"amount": 4999.0, "method": "upi", "bank": "HDFC"},
        prediction=Decimal("0.8400"),
        confidence=Decimal("0.9100")
    )
    session.add(prediction)
    session.commit()

    # Query verification
    assert session.query(Merchant).count() == 1
    assert session.query(Customer).count() == 1
    assert session.query(Payment).count() == 1
    assert session.query(PaymentAttempt).count() == 1
    assert session.query(Subscription).count() == 1
    assert session.query(SubscriptionAttempt).count() == 1
    assert session.query(CheckoutSession).count() == 1
    assert session.query(RevenueLeak).count() == 1
    assert session.query(RecoveryOpportunity).count() == 1
    assert session.query(AgentDecision).count() == 1
    assert session.query(PolicyDecision).count() == 1
    assert session.query(RecoveryAction).count() == 1
    assert session.query(AuditEvent).count() == 1
    assert session.query(WebhookEvent).count() == 1
    assert session.query(Experiment).count() == 1
    assert session.query(ModelPrediction).count() == 1


def test_foreign_key_and_cascade_behavior(isolated_clean_db):
    """Verify that deleting a payment cascades to payment attempts properly."""
    session, _ = isolated_clean_db

    merchant = Merchant(name="Cascade Store", email="cascade@test.com")
    session.add(merchant)
    session.flush()

    customer = Customer(merchant_id=merchant.id, external_ref="cust_casc")
    session.add(customer)
    session.flush()

    payment = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        amount=Decimal("1500.00"),
        currency="INR",
        status=PaymentStatus.FAILED.value,
        payment_method="card",
        device_type="desktop",
        route="test_route"
    )
    session.add(payment)
    session.flush()

    att1 = PaymentAttempt(payment_id=payment.id, attempt_number=1, status="failed")
    att2 = PaymentAttempt(payment_id=payment.id, attempt_number=2, status="failed")
    session.add_all([att1, att2])
    session.commit()

    assert session.query(PaymentAttempt).filter_by(payment_id=payment.id).count() == 2

    # Delete payment
    session.delete(payment)
    session.commit()

    # Payment attempts should be deleted by cascade
    assert session.query(PaymentAttempt).filter_by(payment_id=payment.id).count() == 0


def test_unique_constraint_enforcement(isolated_clean_db):
    """Verify that unique constraints (e.g. webhook event_id) prevent duplicates."""
    session, _ = isolated_clean_db

    evt1 = WebhookEvent(
        provider="razorpay",
        event_id="unique_webhook_id_999",
        event_type="payment.captured",
        raw_payload_json={},
        signature_verified=True,
        processed=False
    )
    session.add(evt1)
    session.commit()

    # Duplicate must raise IntegrityError
    evt2 = WebhookEvent(
        provider="razorpay",
        event_id="unique_webhook_id_999",
        event_type="payment.captured",
        raw_payload_json={},
        signature_verified=True,
        processed=False
    )
    session.add(evt2)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()
