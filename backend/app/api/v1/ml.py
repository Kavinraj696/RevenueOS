import uuid
import json
from decimal import Decimal
from typing import Dict, Any, Optional
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import Payment, ModelPrediction
from app.schemas.ml import RecoveryProbabilityResponse, MLMetricsResponse
from app.ml.pipeline import PaymentFeatureExtractor
from app.ml.training import get_recovery_model, METRICS_PATH, MLTrainingPipeline

router = APIRouter()

@router.get("/recovery-probability/{transaction_id}", response_model=RecoveryProbabilityResponse)
def get_payment_recovery_probability(
    transaction_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    Predict the probability that a failed transaction will be successfully recovered.
    Runs Model 1 inference and logs the prediction audit record into model_predictions.
    """
    payment = db.query(Payment).filter(Payment.id == transaction_id).first()
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction with id {transaction_id} not found"
        )

    # 1. Feature Extraction
    features = PaymentFeatureExtractor.extract_from_payment(payment)

    # 2. Model Inference
    model = get_recovery_model(db)
    prob, conf = model.predict_single(features)

    # 3. Store Prediction Audit Record
    now_utc = datetime.now(timezone.utc)
    input_ref = f"payment:{payment.id}"
    pred_dec = Decimal(str(round(prob, 4)))
    conf_dec = Decimal(str(round(conf, 4)))

    # Serializable features for JSON column
    serializable_features = {
        k: (v.isoformat() if isinstance(v, datetime) else v)
        for k, v in features.items()
    }

    prediction_record = ModelPrediction(
        id=uuid.uuid4(),
        model_name=model.MODEL_NAME,
        model_version=model.MODEL_VERSION,
        entity_type="payment",
        entity_id=payment.id,
        input_features_json=serializable_features,
        prediction=pred_dec,
        confidence=conf_dec,
        input_reference=input_ref,
    )
    db.add(prediction_record)
    db.commit()

    return RecoveryProbabilityResponse(
        transaction_id=payment.id,
        model_name=model.MODEL_NAME,
        model_version=model.MODEL_VERSION,
        prediction=pred_dec,
        recovery_probability=prob,
        confidence=conf,
        input_reference=input_ref,
        input_features=serializable_features,
        timestamp=now_utc
    )

@router.get("/metrics", response_model=Dict[str, Any])
def get_ml_metrics(db: Session = Depends(get_db)):
    """
    Retrieve real evaluation metrics comparing the baseline model
    against the improved production model.
    """
    if not METRICS_PATH.exists():
        pipeline = MLTrainingPipeline(db)
        pipeline.train_all()

    with open(METRICS_PATH, "r") as f:
        metrics_data = json.load(f)
    return metrics_data
