import uuid
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional
from pydantic import BaseModel, ConfigDict, Field

class RecoveryProbabilityResponse(BaseModel):
    transaction_id: uuid.UUID
    model_name: str
    model_version: str
    prediction: Decimal = Field(..., description="Binary recovery forecast or rounded probability")
    recovery_probability: float = Field(..., description="Continuous recovery probability between 0 and 1")
    confidence: float = Field(..., description="Model confidence score between 0 and 1")
    input_reference: str = Field(..., description="Entity identifier e.g. payment:<id>")
    input_features: Dict[str, Any]
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)

class MLMetricsResponse(BaseModel):
    training_timestamp: str
    train_samples: int
    test_samples: int
    baseline_model: Dict[str, Any]
    improved_model: Dict[str, Any]
    comparison: Dict[str, Any]
