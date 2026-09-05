import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier, IsolationForest
from sklearn.pipeline import Pipeline
from sklearn.metrics import (
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    accuracy_score,
    confusion_matrix,
)

from app.ml.pipeline import PaymentFeatureExtractor

def quantize_dec(val: float, places: str = "0.01") -> Decimal:
    """Helper to convert float to quantized Decimal."""
    return Decimal(str(round(val, 4))).quantize(Decimal(places), rounding=ROUND_HALF_UP)

class PaymentRecoveryModel:
    """
    MODEL 1: Payment Recovery Probability.
    Predicts probability P(recovery = 1 | failed_transaction) in [0, 1].
    Includes both a Logistic Regression baseline and an improved HistGradientBoosting model.
    """

    MODEL_NAME = "payment_recovery_probability"
    MODEL_VERSION = "v1.0.0"

    def __init__(self, use_baseline: bool = False):
        self.use_baseline = use_baseline
        self.pipeline: Optional[Pipeline] = None
        self.is_fitted: bool = False

    def build_pipeline(self) -> Pipeline:
        vec = DictVectorizer(sparse=False)
        scaler = StandardScaler()
        if self.use_baseline:
            clf = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=42)
        else:
            clf = HistGradientBoostingClassifier(
                max_iter=150,
                learning_rate=0.08,
                max_leaf_nodes=31,
                random_state=42,
                class_weight="balanced"
            )
        return Pipeline([
            ("vectorizer", vec),
            ("scaler", scaler),
            ("classifier", clf)
        ])

    def fit(self, X: List[Dict[str, Any]], y: np.ndarray) -> "PaymentRecoveryModel":
        """Fit model strictly on training data."""
        clean_X = [
            {k: v for k, v in row.items() if k in PaymentFeatureExtractor.FEATURE_KEYS}
            for row in X
        ]
        self.pipeline = self.build_pipeline()
        self.pipeline.fit(clean_X, y)
        self.is_fitted = True
        return self

    def predict_proba(self, X: List[Dict[str, Any]]) -> np.ndarray:
        """Return probability of recovery (class 1)."""
        if not self.is_fitted or self.pipeline is None:
            raise RuntimeError("Model has not been fitted or loaded yet.")
        clean_X = [
            {k: v for k, v in row.items() if k in PaymentFeatureExtractor.FEATURE_KEYS}
            for row in X
        ]
        probs = self.pipeline.predict_proba(clean_X)
        return probs[:, 1]

    def predict_single(self, payment_features: Dict[str, Any]) -> Tuple[float, float]:
        """
        Run inference on a single payment feature dictionary.
        Returns: (recovery_probability, confidence_score)
        """
        prob = float(self.predict_proba([payment_features])[0])
        # Confidence reflects distance from 0.5 decision boundary and statistical strength
        confidence = float(min(0.99, max(0.50, 0.50 + abs(prob - 0.5) * 0.95)))
        return prob, confidence

    def evaluate(self, X_test: List[Dict[str, Any]], y_test: np.ndarray) -> Dict[str, Any]:
        """Compute real, un-invented evaluation metrics on test data."""
        if not self.is_fitted or self.pipeline is None:
            raise RuntimeError("Model has not been fitted.")

        probs = self.predict_proba(X_test)
        preds = (probs >= 0.5).astype(int)

        prec = float(precision_score(y_test, preds, zero_division=0))
        rec = float(recall_score(y_test, preds, zero_division=0))
        f1 = float(f1_score(y_test, preds, zero_division=0))
        acc = float(accuracy_score(y_test, preds))

        # ROC-AUC requires at least 2 distinct classes in test set
        if len(np.unique(y_test)) > 1:
            auc = float(roc_auc_score(y_test, probs))
        else:
            auc = 0.5

        cm = confusion_matrix(y_test, preds).tolist()

        return {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "accuracy": round(acc, 4),
            "roc_auc": round(auc, 4),
            "confusion_matrix": cm,
            "test_samples": len(y_test),
        }

class RevenueAnomalyDetector:
    """
    MODEL 2: Revenue Anomaly Detector.
    Detects unusual changes in payment/revenue behavior using Isolation Forest
    and rolling robust Z-scores (Median Absolute Deviation).
    """

    MODEL_NAME = "revenue_anomaly_detector"
    MODEL_VERSION = "v1.0.0"

    def __init__(self, contamination: float = 0.05):
        self.contamination = contamination
        self.model = IsolationForest(
            contamination=contamination,
            random_state=42,
            n_estimators=100
        )
        self.is_fitted = False
        self.feature_names = ["volume", "failure_rate", "gross_amount", "revenue_at_risk"]

    def fit(self, window_records: List[Dict[str, float]]) -> "RevenueAnomalyDetector":
        """Fit Isolation Forest on historical baseline windows."""
        matrix = np.array([
            [float(r.get(k, 0.0)) for k in self.feature_names]
            for r in window_records
        ])
        self.model.fit(matrix)

        # Compute robust medians and MADs for Z-score calculation
        self.medians = {
            col: float(np.median(matrix[:, idx]))
            for idx, col in enumerate(self.feature_names)
        }
        self.mads = {}
        for idx, col in enumerate(self.feature_names):
            dev = np.abs(matrix[:, idx] - self.medians[col])
            mad = float(np.median(dev))
            self.mads[col] = max(1e-4, mad * 1.4826)

        self.is_fitted = True
        return self

    def predict_anomaly(self, window_data: Dict[str, float]) -> Tuple[bool, float, float]:
        """
        Evaluate if a given time-window's revenue metrics represent an anomaly.
        Returns: (is_anomaly: bool, anomaly_score: float in [0, 1], z_score: float)
        """
        vec = np.array([[float(window_data.get(k, 0.0)) for k in self.feature_names]])
        
        # Robust Z-score on failure rate
        fail_rate = float(window_data.get("failure_rate", 0.0))
        fr_med = getattr(self, "medians", {}).get("failure_rate", 0.035)
        fr_mad = getattr(self, "mads", {}).get("failure_rate", 0.01)
        z_score = max(0.0, (fail_rate - fr_med) / fr_mad) if fr_mad > 0 else 0.0

        if self.is_fitted:
            raw_score = float(self.model.decision_function(vec)[0])
            # Lower raw_score in IsolationForest indicates an isolated anomaly
            anomaly_prob = 1.0 / (1.0 + math.exp(raw_score * 8.0))
            is_anomaly = bool((self.model.predict(vec)[0] == -1) or (z_score >= 2.5))
        else:
            is_anomaly = (fail_rate > 0.15) or (z_score >= 2.5)
            anomaly_prob = min(1.0, max(0.0, fail_rate * 2.5))

        return is_anomaly, round(anomaly_prob, 4), round(z_score, 2)

class RecoveryOpportunityRanker:
    """
    MODEL 3: Recovery Opportunity Ranking.
    Ranks failed/abandoned transactions and sessions based on Expected Recoverable Value:
        Expected Recovery = P(recovery) * Potentially Recoverable Revenue * Confidence

    Explicitly separates all 5 required revenue dimensions:
    1. Gross Affected Revenue
    2. Revenue at Risk (RAR)
    3. Potentially Recoverable Revenue
    4. Expected Recovery
    5. Actual Recovery
    """

    MODEL_NAME = "recovery_opportunity_ranking"
    MODEL_VERSION = "v1.0.0"

    @staticmethod
    def calculate_revenue_breakdown(
        gross_amount: Decimal,
        recovery_probability: float,
        confidence: float,
        is_checkout: bool = False,
        actual_recovered: Decimal = Decimal("0.00")
    ) -> Dict[str, Decimal]:
        """
        Mathematically formulate the 5 revenue dimensions:
        - Gross Affected Revenue: Face value of failed transaction / cart.
        - Revenue at Risk: Net permanent loss without intervention (excluding natural organic retry).
        - Potentially Recoverable Revenue: Upper bound addressable by active recovery channels.
        - Expected Recovery: Actuarial expected return P(rec) * Potentially Recoverable * Conf.
        - Actual Recovery: True settled monetary amount recovered.
        """
        gross = gross_amount

        # Organic baseline self-recovery rate:
        # Checkouts: ~10% organic return; Transactions: ~15% organic card/UPI retry
        organic_rate = 0.10 if is_checkout else 0.15
        rar_multiplier = 1.0 - organic_rate
        rar = quantize_dec(float(gross) * rar_multiplier)

        # Addressable recovery potential via automated channels (smart routing, payment links, mandates)
        addressability_factor = 0.85
        potentially_recoverable = quantize_dec(float(rar) * addressability_factor)

        # Expected recovery: Actuarial expected value
        expected = quantize_dec(float(potentially_recoverable) * recovery_probability * confidence)

        return {
            "gross_affected_revenue": gross,
            "revenue_at_risk": rar,
            "potentially_recoverable_revenue": potentially_recoverable,
            "expected_recovery": expected,
            "actual_recovery": actual_recovered,
        }

    @classmethod
    def rank_opportunities(cls, opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Rank a collection of candidate opportunities by expected recoverable revenue descending.
        """
        for opp in opportunities:
            gross = Decimal(str(opp.get("gross_amount", 0.00)))
            p_rec = float(opp.get("recovery_probability", 0.50))
            conf = float(opp.get("confidence", 0.85))
            is_chk = bool(opp.get("is_checkout", False))
            act_rec = Decimal(str(opp.get("actual_recovery", 0.00)))

            metrics = cls.calculate_revenue_breakdown(
                gross_amount=gross,
                recovery_probability=p_rec,
                confidence=conf,
                is_checkout=is_chk,
                actual_recovered=act_rec
            )
            opp.update(metrics)
            opp["ranking_score"] = float(metrics["expected_recovery"])

        ranked = sorted(opportunities, key=lambda x: x["ranking_score"], reverse=True)
        for idx, item in enumerate(ranked):
            item["priority_rank"] = idx + 1
        return ranked
