"""
RevenueOS ML Package: Feature Engineering, Model Training, Evaluation, Registry, and Inference.
"""

from app.ml.pipeline import (
    PaymentFeatureExtractor,
    TemporalDataSplitter,
)
from app.ml.models import (
    HistoricalMeanBaseline,
    PaymentRecoveryModel,
    RevenueAnomalyDetector,
    RecoveryOpportunityRanker,
)
from app.ml.training import (
    MLTrainingPipeline,
    get_recovery_model,
    get_anomaly_detector,
)
from app.ml.features import (
    FeatureBuilder,
    FEATURE_CONTRACT,
    FEATURE_NAMES,
)
from app.ml.registry import (
    ModelRegistry,
    registry,
)
from app.ml.inference import (
    InferenceService,
)
from app.ml.dataset import (
    DatasetGenerator,
    DatasetValidator,
)

__all__ = [
    "PaymentFeatureExtractor",
    "TemporalDataSplitter",
    "HistoricalMeanBaseline",
    "PaymentRecoveryModel",
    "RevenueAnomalyDetector",
    "RecoveryOpportunityRanker",
    "MLTrainingPipeline",
    "get_recovery_model",
    "get_anomaly_detector",
    "FeatureBuilder",
    "FEATURE_CONTRACT",
    "FEATURE_NAMES",
    "ModelRegistry",
    "registry",
    "InferenceService",
    "DatasetGenerator",
    "DatasetValidator",
]
