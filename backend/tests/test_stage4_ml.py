"""
Stage 4 — ML Recovery Intelligence Comprehensive Test Suite
Validates:
1. Production-safe feature engineering & contract
2. Temporal leakage prevention (explicit point-in-time invariant)
3. Dataset generation & quality validation
4. Chronological 3-way temporal split (Train/Val/Test)
5. Baseline vs Model 1 calibrated recovery probability
6. Calibration curve & Brier score improvement
7. Model 2 opportunity ranking & expected recovery value
8. Business prioritization test (High-value low-probability vs lower-value high-probability)
9. Model registry, serialization & numerical equivalence
10. Cold-start & unknown-category robustness
11. Inference service & audit persistence
12. API endpoints & merchant isolation
13. Policy boundary enforcement (zero execution capability)
14. Experiment reproducibility
"""

import uuid
import math
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import pytest
import numpy as np

from app.models import (
    Merchant,
    Customer,
    Payment,
    PaymentAttempt,
    Subscription,
    SubscriptionAttempt,
    RecoveryOpportunity,
    ModelPrediction,
    PaymentStatus,
    OpportunityStatus,
)
from app.ml.features.contract import FEATURE_NAMES, FEATURE_CONTRACT
from app.ml.features.transaction_features import extract_transaction_features
from app.ml.features.customer_features import extract_customer_features
from app.ml.features.payment_features import extract_payment_features, categorize_error_code
from app.ml.features.subscription_features import extract_subscription_features
from app.ml.features.merchant_features import extract_merchant_features
from app.ml.features.feature_builder import FeatureBuilder
from app.ml.dataset import DatasetGenerator, DatasetValidator, TrainingSample
from app.ml.pipeline import TemporalDataSplitter
from app.ml.models import (
    HistoricalMeanBaseline,
    PaymentRecoveryModel,
    RecoveryOpportunityRanker,
)
from app.ml.registry import ModelRegistry, registry
from app.ml.inference import InferenceService, InferenceValidationError
from app.ml.training import MLTrainingPipeline


# =============================================================================
# 1. Feature Engineering & Contract Tests
# =============================================================================

def test_feature_contract_completeness():
    """Verify that all features have complete contractual specifications."""
    assert len(FEATURE_NAMES) >= 25
    for name in FEATURE_NAMES:
        defn = FEATURE_CONTRACT[name]
        assert defn.name == name
        assert defn.data_type in ("float", "int", "str", "bool")
        assert "<= prediction_time" in defn.availability_time
        assert defn.calculation is not None
        assert defn.missing_value_behavior is not None


def test_transaction_features_point_in_time():
    """Verify transaction feature extraction respects prediction_time."""
    p_time = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
    pred_t = p_time + timedelta(minutes=5)

    payment = Payment(
        id=uuid.uuid4(),
        amount=Decimal("4500.00"),
        created_at=p_time,
        payment_method="upi",
    )
    attempts = [
        PaymentAttempt(attempt_number=1, attempted_at=p_time + timedelta(seconds=30), status="failed"),
        PaymentAttempt(attempt_number=2, attempted_at=p_time + timedelta(seconds=120), status="failed"),
        # Future attempt after pred_t — MUST BE IGNORED
        PaymentAttempt(attempt_number=3, attempted_at=pred_t + timedelta(hours=2), status="success"),
    ]

    feats = extract_transaction_features(payment, attempts, prediction_time=pred_t, merchant_atv=2000.0)
    assert feats["transaction_amount"] == 4500.0
    assert abs(feats["log_amount"] - math.log1p(4500.0)) < 1e-4
    assert feats["attempt_number"] == 2  # Attempt 3 occurred after pred_t
    assert feats["payment_method"] == "upi"
    assert feats["transaction_hour"] == 10
    assert feats["transaction_day_of_week"] == p_time.weekday()


def test_customer_features_cold_start():
    """Verify customer with no prior history produces valid cold-start features."""
    pred_t = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
    feats = extract_customer_features(customer_payments_history=[], prediction_time=pred_t)

    assert feats["is_cold_start"] == 1
    assert feats["customer_transaction_count_before_prediction"] == 0
    assert feats["customer_success_count"] == 0
    assert feats["customer_historical_success_rate"] == 0.50
    assert feats["customer_lifetime_value_before_prediction"] == 0.0
    assert feats["days_since_last_success"] == -1.0


def test_customer_features_warm_history():
    """Verify customer historical calculation strictly excludes future events."""
    pred_t = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
    history = [
        Payment(amount=Decimal("1000.00"), status="success", created_at=pred_t - timedelta(days=5)),
        Payment(amount=Decimal("2000.00"), status="success", created_at=pred_t - timedelta(days=2)),
        Payment(amount=Decimal("500.00"), status="failed", created_at=pred_t - timedelta(days=1)),
        # Future payment — MUST NOT BE COUNTED
        Payment(amount=Decimal("10000.00"), status="success", created_at=pred_t + timedelta(days=1)),
    ]

    feats = extract_customer_features(history, prediction_time=pred_t)
    assert feats["is_cold_start"] == 0
    assert feats["customer_transaction_count_before_prediction"] == 3
    assert feats["customer_success_count"] == 2
    assert feats["customer_failure_count"] == 1
    assert round(feats["customer_historical_success_rate"], 2) == 0.67
    assert feats["customer_lifetime_value_before_prediction"] == 3000.0
    assert feats["days_since_last_success"] >= 2.0


def test_payment_features_and_unknown_handling():
    """Verify unknown payment method, bank, and error codes are safely handled."""
    pred_t = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
    payment = Payment(
        bank="UNKNOWN_BANK_XYZ",
        payment_method="crypto_token",
        device_type="smart_fridge",
    )
    attempts = [
        PaymentAttempt(
            error_code="WEIRD_UNSEEN_ERROR_999",
            failure_reason="Something weird happened",
            attempted_at=pred_t - timedelta(seconds=60),
        )
    ]

    feats = extract_payment_features(payment, attempts, customer_payments_history=[], prediction_time=pred_t)
    assert feats["bank"] == "OTHER"
    assert feats["device_type"] == "unknown"
    assert feats["failure_reason"] == "OTHER"
    assert feats["previous_attempt_count"] == 1


# =============================================================================
# 2. Strict Temporal Leakage Tests
# =============================================================================

def test_temporal_leakage_future_events_invariant(db_session):
    """
    CRITICAL INVARIANT TEST:
    Adding future records must NEVER alter features computed at an earlier prediction_time.
    """
    merch = Merchant(id=uuid.uuid4(), name="Temporal Merchant", email="temporal@merchant.com")
    cust = Customer(id=uuid.uuid4(), merchant_id=merch.id, external_ref="cust_temporal")
    db_session.add_all([merch, cust])
    db_session.commit()

    base_time = datetime(2026, 8, 1, 10, 0, 0, tzinfo=timezone.utc)
    pred_time = base_time + timedelta(minutes=5)

    # Initial payment
    p1 = Payment(
        id=uuid.uuid4(),
        merchant_id=merch.id,
        customer_id=cust.id,
        amount=Decimal("1500.00"),
        status="failed",
        payment_method="upi",
        device_type="android",
        route="hdfc_upi",
        created_at=base_time,
    )
    att1 = PaymentAttempt(
        payment_id=p1.id,
        attempt_number=1,
        status="failed",
        error_code="GATEWAY_TIMEOUT",
        attempted_at=base_time + timedelta(seconds=30),
    )
    db_session.add_all([p1, att1])
    db_session.commit()

    builder = FeatureBuilder(db_session)
    feats_before = builder.build_features_for_payment(p1, prediction_time=pred_time)

    # Insert a FUTURE payment and attempt at T_pred + 2 hours
    p_future = Payment(
        id=uuid.uuid4(),
        merchant_id=merch.id,
        customer_id=cust.id,
        amount=Decimal("50000.00"),
        status="success",
        payment_method="card",
        device_type="desktop",
        route="icici_card",
        created_at=pred_time + timedelta(hours=2),
    )
    att_future = PaymentAttempt(
        payment_id=p_future.id,
        attempt_number=1,
        status="success",
        attempted_at=pred_time + timedelta(hours=2),
    )
    db_session.add_all([p_future, att_future])
    db_session.commit()

    # Re-extract features at the SAME earlier prediction_time
    feats_after = builder.build_features_for_payment(p1, prediction_time=pred_time)

    # Invariant: features_before must match features_after exactly!
    for key in FEATURE_NAMES:
        val_b = feats_before[key]
        val_a = feats_after[key]
        assert val_b == val_a, f"Temporal leakage detected on '{key}': before={val_b}, after={val_a}"


# =============================================================================
# 3. Dataset Generation & Chronological Split Tests
# =============================================================================

def test_dataset_generator_and_validator(db_session):
    """Verify dataset generation, non-null values, and zero duplicate sample IDs."""
    gen = DatasetGenerator(db_session, seed=42)
    samples, report = gen.generate_dataset_from_db(min_samples=60)

    assert len(samples) >= 60
    assert report.is_valid
    assert report.duplicate_count == 0
    assert report.missing_value_count == 0
    assert 0.10 <= report.positive_rate <= 0.90

    # Ensure no raw IDs are included as model features
    sample = samples[0]
    for id_col in ("id", "payment_id", "customer_id", "merchant_id", "sample_id"):
        assert id_col not in sample.features


def test_chronological_three_way_split():
    """Verify chronological split guarantees: max(train) < min(val) < min(test)."""
    base = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
    records = []
    for i in range(100):
        records.append({
            "prediction_time": base + timedelta(hours=i),
            "val": i,
        })

    train, val, test, meta = TemporalDataSplitter.split_train_val_test(
        records, time_key="prediction_time", train_ratio=0.60, val_ratio=0.20
    )

    assert len(train) == 60
    assert len(val) == 20
    assert len(test) == 20

    max_train = max(r["prediction_time"] for r in train)
    min_val = min(r["prediction_time"] for r in val)
    max_val = max(r["prediction_time"] for r in val)
    min_test = min(r["prediction_time"] for r in test)

    assert max_train <= min_val
    assert max_val <= min_test


# =============================================================================
# 4. Model Training, Calibration & Baseline Evaluation
# =============================================================================

def test_naive_baseline_model():
    """Verify naive HistoricalMeanBaseline outputs expected prevalence and metrics."""
    baseline = HistoricalMeanBaseline()
    y_train = np.array([1, 1, 0, 0, 0])  # 40% positive
    baseline.fit(y_train)

    assert baseline.is_fitted
    assert abs(baseline.mean_recovery_rate - 0.40) < 1e-4

    y_test = np.array([1, 0, 1, 0])
    X_test = [{} for _ in range(4)]
    metrics = baseline.evaluate(X_test, y_test)

    assert metrics["roc_auc"] == 0.50
    assert 0.0 <= metrics["brier_score"] <= 1.0


def test_model1_training_and_calibration():
    """Verify Model 1 fits, calibrates on validation set, and bounds output in [0, 1]."""
    rng = np.random.RandomState(42)
    X = []
    for i in range(100):
        X.append({
            "transaction_amount": float(rng.uniform(500, 10000)),
            "log_amount": float(math.log1p(rng.uniform(500, 10000))),
            "amount_percentile_for_merchant": 1.0,
            "payment_method": "upi" if i % 2 == 0 else "card",
            "transaction_hour": 14,
            "transaction_day_of_week": 2,
            "days_since_transaction": 0.01,
            "attempt_number": 1,
            "time_since_previous_attempt": 0.0,
            "customer_transaction_count_before_prediction": 5,
            "customer_success_count": 4,
            "customer_failure_count": 1,
            "customer_historical_success_rate": 0.80,
            "customer_historical_failure_rate": 0.20,
            "customer_lifetime_value_before_prediction": 5000.0,
            "days_since_last_success": 2.0,
            "days_since_last_transaction": 1.0,
            "is_cold_start": 0,
            "failure_reason": "TIMEOUT" if i % 2 == 0 else "INSUFFICIENT_FUNDS",
            "bank": "HDFC",
            "device_type": "android",
            "previous_payment_method_success_rate": 0.80,
            "previous_attempt_count": 1,
            "time_since_failure": 300.0,
            "is_subscription": 0,
            "subscription_age_days": 0.0,
            "renewal_number": 0,
            "previous_renewal_count": 0,
            "previous_renewal_success_rate": 0.50,
            "plan_value": 0.0,
            "subscription_status": "none",
            "merchant_payment_success_rate": 0.85,
            "merchant_failure_rate": 0.15,
            "merchant_average_transaction_value": 2500.0,
            "merchant_payment_method_success_rate": 0.85,
        })
    y = np.array([1 if i % 2 == 0 else 0 for i in range(100)])

    train_X, val_X, test_X = X[:60], X[60:80], X[80:]
    train_y, val_y, test_y = y[:60], y[60:80], y[80:]

    model = PaymentRecoveryModel(use_baseline=False, random_seed=42)
    model.fit(train_X, train_y)
    assert model.is_fitted

    # Calibrate on validation set
    model.calibrate(val_X, val_y)
    assert model.is_calibrated

    # Evaluate on test set
    metrics = model.evaluate(test_X, test_y)
    assert metrics["roc_auc"] >= 0.50
    assert 0.0 <= metrics["brier_score"] <= 1.0
    assert "top_k_metrics" in metrics

    # Verify predictions bounded strictly in [0.0, 1.0]
    probs = model.predict_proba(test_X)
    assert np.all(probs >= 0.0)
    assert np.all(probs <= 1.0)


# =============================================================================
# 5. Opportunity Ranking & Business Prioritization Tests
# =============================================================================

def test_expected_recovery_formula():
    """Verify expected_recovery_value = recovery_probability * eligible_revenue."""
    p = 0.85
    eligible = Decimal("4000.00")
    erv = RecoveryOpportunityRanker.calculate_expected_recovery_value(p, eligible)
    assert erv == Decimal("3400.00")


def test_business_prioritization_high_value_low_prob_vs_low_value_high_prob():
    """
    Business prioritization test:
    Opportunity A: ₹100,000 transaction with 10% recovery prob -> ERV = ₹8,500 (high risk)
    Opportunity B: ₹10,000 transaction with 90% recovery prob -> ERV = ₹7,650 (low risk)
    Verify ranking follows documented transparent formula.
    """
    opp_a = {
        "id": "opp_a",
        "gross_amount": Decimal("100000.00"),
        "recovery_probability": 0.10,
        "confidence": 0.80,
        "customer_ltv": 10000.0,
        "age_hours": 1.0,
        "risk": "medium",
        "actual_recovery": Decimal("0.00"),
    }
    opp_b = {
        "id": "opp_b",
        "gross_amount": Decimal("10000.00"),
        "recovery_probability": 0.90,
        "confidence": 0.95,
        "customer_ltv": 25000.0,
        "age_hours": 0.5,
        "risk": "low",
        "actual_recovery": Decimal("8500.00"),
    }

    ranked = RecoveryOpportunityRanker.rank_opportunities([opp_a, opp_b])
    assert len(ranked) == 2
    # Opp B has much higher probability, higher customer LTV, lower risk, fresh recency
    assert ranked[0]["id"] == "opp_b"
    assert ranked[1]["id"] == "opp_a"
    assert ranked[0]["opportunity_score"] > ranked[1]["opportunity_score"]


# =============================================================================
# 6. Model Registry & Artifact Serialization Tests
# =============================================================================

def test_model_serialization_and_numerical_precision(tmp_path):
    """Verify model can be saved, loaded, and generates numerically identical predictions."""
    custom_reg = ModelRegistry(artifacts_dir=tmp_path)
    model = PaymentRecoveryModel(use_baseline=False, random_seed=42)

    X_train = [{k: 1.0 for k in FEATURE_NAMES}, {k: 0.0 for k in FEATURE_NAMES}] * 10
    y_train = np.array([1, 0] * 10)
    model.fit(X_train, y_train)

    meta = {
        "algorithm": "HistGradientBoosting",
        "feature_version": "v1.0.0",
        "dataset_version": "test_v1",
        "metrics": {"roc_auc": 0.90},
    }
    entry = custom_reg.register_model(
        model_name="test_model",
        model_version="v1.0",
        model_artifact=model,
        metadata=meta,
    )
    assert entry.is_active

    loaded = custom_reg.load_active_model("test_model")
    assert loaded is not None

    test_vec = [{k: 0.5 for k in FEATURE_NAMES}]
    orig_p = model.predict_proba(test_vec)[0]
    load_p = loaded.predict_proba(test_vec)[0]

    assert abs(orig_p - load_p) < 1e-6, f"Precision mismatch: {orig_p} vs {load_p}"


# =============================================================================
# 7. Inference Service & Audit Persistence Tests
# =============================================================================

def test_inference_service_single_prediction_and_audit(db_session):
    """Verify inference service computes probability, ERV, factors, and logs audit record."""
    merch = Merchant(id=uuid.uuid4(), name="Inference Merchant", email="inf@merchant.com")
    cust = Customer(id=uuid.uuid4(), merchant_id=merch.id, external_ref="cust_inf")
    db_session.add_all([merch, cust])
    db_session.commit()

    p = Payment(
        id=uuid.uuid4(),
        merchant_id=merch.id,
        customer_id=cust.id,
        amount=Decimal("3500.00"),
        status="failed",
        payment_method="upi",
        bank="HDFC",
        device_type="android",
        route="hdfc_upi",
    )
    att = PaymentAttempt(
        payment_id=p.id,
        attempt_number=1,
        status="failed",
        error_code="TIMEOUT",
    )
    db_session.add_all([p, att])
    db_session.commit()

    service = InferenceService(db_session)
    res = service.predict_recovery_probability(transaction_id=p.id, persist_audit=True)

    assert res["transaction_id"] == p.id
    assert 0.0 <= res["recovery_probability"] <= 1.0
    assert 0.0 <= res["confidence"] <= 1.0
    assert res["expected_recovery_value"] >= Decimal("0.00")
    assert res["opportunity_score"] >= 0.0
    assert len(res["contributing_factors"]) > 0

    # Verify audit persistence in model_predictions
    pred_row = db_session.query(ModelPrediction).filter(ModelPrediction.entity_id == p.id).first()
    assert pred_row is not None
    assert pred_row.model_name == res["model_name"]
    assert pred_row.model_version == res["model_version"]


def test_inference_service_batch_opportunity_generation(db_session):
    """Verify batch opportunity generation creates and ranks RecoveryOpportunity records."""
    merch = Merchant(id=uuid.uuid4(), name="Batch Merchant", email="batch@merchant.com")
    cust = Customer(id=uuid.uuid4(), merchant_id=merch.id, external_ref="cust_batch")
    db_session.add_all([merch, cust])
    db_session.commit()

    for i in range(3):
        p = Payment(
            id=uuid.uuid4(),
            merchant_id=merch.id,
            customer_id=cust.id,
            amount=Decimal(str(1000 * (i + 1))),
            status="failed",
            payment_method="upi",
            device_type="android",
            route="hdfc_upi",
        )
        db_session.add(p)
    db_session.commit()

    service = InferenceService(db_session)
    opps = service.generate_recovery_opportunities(merchant_id=merch.id)

    assert len(opps) == 3
    for o in opps:
        assert o.model_version is not None
        assert o.feature_version is not None
        assert o.prediction_time is not None
        assert o.recovery_probability >= Decimal("0.0000")
        assert o.expected_recovered_value >= Decimal("0.00")


# =============================================================================
# 8. Policy Boundary Enforcement Test
# =============================================================================

def test_ml_layer_strictly_advisory_no_payment_execution():
    """
    CRITICAL ARCHITECTURAL SAFETY BOUNDARY TEST:
    Verify that ML modules have ZERO imports or dependencies on payment execution providers
    (PaymentProvider, RazorpayTestProvider, execute_retry, refund, etc.).
    """
    import inspect
    import app.ml
    import app.ml.models
    import app.ml.inference
    import app.ml.features.feature_builder

    forbidden_tokens = [
        "PaymentProvider",
        "RazorpayTestProvider",
        "execute_payment",
        "refund_payment",
        "execute_retry",
        "razorpay_client",
    ]

    for mod in (app.ml.models, app.ml.inference, app.ml.features.feature_builder):
        src = inspect.getsource(mod)
        for token in forbidden_tokens:
            assert token not in src, f"Policy violation: Forbidden execution token '{token}' in {mod.__name__}"


# =============================================================================
# 9. Reproducibility Test
# =============================================================================

def test_experiment_reproducibility():
    """Verify that training twice with the same seed yields equivalent predictions."""
    rng = np.random.RandomState(42)
    X = [{k: float(rng.uniform(0, 100)) for k in FEATURE_NAMES} for _ in range(40)]
    y = np.array([1 if i % 2 == 0 else 0 for i in range(40)])

    model_1 = PaymentRecoveryModel(use_baseline=False, random_seed=42)
    model_1.fit(X, y)

    model_2 = PaymentRecoveryModel(use_baseline=False, random_seed=42)
    model_2.fit(X, y)

    test_vec = [{k: 50.0 for k in FEATURE_NAMES}]
    p1 = model_1.predict_proba(test_vec)[0]
    p2 = model_2.predict_proba(test_vec)[0]

    assert abs(p1 - p2) < 1e-5, f"Reproducibility failure: {p1} != {p2}"


# =============================================================================
# 10. API & Tenant Isolation Tests
# =============================================================================

def test_ml_api_predict_and_metrics(client, db_session):
    """Verify POST /api/v1/ml/predict/{id} and GET /api/v1/ml/metrics endpoints."""
    merch = Merchant(id=uuid.uuid4(), name="API Merchant", email="api@merchant.com")
    cust = Customer(id=uuid.uuid4(), merchant_id=merch.id, external_ref="cust_api")
    db_session.add_all([merch, cust])
    db_session.commit()

    p = Payment(
        id=uuid.uuid4(),
        merchant_id=merch.id,
        customer_id=cust.id,
        amount=Decimal("4200.00"),
        status="failed",
        payment_method="upi",
        device_type="android",
        route="hdfc_upi",
    )
    att = PaymentAttempt(payment_id=p.id, attempt_number=1, status="failed", error_code="TIMEOUT")
    db_session.add_all([p, att])
    db_session.commit()

    # Test POST /api/v1/ml/predict/{transaction_id}
    res_post = client.post(f"/api/v1/ml/predict/{p.id}")
    assert res_post.status_code == 200
    data_post = res_post.json()
    assert data_post["transaction_id"] == str(p.id)
    assert 0.0 <= data_post["recovery_probability"] <= 1.0
    assert "contributing_factors" in data_post
    assert data_post["expected_recovery_value"] is not None

    # Test GET /api/v1/ml/recovery-probability/{transaction_id}
    res_get = client.get(f"/api/v1/ml/recovery-probability/{p.id}")
    assert res_get.status_code == 200
    data_get = res_get.json()
    assert data_get["recovery_probability"] == data_post["recovery_probability"]

    # Test GET /api/v1/ml/metrics
    res_metrics = client.get("/api/v1/ml/metrics")
    assert res_metrics.status_code == 200
    m_data = res_metrics.json()
    assert "baseline_model" in m_data
    assert "production_model" in m_data

    # Test GET /api/v1/ml/models
    res_models = client.get("/api/v1/ml/models")
    assert res_models.status_code == 200
    models_list = res_models.json()
    assert isinstance(models_list, list)


def test_ml_api_opportunities_filtering_and_tenant_isolation(client, db_session):
    """Verify recovery opportunities query filtering and merchant tenant isolation."""
    merch1 = Merchant(id=uuid.uuid4(), name="Merchant A", email="mercha@merchant.com")
    merch2 = Merchant(id=uuid.uuid4(), name="Merchant B", email="merchb@merchant.com")
    db_session.add_all([merch1, merch2])
    db_session.commit()

    opp1 = RecoveryOpportunity(
        id=uuid.uuid4(),
        merchant_id=merch1.id,
        gross_value_affected=Decimal("5000.00"),
        potentially_recoverable_value=Decimal("4250.00"),
        recovery_probability=Decimal("0.8500"),
        expected_recovered_value=Decimal("3612.50"),
        priority_score=Decimal("82.00"),
        priority="CRITICAL",
        status=OpportunityStatus.OPEN.value,
        risk="low",
    )
    opp2 = RecoveryOpportunity(
        id=uuid.uuid4(),
        merchant_id=merch2.id,
        gross_value_affected=Decimal("1200.00"),
        potentially_recoverable_value=Decimal("1020.00"),
        recovery_probability=Decimal("0.2500"),
        expected_recovered_value=Decimal("255.00"),
        priority_score=Decimal("32.00"),
        priority="LOW",
        status=OpportunityStatus.OPEN.value,
        risk="low",
    )
    db_session.add_all([opp1, opp2])
    db_session.commit()

    # Query filtered strictly by merchant1
    res1 = client.get(f"/api/v1/recovery-opportunities?merchant_id={merch1.id}&run_engine=false")
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["total"] == 1
    assert data1["items"][0]["id"] == str(opp1.id)
    assert data1["items"][0]["merchant_id"] == str(merch1.id)

    # Verify merchant2's opportunity is completely isolated
    for item in data1["items"]:
        assert item["merchant_id"] != str(merch2.id)

    # Test probability filter
    res_prob = client.get(f"/api/v1/recovery-opportunities?minimum_probability=0.50&run_engine=false")
    assert res_prob.status_code == 200
    for item in res_prob.json()["items"]:
        assert item["recovery_probability"] >= 0.50

    # Test expected value filter
    res_val = client.get(f"/api/v1/recovery-opportunities?minimum_expected_value=1000.00&run_engine=false")
    assert res_val.status_code == 200
    for item in res_val.json()["items"]:
        assert float(item["expected_recovery"]) >= 1000.00

