import uuid
from decimal import Decimal
from datetime import datetime, timezone
import pytest
from sqlalchemy.exc import IntegrityError

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
    PaymentStatus,
    PaymentAttemptStatus,
    SubscriptionStatus,
    CheckoutSessionStatus,
    PaymentMethod,
    BankCode,
    DeviceType,
    RiskSegment,
)

def test_merchant_and_customer_creation(db_session):
    merchant = Merchant(
        name="Test Merchant Ltd",
        email="test@merchant.com",
        settings_json={"mode": "test", "currency": "INR"}
    )
    db_session.add(merchant)
    db_session.flush()

    assert isinstance(merchant.id, uuid.UUID)
    assert merchant.created_at is not None

    customer = Customer(
        merchant_id=merchant.id,
        external_ref="cust_syn_test_123",
        risk_segment=RiskSegment.LOW.value,
        lifetime_value=Decimal("15000.50")
    )
    db_session.add(customer)
    db_session.flush()

    assert isinstance(customer.id, uuid.UUID)
    assert customer.lifetime_value == Decimal("15000.50")
    assert isinstance(customer.lifetime_value, Decimal)
    assert customer.merchant.name == "Test Merchant Ltd"

def test_payment_strict_decimal_precision(db_session):
    merchant = Merchant(name="Fintech Corp", email="ops@fintech.com")
    db_session.add(merchant)
    db_session.flush()

    customer = Customer(merchant_id=merchant.id, external_ref="cust_1", lifetime_value=Decimal("0.00"))
    db_session.add(customer)
    db_session.flush()

    exact_amount = Decimal("14999.99")
    payment = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        amount=exact_amount,
        currency="INR",
        status=PaymentStatus.SUCCESS.value,
        payment_method=PaymentMethod.UPI.value,
        bank=BankCode.HDFC.value,
        device_type=DeviceType.ANDROID.value,
        route="hdfc_upi_direct"
    )
    db_session.add(payment)
    db_session.flush()

    # Re-fetch from DB and verify type and precision
    fetched = db_session.query(Payment).filter(Payment.id == payment.id).one()
    assert isinstance(fetched.amount, Decimal)
    assert fetched.amount == exact_amount
    assert str(fetched.amount) == "14999.99"
    # Never floating point
    assert not isinstance(fetched.amount, float)

def test_payment_attempts_and_cascade(db_session):
    merchant = Merchant(name="Store A", email="store@a.com")
    db_session.add(merchant)
    db_session.flush()

    customer = Customer(merchant_id=merchant.id, external_ref="cust_2", lifetime_value=Decimal("0.00"))
    db_session.add(customer)
    db_session.flush()

    payment = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        amount=Decimal("2500.00"),
        currency="INR",
        status=PaymentStatus.FAILED.value,
        payment_method=PaymentMethod.CARD.value,
        device_type=DeviceType.IOS.value,
        route="razorpay_smart_router"
    )
    db_session.add(payment)
    db_session.flush()

    att1 = PaymentAttempt(
        payment_id=payment.id,
        attempt_number=1,
        status=PaymentAttemptStatus.FAILED.value,
        failure_reason="Card expired",
        error_code="CARD_EXPIRED"
    )
    att2 = PaymentAttempt(
        payment_id=payment.id,
        attempt_number=2,
        status=PaymentAttemptStatus.FAILED.value,
        failure_reason="Insufficient funds",
        error_code="INSUFFICIENT_FUNDS"
    )
    db_session.add_all([att1, att2])
    db_session.flush()

    assert len(payment.attempts) == 2
    assert payment.attempts[0].attempt_number == 1
    assert payment.attempts[1].attempt_number == 2

    # Verify cascade delete
    payment_id = payment.id
    db_session.delete(payment)
    db_session.flush()

    remaining_attempts = db_session.query(PaymentAttempt).filter(PaymentAttempt.payment_id == payment_id).all()
    assert len(remaining_attempts) == 0

def test_subscription_and_checkout_session(db_session):
    merchant = Merchant(name="SaaS Sub Store", email="sub@store.com")
    db_session.add(merchant)
    db_session.flush()

    customer = Customer(merchant_id=merchant.id, external_ref="cust_sub_1", lifetime_value=Decimal("5000.00"))
    db_session.add(customer)
    db_session.flush()

    sub = Subscription(
        merchant_id=merchant.id,
        customer_id=customer.id,
        plan_name="Enterprise Plan",
        plan_amount=Decimal("9999.00"),
        currency="INR",
        billing_cycle="monthly",
        status=SubscriptionStatus.ACTIVE.value
    )
    db_session.add(sub)

    cs = CheckoutSession(
        merchant_id=merchant.id,
        customer_id=customer.id,
        cart_value=Decimal("45000.00"),
        currency="INR",
        status=CheckoutSessionStatus.ABANDONED.value,
        stage_dropped="otp_entry",
        device_type="android"
    )
    db_session.add(cs)
    db_session.flush()

    assert isinstance(sub.plan_amount, Decimal)
    assert sub.plan_amount == Decimal("9999.00")
    assert isinstance(cs.cart_value, Decimal)
    assert cs.cart_value == Decimal("45000.00")
    assert cs.stage_dropped == "otp_entry"

def test_webhook_event_idempotency_constraint(db_session):
    evt1 = WebhookEvent(
        provider="razorpay",
        event_id="evt_test_unique_001",
        event_type="payment.captured",
        raw_payload_json={"payment": {"id": "pay_123"}},
        signature_verified=True,
        processed=False
    )
    db_session.add(evt1)
    db_session.flush()

    # Second event with identical event_id must fail unique constraint
    evt2 = WebhookEvent(
        provider="razorpay",
        event_id="evt_test_unique_001",
        event_type="payment.captured",
        raw_payload_json={"payment": {"id": "pay_123"}},
        signature_verified=True,
        processed=False
    )
    db_session.add(evt2)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
