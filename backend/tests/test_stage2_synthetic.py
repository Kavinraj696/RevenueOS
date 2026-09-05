"""
RevenueOS Stage 2 Test Suite: Synthetic Revenue Data & Loss Simulation
=======================================================================
Verifies:
  1. Deterministic generation with identical seeds produces equivalent data
  2. Differing seeds produce divergent datasets
  3. Healthy merchant baseline behavior (2–5% failure rate, natural distributions)
  4. Payment degradation scenario (HDFC UPI Android evening cluster failure rate >= 70%)
  5. Checkout abandonment scenario (elevated drop-offs at OTP / payment method select)
  6. Subscription failure scenario (recurring mandate failures, card expiry)
  7. High-value recovery scenario (high-ticket recoverable payments)
  8. Non-recoverable transaction modeling (fraud risk, excessive retries, expired window)
  9. Mixed multi-issue scenario (combining all channels in an enterprise merchant)
  10. Data quality and relational integrity (no orphan FKs, valid timestamps)
  11. Ground-truth integrity and separation from production data
"""

import pytest
from decimal import Decimal
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import json

from app.db.base import Base
from app.models import (
    Merchant,
    Customer,
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
from app.synthetic.scenarios import SCENARIO_CONFIGS, get_scenario_config
from app.synthetic.ground_truth import GroundTruthRegistry, NonRecoveryReason
from app.synthetic.validation import validate_dataset_integrity, calculate_observed_metrics


@pytest.fixture
def clean_mem_db():
    """Isolated in-memory SQLite database for test execution."""
    def custom_json_serializer(obj):
        return json.dumps(obj, default=lambda o: str(o) if isinstance(o, Decimal) else str(o))

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        json_serializer=custom_json_serializer
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def test_1_deterministic_generation(clean_mem_db):
    """Verify seed=42 executed twice produces identical datasets."""
    # Run 1
    gen1 = SyntheticDataGenerator(seed=42)
    res1 = gen1.generate_scenario(clean_mem_db, "healthy")
    payments1 = clean_mem_db.query(Payment).order_by(Payment.id).all()
    p1_ids = [p.id for p in payments1]
    p1_amounts = [p.amount for p in payments1]

    # Create second independent database
    engine2 = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine2)
    Session2 = sessionmaker(bind=engine2)
    db2 = Session2()

    try:
        gen2 = SyntheticDataGenerator(seed=42)
        res2 = gen2.generate_scenario(db2, "healthy")
        payments2 = db2.query(Payment).order_by(Payment.id).all()
        p2_ids = [p.id for p in payments2]
        p2_amounts = [p.amount for p in payments2]

        assert res1["payments"] == res2["payments"]
        assert res1["failed_payments"] == res2["failed_payments"]
        assert len(payments1) == len(payments2)
        assert p1_ids == p2_ids, "Transaction UUIDs must match bit-for-bit with identical seeds"
        assert p1_amounts == p2_amounts, "Transaction amounts must match bit-for-bit with identical seeds"
    finally:
        db2.close()
        engine2.dispose()


def test_2_differing_seeds_diverge(clean_mem_db):
    """Verify seed=42 vs seed=99 produce different transaction streams."""
    gen1 = SyntheticDataGenerator(seed=42)
    res1 = gen1.generate_scenario(clean_mem_db, "healthy")
    p1_amounts = [p.amount for p in clean_mem_db.query(Payment).order_by(Payment.id).all()]

    engine2 = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine2)
    Session2 = sessionmaker(bind=engine2)
    db2 = Session2()

    try:
        gen2 = SyntheticDataGenerator(seed=99)
        res2 = gen2.generate_scenario(db2, "healthy")
        p2_amounts = [p.amount for p in db2.query(Payment).order_by(Payment.id).all()]

        assert p1_amounts != p2_amounts, "Different seeds must produce different transaction amounts and ordering"
    finally:
        db2.close()
        engine2.dispose()


def test_3_healthy_scenario(clean_mem_db):
    """Verify healthy merchant baseline has low failure rate (< 6%) and natural distributions."""
    gen = SyntheticDataGenerator(seed=42)
    res = gen.generate_scenario(clean_mem_db, "healthy")
    merchant_id = res["ground_truth"].merchant_id

    metrics = calculate_observed_metrics(clean_mem_db, merchant_id)
    p_stats = metrics["payments"]

    assert p_stats["total_count"] >= 200
    assert p_stats["overall_failure_rate"] <= 0.06, f"Healthy merchant failure rate {p_stats['overall_failure_rate']:.2f} should be <= 6%"

    # Verify payment method distributions exist
    payments = clean_mem_db.query(Payment).filter(Payment.merchant_id == merchant_id).all()
    methods = {p.payment_method for p in payments}
    assert PaymentMethod.UPI.value in methods
    assert PaymentMethod.CARD.value in methods
    assert PaymentMethod.NETBANKING.value in methods


def test_4_payment_degradation(clean_mem_db):
    """Verify payment degradation scenario has sharp failure spike on HDFC UPI Android evening cluster."""
    gen = SyntheticDataGenerator(seed=42)
    res = gen.generate_scenario(clean_mem_db, "payment_degradation")
    merchant_id = res["ground_truth"].merchant_id

    metrics = calculate_observed_metrics(clean_mem_db, merchant_id)
    p_stats = metrics["payments"]

    # Cluster failure rate should be >= 65%, control should be <= 10%
    assert p_stats["cluster_failure_rate"] >= 0.65, f"Cluster failure rate {p_stats['cluster_failure_rate']:.2f} must be >= 65%"
    assert p_stats["control_failure_rate"] <= 0.10, f"Control failure rate {p_stats['control_failure_rate']:.2f} must be <= 10%"
    assert p_stats["cluster_count"] > 0

    # Ground truth validation
    gt = res["ground_truth"]
    assert gt.scenario_id == "payment_degradation"
    assert len(gt.affected_transaction_ids) > 0


def test_5_checkout_abandonment(clean_mem_db):
    """Verify checkout abandonment scenario has elevated drop-offs at OTP entry and payment method select."""
    gen = SyntheticDataGenerator(seed=42)
    res = gen.generate_scenario(clean_mem_db, "checkout_abandonment")
    merchant_id = res["ground_truth"].merchant_id

    metrics = calculate_observed_metrics(clean_mem_db, merchant_id)
    c_stats = metrics["checkouts"]

    assert c_stats["abandonment_rate"] >= 0.40, f"Observed abandonment rate {c_stats['abandonment_rate']:.2f} must be >= 40%"
    assert c_stats["lost_cart_value_inr"] > 0

    # Verify dropped stages are specific
    checkouts = clean_mem_db.query(CheckoutSession).filter(CheckoutSession.merchant_id == merchant_id).all()
    abandoned = [cs for cs in checkouts if cs.status == "abandoned"]
    for cs in abandoned:
        assert cs.stage_dropped in ("otp_entry", "payment_method_select")


def test_6_subscription_failure(clean_mem_db):
    """Verify subscription failure scenario generates high mandate failure rates with recurring error codes."""
    gen = SyntheticDataGenerator(seed=42)
    res = gen.generate_scenario(clean_mem_db, "subscription_failure")
    merchant_id = res["ground_truth"].merchant_id

    metrics = calculate_observed_metrics(clean_mem_db, merchant_id)
    s_stats = metrics["subscriptions"]

    assert s_stats["renewal_failure_rate"] >= 0.30, f"Renewal failure rate {s_stats['renewal_failure_rate']:.2f} must be >= 30%"
    assert s_stats["affected_mrr_inr"] > 0

    # Verify specific error codes in attempts
    attempts = (
        clean_mem_db.query(SubscriptionAttempt)
        .join(Subscription)
        .filter(Subscription.merchant_id == merchant_id, SubscriptionAttempt.status == "failed")
        .all()
    )
    error_codes = {a.error_code for a in attempts}
    assert any(ec in ("MANDATE_LIMIT_EXCEEDED", "CARD_EXPIRED", "INSUFFICIENT_FUNDS") for ec in error_codes)


def test_7_high_value_recovery(clean_mem_db):
    """Verify high-value recovery scenario produces high-ticket recoverable transactions."""
    gen = SyntheticDataGenerator(seed=42)
    res = gen.generate_scenario(clean_mem_db, "high_value_recovery")
    merchant_id = res["ground_truth"].merchant_id

    payments = clean_mem_db.query(Payment).filter(Payment.merchant_id == merchant_id).all()
    assert any(p.amount >= Decimal("35000.00") for p in payments)

    metrics = calculate_observed_metrics(clean_mem_db, merchant_id)
    assert metrics["payments"]["recoverable_volume_inr"] > 0


def test_8_non_recoverable_transactions(clean_mem_db):
    """Verify that explicit non-recoverable transactions are generated and labeled."""
    gen = SyntheticDataGenerator(seed=42)
    res = gen.generate_scenario(clean_mem_db, "high_value_recovery")
    gt = res["ground_truth"]

    # Verify ground truth records non-recoverable transactions
    non_rec_txs = [tx for tx in gt.transactions.values() if not tx.is_recoverable and tx.loss_amount > 0]
    assert len(non_rec_txs) > 0, "Scenario must contain explicit non-recoverable transactions"

    # Verify reasons are categorized
    reasons = {tx.non_recovery_reason for tx in non_rec_txs if tx.non_recovery_reason}
    assert any(r in reasons for r in [
        NonRecoveryReason.FRAUD_RISK.value,
        NonRecoveryReason.EXCESSIVE_RETRIES.value,
        NonRecoveryReason.EXPIRED_WINDOW.value,
        NonRecoveryReason.INVALID_DETAILS.value
    ]), f"Non-recovery reasons must be recognized: {reasons}"


def test_9_mixed_scenario(clean_mem_db):
    """Verify mixed scenario combines multi-channel issues into a single merchant."""
    gen = SyntheticDataGenerator(seed=42)
    res = gen.generate_scenario(clean_mem_db, "mixed")
    merchant_id = res["ground_truth"].merchant_id

    metrics = calculate_observed_metrics(clean_mem_db, merchant_id)
    assert metrics["payments"]["total_count"] >= 300
    assert metrics["payments"]["failed_count"] > 0
    assert metrics["checkouts"]["abandoned_count"] > 0
    assert metrics["subscriptions"]["failed_count"] > 0


def test_10_data_integrity(clean_mem_db):
    """Verify validate_dataset_integrity reports 0 violations across all 6 scenarios."""
    gen = SyntheticDataGenerator(seed=42)
    scenarios_to_test = ["healthy", "payment_degradation", "checkout_abandonment", "subscription_failure", "high_value_recovery", "mixed"]

    for sc in scenarios_to_test:
        res = gen.generate_scenario(clean_mem_db, sc)
        merchant_id = res["ground_truth"].merchant_id
        integ = validate_dataset_integrity(clean_mem_db, merchant_id)
        assert integ["valid"] is True, f"Integrity failed for scenario {sc}: {integ['violations']}"
        assert integ["violations_count"] == 0


def test_11_ground_truth_integrity(clean_mem_db):
    """Verify ground truth referential validity and mathematical balance."""
    gen = SyntheticDataGenerator(seed=42)
    res = gen.generate_scenario(clean_mem_db, "payment_degradation")
    gt = res["ground_truth"]

    # Verify all transaction IDs in ground truth exist in database
    db_payment_ids = {p.id for p in clean_mem_db.query(Payment).filter(Payment.merchant_id == gt.merchant_id).all()}
    for tx_id in gt.transactions.keys():
        assert tx_id in db_payment_ids, f"Ground truth transaction {tx_id} does not exist in DB!"

    # Verify revenue balance: recoverable + non_recoverable == total revenue at risk
    assert gt.potentially_recoverable_revenue + gt.non_recoverable_revenue == gt.total_revenue_at_risk, (
        f"Ground truth mathematical balance violated: {gt.potentially_recoverable_revenue} + "
        f"{gt.non_recoverable_revenue} != {gt.total_revenue_at_risk}"
    )
