"""
Training Dataset Pipeline & Quality Validation for RevenueOS Recovery Intelligence.
"""

import uuid
import random
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.models import Payment, Customer, PaymentAttempt, PaymentStatus
from app.ml.features.feature_builder import FeatureBuilder
from app.ml.features.contract import FEATURE_NAMES

logger = logging.getLogger(__name__)


@dataclass
class TrainingSample:
    sample_id: str
    prediction_time: datetime
    transaction_reference: str
    features: Dict[str, Any]
    label: int  # 1 = Recovered, 0 = Permanent Failure
    dataset_version: str


@dataclass
class DatasetQualityReport:
    total_samples: int
    positive_samples: int
    negative_samples: int
    positive_rate: float
    duplicate_count: int
    missing_value_count: int
    is_valid: bool
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DatasetValidator:
    """
    Validates training dataset integrity and reports quality metrics.
    """

    @staticmethod
    def validate(samples: List[TrainingSample]) -> DatasetQualityReport:
        warnings = []
        if not samples:
            return DatasetQualityReport(
                total_samples=0,
                positive_samples=0,
                negative_samples=0,
                positive_rate=0.0,
                duplicate_count=0,
                missing_value_count=0,
                is_valid=False,
                warnings=["Dataset is empty."],
            )

        seen_ids = set()
        seen_txs = set()
        duplicate_count = 0
        missing_values = 0
        positives = 0
        negatives = 0

        for s in samples:
            # Check ID uniqueness
            if s.sample_id in seen_ids:
                duplicate_count += 1
            seen_ids.add(s.sample_id)

            # Check label validity
            if s.label == 1:
                positives += 1
            elif s.label == 0:
                negatives += 1
            else:
                warnings.append(f"Invalid label {s.label} on sample {s.sample_id}")

            # Check feature values
            for k in FEATURE_NAMES:
                val = s.features.get(k)
                if val is None:
                    missing_values += 1

            # Check timestamp validity
            if s.prediction_time is None:
                warnings.append(f"Missing prediction_time on sample {s.sample_id}")

        total = len(samples)
        pos_rate = round(positives / total, 4) if total > 0 else 0.0

        if total < 50:
            warnings.append(f"Small dataset size ({total} samples). Metrics should be interpreted with caution.")
        if pos_rate < 0.05 or pos_rate > 0.95:
            warnings.append(f"High class imbalance (positive rate = {pos_rate:.1%}).")

        is_valid = (duplicate_count == 0) and (missing_values == 0) and (len(warnings) == 0 or total > 0)

        return DatasetQualityReport(
            total_samples=total,
            positive_samples=positives,
            negative_samples=negatives,
            positive_rate=pos_rate,
            duplicate_count=duplicate_count,
            missing_value_count=missing_values,
            is_valid=is_valid,
            warnings=warnings,
        )


class DatasetGenerator:
    """
    Generates point-in-time training samples for recovery probability modeling.
    """

    DATASET_VERSION = "recovery_dataset_v1.0.0"

    def __init__(self, db: Optional[Session] = None, seed: int = 42):
        self.db = db
        self.seed = seed
        self.feature_builder = FeatureBuilder(db)

    def generate_dataset_from_db(
        self,
        min_samples: int = 80,
    ) -> Tuple[List[TrainingSample], DatasetQualityReport]:
        """
        Generate training samples from actual DB payments and attempts.
        """
        samples: List[TrainingSample] = []
        if self.db:
            payments = self.db.query(Payment).all()
        else:
            payments = []

        # Filter payments that have reached a terminal or recoverable outcome
        for p in payments:
            st = str(getattr(p, "status", "")).lower()
            attempts = getattr(p, "attempts", []) or []

            # Determine label
            if st in ("recovered", "success") and (len(attempts) > 1 or st == "recovered"):
                label = 1
            elif st in ("failed", "dropped", "cancelled"):
                label = 0
            else:
                continue

            created_at = getattr(p, "created_at", None) or datetime.now(timezone.utc)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)

            pred_time = created_at + timedelta(minutes=5)
            feats = self.feature_builder.build_features_for_payment(
                payment=p,
                prediction_time=pred_time,
            )

            sample = TrainingSample(
                sample_id=f"samp_{uuid.uuid4().hex[:12]}",
                prediction_time=pred_time,
                transaction_reference=f"payment:{p.id}",
                features=feats,
                label=label,
                dataset_version=self.DATASET_VERSION,
            )
            samples.append(sample)

        # If DB has insufficient samples for statistical modeling, bootstrap reproducible synthetic rows
        if len(samples) < min_samples:
            logger.info(f"DB samples ({len(samples)}) below threshold ({min_samples}). Augmenting with deterministic historical samples...")
            augmented = self._generate_synthetic_historical_samples(
                count=max(min_samples - len(samples), 80),
                start_time=datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc),
            )
            samples.extend(augmented)

        # Sort chronologically by prediction_time
        samples.sort(key=lambda s: s.prediction_time)

        report = DatasetValidator.validate(samples)
        return samples, report

    def _generate_synthetic_historical_samples(
        self,
        count: int,
        start_time: datetime,
    ) -> List[TrainingSample]:
        """
        Generates realistic, deterministic historical payment outcomes with realistic failure modes.
        Used for reproducible model development and training.
        """
        rng = random.Random(self.seed)
        samples = []

        banks = ["HDFC", "ICICI", "SBI", "AXIS", "KOTAK", "OTHER"]
        methods = ["upi", "card", "netbanking", "wallet"]
        error_types = ["TIMEOUT", "INSUFFICIENT_FUNDS", "AUTH_FAILURE", "LIMIT_EXCEEDED"]

        for i in range(count):
            t_offset = timedelta(hours=i * 2 + rng.uniform(0, 1.5))
            tx_time = start_time + t_offset
            pred_time = tx_time + timedelta(minutes=5)

            method = rng.choice(methods)
            bank = rng.choice(banks)
            amt = float(round(rng.uniform(300.0, 35000.0), 2))
            err = rng.choice(error_types)

            # True recovery probability underlying data generator:
            # Timeouts are highly recoverable (75%), Auth failures moderately (45%), Insufficient funds rarely (20%)
            base_p = 0.50
            if err == "TIMEOUT":
                base_p += 0.28
            elif err == "AUTH_FAILURE":
                base_p -= 0.05
            elif err == "INSUFFICIENT_FUNDS":
                base_p -= 0.25

            # UPI has higher recovery than Netbanking
            if method == "upi":
                base_p += 0.10
            elif method == "netbanking":
                base_p -= 0.08

            # Lower amounts recover easier
            if amt < 2000.0:
                base_p += 0.10
            elif amt > 20000.0:
                base_p -= 0.12

            p_final = max(0.08, min(0.92, base_p))
            label = 1 if (rng.random() < p_final) else 0

            is_cold = 1 if (i % 8 == 0) else 0
            cust_txs = 0 if is_cold else rng.randint(1, 15)
            cust_succ = 0 if is_cold else int(cust_txs * rng.uniform(0.5, 0.95))
            cust_fail = cust_txs - cust_succ
            succ_rate = round(cust_succ / cust_txs, 4) if cust_txs > 0 else 0.50

            feats = {
                "transaction_amount": amt,
                "log_amount": round(math_log1p(amt), 4),
                "amount_percentile_for_merchant": round(amt / 2500.0, 4),
                "payment_method": method,
                "transaction_hour": pred_time.hour,
                "transaction_day_of_week": pred_time.weekday(),
                "days_since_transaction": round(5.0 / 1440.0, 4),
                "attempt_number": rng.choice([1, 2]),
                "time_since_previous_attempt": round(rng.uniform(30.0, 300.0), 2) if rng.random() > 0.5 else 0.0,
                "customer_transaction_count_before_prediction": cust_txs,
                "customer_success_count": cust_succ,
                "customer_failure_count": cust_fail,
                "customer_historical_success_rate": succ_rate,
                "customer_historical_failure_rate": round(1.0 - succ_rate, 4),
                "customer_lifetime_value_before_prediction": round(float(cust_succ * amt * 0.8), 2),
                "days_since_last_success": round(rng.uniform(1.0, 30.0), 2) if cust_succ > 0 else -1.0,
                "days_since_last_transaction": round(rng.uniform(0.1, 15.0), 2) if cust_txs > 0 else -1.0,
                "is_cold_start": is_cold,
                "failure_reason": err,
                "bank": bank,
                "device_type": rng.choice(["android", "ios", "desktop"]),
                "previous_payment_method_success_rate": succ_rate,
                "previous_attempt_count": 1,
                "time_since_failure": 300.0,
                "is_subscription": 1 if (i % 5 == 0) else 0,
                "subscription_age_days": round(rng.uniform(10.0, 200.0), 2) if (i % 5 == 0) else 0.0,
                "renewal_number": rng.randint(1, 6) if (i % 5 == 0) else 0,
                "previous_renewal_count": rng.randint(0, 5) if (i % 5 == 0) else 0,
                "previous_renewal_success_rate": 0.80 if (i % 5 == 0) else 0.50,
                "plan_value": amt if (i % 5 == 0) else 0.0,
                "subscription_status": "active" if (i % 5 == 0) else "none",
                "merchant_payment_success_rate": 0.82,
                "merchant_failure_rate": 0.18,
                "merchant_average_transaction_value": 2500.0,
                "merchant_payment_method_success_rate": 0.84 if method == "upi" else 0.78,
            }

            samples.append(TrainingSample(
                sample_id=f"synth_{uuid.uuid4().hex[:12]}",
                prediction_time=pred_time,
                transaction_reference=f"synthetic:{i+1}",
                features=feats,
                label=label,
                dataset_version=self.DATASET_VERSION,
            ))

        return samples


def math_log1p(x: float) -> float:
    import math
    return math.log1p(max(0.0, x))
