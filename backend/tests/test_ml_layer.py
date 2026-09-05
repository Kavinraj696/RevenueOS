import uuid
from decimal import Decimal
import pytest
import numpy as np

from app.models import (
    Merchant,
    Payment,
    Customer,
    PaymentAttempt,
    PaymentStatus,
    ModelPrediction,
)
from app.ml.pipeline import (
    PaymentFeatureExtractor,
    TemporalDataSplitter,
)
from app.ml.models import (
    PaymentRecoveryModel,
    RevenueAnomalyDetector,
    RecoveryOpportunityRanker,
)
from app.ml.training import (
    MLTrainingPipeline,
    get_recovery_model,
    get_anomaly_detector,
    METRICS_PATH,
)
from app.synthetic.generator import SyntheticDataGenerator

def test_feature_extraction_and_temporal_split(db_session):
    """
    Test feature extraction and leak-free chronological data splitting.
    Verifies that all training timestamps occur prior to testing timestamps.
    """
    gen = SyntheticDataGenerator(seed=42)
    gen.generate_all(db_session)

    payments = db_session.query(Payment).all()
    assert len(payments) > 50

    records = PaymentFeatureExtractor.build_dataset_from_payments(payments)
    assert len(records) > 0
    sample = records[0]
    assert "log_amount" in sample
    assert "payment_method" in sample
    assert "bank" in sample
    assert "device_type" in sample
    assert "error_code_category" in sample

    # Test chronological splitting
    train_recs, test_recs = TemporalDataSplitter.split(records, time_key="created_at", train_ratio=0.75)
    assert len(train_recs) > 0
    assert len(test_recs) > 0
    assert len(train_recs) + len(test_recs) == len(records)

    # Verify zero forward-looking leakage: max(train) <= min(test)
    max_train_time = max(r["created_at"] for r in train_recs)
    min_test_time = min(r["created_at"] for r in test_recs)
    assert max_train_time <= min_test_time, "Train timestamps must precede Test timestamps"

def test_model1_training_and_baseline_comparison(db_session):
    """
    Test Model 1 end-to-end training pipeline, real metrics calculation,
    baseline vs improved comparison, and model persistence.
    """
    pipeline = MLTrainingPipeline(db_session)
    summary = pipeline.train_all()

    assert "baseline_model" in summary
    assert "improved_model" in summary
    assert "comparison" in summary

    base_metrics = summary["baseline_model"]["metrics"]
    prod_metrics = summary["improved_model"]["metrics"]

    # Real metrics check: precision, recall, f1, roc_auc
    for m in (base_metrics, prod_metrics):
        assert "precision" in m
        assert "recall" in m
        assert "f1" in m
        assert "roc_auc" in m
        assert 0.0 <= m["roc_auc"] <= 1.0
        assert 0.0 <= m["f1"] <= 1.0

    # Ensure improved model is competitive
    assert prod_metrics["roc_auc"] >= 0.50

    # Test singleton loader loads fitted model
    loaded_model = get_recovery_model(db_session)
    assert loaded_model.is_fitted

    # Test single inference
    sample_features = {
        "log_amount": 8.0,
        "attempt_count": 1,
        "customer_ltv": 12000.0,
        "hour_of_day": 19,
        "day_of_week": 3,
        "payment_method": "upi",
        "bank": "HDFC",
        "device_type": "android",
        "customer_risk_segment": "low",
        "error_code_category": "TIMEOUT",
    }
    prob, conf = loaded_model.predict_single(sample_features)
    assert 0.0 <= prob <= 1.0
    assert 0.5 <= conf <= 1.0

def test_model2_anomaly_detector(db_session):
    """
    Test Model 2 Revenue Anomaly Detector on normal vs severe degradation windows.
    """
    detector = get_anomaly_detector(db_session)
    
    # Train on historical baseline window with realistic natural variance
    rng = np.random.default_rng(42)
    vols = rng.normal(100, 10, 50)
    fails = rng.normal(0.03, 0.005, 50)
    gross = rng.normal(250000, 20000, 50)
    rars = gross * fails
    train_data = [
        {"volume": float(vols[i]), "failure_rate": float(fails[i]), "gross_amount": float(gross[i]), "revenue_at_risk": float(rars[i])}
        for i in range(50)
    ]
    detector.fit(train_data)

    # Normal window
    is_ano_norm, score_norm, z_norm = detector.predict_anomaly({
        "volume": 98.0, "failure_rate": 0.032, "gross_amount": 245000.0, "revenue_at_risk": 7840.0
    })

    # Severe failure rate spike (e.g. 72% failure outage)
    is_ano_spike, score_spike, z_spike = detector.predict_anomaly({
        "volume": 120.0, "failure_rate": 0.72, "gross_amount": 300000.0, "revenue_at_risk": 180000.0
    })

    assert score_spike > score_norm
    assert is_ano_spike is True or score_spike >= 0.50
    assert z_spike > z_norm

def test_model3_opportunity_ranking_and_5_revenue_dimensions():
    """
    Test Model 3 ranking logic and strict mathematical separation of all 5 revenue dimensions:
    1. Gross Affected Revenue
    2. Revenue at Risk (RAR)
    3. Potentially Recoverable Revenue
    4. Expected Recovery
    5. Actual Recovery
    """
    gross_val = Decimal("100000.00")
    p_rec = 0.75
    conf = 0.90

    breakdown = RecoveryOpportunityRanker.calculate_revenue_breakdown(
        gross_amount=gross_val,
        recovery_probability=p_rec,
        confidence=conf,
        is_checkout=False,
        actual_recovered=Decimal("15000.00")
    )

    # Mathematical hierarchy verification: Gross >= RAR >= Potentially Recoverable >= Expected Recovery
    assert breakdown["gross_affected_revenue"] == Decimal("100000.00")
    assert breakdown["revenue_at_risk"] == Decimal("85000.00")  # (1 - 0.15) * 100k
    assert breakdown["potentially_recoverable_revenue"] == Decimal("72250.00")  # 0.85 * 85k
    # Expected: 72250 * 0.75 * 0.90 = 48768.75
    assert breakdown["expected_recovery"] == Decimal("48768.75")
    assert breakdown["actual_recovery"] == Decimal("15000.00")

    # Test ranking of multiple opportunities
    opps = [
        {"gross_amount": Decimal("10000.00"), "recovery_probability": 0.20, "confidence": 0.80},
        {"gross_amount": Decimal("80000.00"), "recovery_probability": 0.85, "confidence": 0.95},
        {"gross_amount": Decimal("30000.00"), "recovery_probability": 0.50, "confidence": 0.85},
    ]
    ranked = RecoveryOpportunityRanker.rank_opportunities(opps)
    
    assert len(ranked) == 3
    assert ranked[0]["priority_rank"] == 1
    assert ranked[1]["priority_rank"] == 2
    assert ranked[2]["priority_rank"] == 3
    # First ranked item must have highest expected recovery
    assert ranked[0]["expected_recovery"] > ranked[1]["expected_recovery"]
    assert ranked[1]["expected_recovery"] > ranked[2]["expected_recovery"]

def test_api_recovery_probability_endpoint(client, db_session, seeded_db):
    """
    Test GET /api/ml/recovery-probability/{transaction_id}
    Verifies inference response, fields, and ModelPrediction DB audit persistence.
    """
    failed_payment = db_session.query(Payment).filter(Payment.status == PaymentStatus.FAILED.value).first()
    assert failed_payment is not None

    res = client.get(f"/api/ml/recovery-probability/{failed_payment.id}")
    assert res.status_code == 200
    data = res.json()

    assert data["transaction_id"] == str(failed_payment.id)
    assert data["model_name"] == "payment_recovery_probability"
    assert "model_version" in data
    assert 0.0 <= data["recovery_probability"] <= 1.0
    assert 0.0 <= data["confidence"] <= 1.0
    assert data["input_reference"] == f"payment:{failed_payment.id}"
    assert "timestamp" in data
    assert "input_features" in data

    # Verify audit persistence in model_predictions table
    pred_row = db_session.query(ModelPrediction).filter(
        ModelPrediction.entity_id == failed_payment.id
    ).first()
    assert pred_row is not None
    assert pred_row.model_name == "payment_recovery_probability"
    assert pred_row.input_reference == f"payment:{failed_payment.id}"

    # Verify 404 for non-existent transaction
    bad_res = client.get(f"/api/ml/recovery-probability/{uuid.uuid4()}")
    assert bad_res.status_code == 404

def test_api_recovery_opportunities_endpoint(client, seeded_db):
    """
    Test GET /api/recovery-opportunities
    Verifies ranked opportunities list and 5 distinct revenue dimensions.
    """
    res = client.get("/api/recovery-opportunities")
    assert res.status_code == 200
    data = res.json()

    assert "total" in data
    assert "total_gross_affected" in data
    assert "total_revenue_at_risk" in data
    assert "total_potentially_recoverable" in data
    assert "total_expected_recovery" in data
    assert "total_actual_recovery" in data
    assert "items" in data
    assert len(data["items"]) > 0

    first_opp = data["items"][0]
    assert first_opp["priority_rank"] == 1
    assert "gross_affected_revenue" in first_opp
    assert "revenue_at_risk" in first_opp
    assert "potentially_recoverable_revenue" in first_opp
    assert "expected_recovery" in first_opp
    assert "actual_recovery" in first_opp
    assert "suggested_action" in first_opp
    assert "description" in first_opp

    # Monotonicity check on priority score
    for i in range(len(data["items"]) - 1):
        assert float(data["items"][i]["priority_score"]) >= float(data["items"][i+1]["priority_score"])
