import uuid
import json
from decimal import Decimal
from typing import Dict, Any, Optional, List
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models import Payment, ModelPrediction
from app.schemas.ml import RecoveryProbabilityResponse, MLMetricsResponse
from app.ml.inference import InferenceService
from app.ml.registry import registry
from app.ml.training import METRICS_PATH, MLTrainingPipeline

router = APIRouter()


@router.post("/predict/{transaction_id}", response_model=RecoveryProbabilityResponse)
def predict_transaction_recovery(
    transaction_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """
    POST endpoint for Phase 26 ML Recovery Probability Prediction.
    Executes point-in-time inference via InferenceService and logs audit record.
    """
    inference_service = InferenceService(db)
    try:
        res = inference_service.predict_recovery_probability(
            transaction_id=transaction_id,
            persist_audit=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Inference error: {e}")

    return RecoveryProbabilityResponse(
        transaction_id=res["transaction_id"],
        model_name=res["model_name"],
        model_version=res["model_version"],
        prediction=Decimal(str(round(res["recovery_probability"], 4))),
        recovery_probability=res["recovery_probability"],
        confidence=res["confidence"],
        input_reference=f"payment:{res['transaction_id']}",
        input_features=res["input_features"],
        timestamp=res["created_at"],
        expected_recovery_value=res["expected_recovery_value"],
        opportunity_score=res["opportunity_score"],
        contributing_factors=res["contributing_factors"],
    )


@router.get("/recovery-probability/{transaction_id}", response_model=RecoveryProbabilityResponse)
def get_payment_recovery_probability(
    transaction_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """
    GET endpoint for ML recovery probability prediction.
    Maintains full backward compatibility while using InferenceService.
    """
    return predict_transaction_recovery(transaction_id=transaction_id, db=db)


@router.get("/metrics", response_model=Dict[str, Any])
def get_ml_metrics(db: Session = Depends(get_db)):
    """
    Retrieve real evaluation metrics comparing the naive baseline
    against Model 1 (calibrated) and Model 2 (opportunity ranking).
    """
    if not METRICS_PATH.exists():
        pipeline = MLTrainingPipeline(db)
        pipeline.train_all()

    with open(METRICS_PATH, "r") as f:
        metrics_data = json.load(f)
    return metrics_data


@router.get("/models", response_model=List[Dict[str, Any]])
def list_registered_models():
    """
    List all registered models, versions, active status, and evaluation summaries.
    """
    return registry.list_models()
