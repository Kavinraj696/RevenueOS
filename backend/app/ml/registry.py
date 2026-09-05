"""
Model Registry & Versioning for RevenueOS.
Manages model metadata, active versions, serialization, deserialization, and reproducibility validation.
"""

import os
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List
import joblib
import numpy as np

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
REGISTRY_METADATA_PATH = ARTIFACTS_DIR / "registry_metadata.json"


@dataclass
class ModelVersionMetadata:
    model_name: str
    model_version: str
    algorithm: str
    feature_version: str
    dataset_version: str
    training_timestamp: str
    training_start: str
    training_end: str
    train_samples: int
    val_samples: int
    test_samples: int
    metrics: Dict[str, Any]
    calibration_method: str
    artifact_path: str
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ModelRegistry:
    """
    Lightweight, traceable Model Registry managing model versions, evaluation records,
    and binary artifact persistence.
    """

    def __init__(self, artifacts_dir: Path = ARTIFACTS_DIR):
        self.artifacts_dir = artifacts_dir
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.artifacts_dir / "registry_metadata.json"

    def register_model(
        self,
        model_name: str,
        model_version: str,
        model_artifact: Any,
        metadata: Dict[str, Any],
        is_active: bool = True,
    ) -> ModelVersionMetadata:
        """
        Persist model artifact and register version metadata.
        Validates artifact by loading it and comparing test predictions.
        """
        artifact_filename = f"{model_name}_{model_version}.joblib"
        artifact_path = self.artifacts_dir / artifact_filename

        # 1. Serialize artifact
        joblib.dump(model_artifact, artifact_path)

        # 2. Deserialization validation check
        loaded = joblib.load(artifact_path)
        sample_input = [{
            "transaction_amount": 1500.0,
            "log_amount": 7.3,
            "payment_method": "upi",
            "is_cold_start": 0,
            "customer_historical_success_rate": 0.85,
            "failure_reason": "TIMEOUT",
            "attempt_number": 1,
        }]
        p_orig = model_artifact.predict_proba(sample_input)[0]
        p_loaded = loaded.predict_proba(sample_input)[0]
        diff = abs(float(p_orig) - float(p_loaded))
        if diff > 1e-5:
            raise RuntimeError(f"Serialization validation failed: prediction diff {diff} > 1e-5")

        # 3. Create metadata entry
        entry = ModelVersionMetadata(
            model_name=model_name,
            model_version=model_version,
            algorithm=metadata.get("algorithm", "HistGradientBoostingClassifier"),
            feature_version=metadata.get("feature_version", "v1.0.0"),
            dataset_version=metadata.get("dataset_version", "recovery_dataset_v1.0.0"),
            training_timestamp=datetime.now(timezone.utc).isoformat(),
            training_start=metadata.get("training_start", ""),
            training_end=metadata.get("training_end", ""),
            train_samples=metadata.get("train_samples", 0),
            val_samples=metadata.get("val_samples", 0),
            test_samples=metadata.get("test_samples", 0),
            metrics=metadata.get("metrics", {}),
            calibration_method=metadata.get("calibration_method", "sigmoid"),
            artifact_path=str(artifact_path),
            is_active=is_active,
        )

        # 4. Save to registry manifest
        manifest = self._load_manifest()
        if is_active:
            # Mark other versions of this model as inactive
            for m in manifest:
                if m.get("model_name") == model_name:
                    m["is_active"] = False

        manifest.append(entry.to_dict())
        self._save_manifest(manifest)
        return entry

    def get_active_model_metadata(self, model_name: str = "payment_recovery_probability") -> Optional[Dict[str, Any]]:
        """Retrieve metadata for the currently active model."""
        manifest = self._load_manifest()
        for m in reversed(manifest):
            if m.get("model_name") == model_name and m.get("is_active"):
                return m
        # Fallback to last registered version if none explicitly active
        for m in reversed(manifest):
            if m.get("model_name") == model_name:
                return m
        return None

    def load_active_model(self, model_name: str = "payment_recovery_probability") -> Optional[Any]:
        """Load the active model pipeline artifact from disk."""
        meta = self.get_active_model_metadata(model_name)
        if meta and "artifact_path" in meta:
            path = Path(meta["artifact_path"])
            if not path.exists():
                path = self.artifacts_dir / path.name
            if path.exists():
                try:
                    return joblib.load(path)
                except Exception as e:
                    logger.warning(f"Error loading model from {path}: {e}")

        # Fallback default artifact
        default_path = self.artifacts_dir / f"{model_name}_v1.joblib"
        if default_path.exists():
            return joblib.load(default_path)
        return None

    def list_models(self) -> List[Dict[str, Any]]:
        """List all registered models and versions."""
        return self._load_manifest()

    def _load_manifest(self) -> List[Dict[str, Any]]:
        if not self.metadata_file.exists():
            return []
        try:
            with open(self.metadata_file, "r") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_manifest(self, manifest: List[Dict[str, Any]]) -> None:
        with open(self.metadata_file, "w") as f:
            json.dump(manifest, f, indent=2)


# Global registry singleton
registry = ModelRegistry()
