import pytest
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import (
    Merchant,
    Payment,
    PaymentAttempt,
    Subscription,
    SubscriptionAttempt,
    CheckoutSession,
    PaymentStatus,
    BankCode,
    PaymentMethod,
    DeviceType,
)
from app.synthetic.generator import SyntheticDataGenerator
from app.synthetic.scenarios import SCENARIO_CONFIGS

def test_generator_determinism_and_reproducibility():
    """Verify that identical seeds produce bit-for-bit identical results."""
    import json
    from decimal import Decimal
    from sqlalchemy.pool import StaticPool

    def custom_json_serializer(obj):
        return json.dumps(obj, default=lambda o: str(o) if isinstance(o, Decimal) else str(o))

    # Engine 1
    engine1 = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool, json_serializer=custom_json_serializer)
    Base.metadata.create_all(bind=engine1)
    Session1 = sessionmaker(bind=engine1)
    session1 = Session1()

    gen1 = SyntheticDataGenerator(seed=12345)
    res1 = gen1.generate_all(session1)
    payments1 = session1.query(Payment).order_by(Payment.id).all()
    total_vol1 = sum(p.amount for p in payments1)
    session1.close()

    # Engine 2
    engine2 = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool, json_serializer=custom_json_serializer)
    Base.metadata.create_all(bind=engine2)
    Session2 = sessionmaker(bind=engine2)
    session2 = Session2()

    gen2 = SyntheticDataGenerator(seed=12345)
    res2 = gen2.generate_all(session2)
    payments2 = session2.query(Payment).order_by(Payment.id).all()
    total_vol2 = sum(p.amount for p in payments2)
    session2.close()

    # Verify identical counts across all scenarios
    assert res1 == res2
    assert len(payments1) == len(payments2)
    assert total_vol1 == total_vol2
    assert isinstance(total_vol1, Decimal)

def test_intentional_pattern_payment_degradation(db_session):
    """
    Verify intentional pattern:
    Bank A (HDFC) + UPI + Android + Evening (18-22) has a drastically higher failure rate
    than the rest of the merchant's payments.
    """
    gen = SyntheticDataGenerator(seed=42)
    scenario_cfg = next(c for c in SCENARIO_CONFIGS if c["id"] == "payment_degradation")
    gen.generate_scenario(db_session, scenario_cfg)

    merchant = db_session.query(Merchant).filter(Merchant.email == scenario_cfg["email"]).one()
    all_payments = db_session.query(Payment).filter(Payment.merchant_id == merchant.id).all()

    cluster_target = []
    cluster_control = []

    for p in all_payments:
        is_target = (
            p.bank == BankCode.HDFC.value
            and p.payment_method == PaymentMethod.UPI.value
            and p.device_type == DeviceType.ANDROID.value
            and (18 <= p.created_at.hour <= 22)
        )
        if is_target:
            cluster_target.append(p)
        else:
            cluster_control.append(p)

    assert len(cluster_target) > 0, "Target degradation cluster must contain transactions"

    target_failures = [p for p in cluster_target if p.status == PaymentStatus.FAILED.value]
    target_failure_rate = len(target_failures) / len(cluster_target)

    control_failures = [p for p in cluster_control if p.status == PaymentStatus.FAILED.value]
    control_failure_rate = len(control_failures) / len(cluster_control)

    # In our intentional pattern: target failure rate is ~75%, control is ~4%
    assert target_failure_rate >= 0.60, f"Target failure rate {target_failure_rate:.2f} should be >= 0.60"
    assert control_failure_rate <= 0.10, f"Control failure rate {control_failure_rate:.2f} should be <= 0.10"

    # Verify specific error code on the target failures
    for tf in target_failures:
        attempts = db_session.query(PaymentAttempt).filter(PaymentAttempt.payment_id == tf.id).all()
        assert any(a.error_code == "BAD_REQUEST_GATEWAY_TIMEOUT" for a in attempts)

def test_intentional_pattern_checkout_abandonment(db_session):
    """Verify Scenario 3 cart drop-offs are clustered at otp_entry and payment_method_select with high cart values."""
    gen = SyntheticDataGenerator(seed=42)
    scenario_cfg = next(c for c in SCENARIO_CONFIGS if c["id"] == "checkout_abandonment")
    gen.generate_scenario(db_session, scenario_cfg)

    merchant = db_session.query(Merchant).filter(Merchant.email == scenario_cfg["email"]).one()
    sessions = db_session.query(CheckoutSession).filter(CheckoutSession.merchant_id == merchant.id).all()

    abandoned = [s for s in sessions if s.status == "abandoned"]
    assert len(abandoned) > 0

    # Verify high cart values
    avg_cart_val = sum(s.cart_value for s in abandoned) / len(abandoned)
    assert avg_cart_val >= Decimal("20000.00"), f"Average cart value {avg_cart_val} should be >= 20,000 INR"

    # Verify dropped stages are specific
    for s in abandoned:
        assert s.stage_dropped in ("otp_entry", "payment_method_select")

def test_intentional_pattern_subscription_spike(db_session):
    """Verify Scenario 4 has high mandate failure rate with specific recurring error codes."""
    gen = SyntheticDataGenerator(seed=42)
    scenario_cfg = next(c for c in SCENARIO_CONFIGS if c["id"] == "subscription_spike")
    gen.generate_scenario(db_session, scenario_cfg)

    merchant = db_session.query(Merchant).filter(Merchant.email == scenario_cfg["email"]).one()
    subs = db_session.query(Subscription).filter(Subscription.merchant_id == merchant.id).all()

    failed_subs = [s for s in subs if s.status == "failed"]
    assert len(failed_subs) > 0
    failure_rate = len(failed_subs) / len(subs)
    assert failure_rate >= 0.30

    attempts = (
        db_session.query(SubscriptionAttempt)
        .join(Subscription)
        .filter(Subscription.merchant_id == merchant.id, SubscriptionAttempt.status == "failed")
        .all()
    )
    error_codes = {a.error_code for a in attempts}
    assert "MANDATE_LIMIT_EXCEEDED" in error_codes or "CARD_EXPIRED" in error_codes

def test_intentional_pattern_high_value_recoveries(db_session):
    """Verify Scenario 5 has high value payments and recovered transactions."""
    gen = SyntheticDataGenerator(seed=42)
    scenario_cfg = next(c for c in SCENARIO_CONFIGS if c["id"] == "high_value_recoverable")
    gen.generate_scenario(db_session, scenario_cfg)

    merchant = db_session.query(Merchant).filter(Merchant.email == scenario_cfg["email"]).one()
    recovered_payments = db_session.query(Payment).filter(
        Payment.merchant_id == merchant.id,
        Payment.status == PaymentStatus.RECOVERED.value
    ).all()

    assert len(recovered_payments) > 0
    for rp in recovered_payments:
        assert rp.amount >= Decimal("35000.00")
        # Check attempts
        attempts = db_session.query(PaymentAttempt).filter(PaymentAttempt.payment_id == rp.id).all()
        assert len(attempts) >= 2
        assert attempts[0].status == "failed"
        assert attempts[1].status == "success"
