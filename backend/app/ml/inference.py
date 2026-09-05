"""
RevenueOS ML Inference Service
Provides point-in-time recovery probability inference, output validation,
explainability extraction, opportunity ranking, and audit persistence.
CRITICAL: THIS SERVICE IS STRICTLY ADVISORY AND HAS NO FINANCIAL EXECUTION AUTHORITY.
"""

import uuid
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models import Payment, Customer, RecoveryOpportunity, ModelPrediction, PaymentStatus, OpportunityStatus
from app.ml.features.feature_builder import FeatureBuilder
from app.ml.models import PaymentRecoveryModel, RecoveryOpportunityRanker, quantize_dec
from app.ml.registry import registry

# Default model version constants
DEFAULT_MODEL_NAME = "payment_recovery_probability"
DEFAULT_MODEL_VERSION = "recovery_probability_v1"
DEFAULT_FEATURE_VERSION = "v1.0.0"


class InferenceValidationError(Exception):
    """Raised when model inference outputs fail safety or range validation checks."""
    pass


class InferenceService:
    """
    Production-safe Inference Service for Recovery Intelligence.
    Advisory only — strictly decoupled from any payment execution provider.
    """

    def __init__(self, db: Session):
        self.db = db
        self.feature_builder = FeatureBuilder(db)
        self._cached_model: Optional[PaymentRecoveryModel] = None

    def _get_active_model(self) -> PaymentRecoveryModel:
        """Retrieve active model from registry or instantiate fitted fallback."""
        if self._cached_model is not None and getattr(self._cached_model, "is_fitted", False):
            return self._cached_model

        model = registry.load_active_model(DEFAULT_MODEL_NAME)
        if model is not None and getattr(model, "is_fitted", False):
            self._cached_model = model
            return self._cached_model

        # In-memory fitted fallback for testing/first boot
        fallback = PaymentRecoveryModel(use_baseline=False)
        sample_x = [
            {"transaction_amount": 1000.0, "log_amount": 6.9, "payment_method": "upi", "failure_reason": "TIMEOUT", "is_cold_start": 0},
            {"transaction_amount": 25000.0, "log_amount": 10.1, "payment_method": "card", "failure_reason": "INSUFFICIENT_FUNDS", "is_cold_start": 1},
        ]
        fallback.fit(sample_x, np.array([1, 0]))
        return fallback

    def predict_recovery_probability(
        self,
        transaction_id: uuid.UUID,
        prediction_time: Optional[datetime] = None,
        persist_audit: bool = True,
    ) -> Dict[str, Any]:
        """
        Run point-in-time inference for a single failed payment transaction.
        1. Retrieve transaction
        2. Determine prediction_time (T_pred)
        3. Build point-in-time features (event_time <= T_pred)
        4. Load active model
        5. Generate probability & confidence
        6. Validate outputs
        7. Calculate expected recovery value & opportunity score
        8. Extract explainable contributing factors
        9. Persist prediction audit record
        10. Return result
        """
        # 1. Retrieve transaction
        payment = self.db.query(Payment).filter(Payment.id == transaction_id).first()
        if not payment:
            raise ValueError(f"Transaction with id {transaction_id} not found.")

        # 2. Determine prediction_time
        if prediction_time is None:
            p_time = getattr(payment, "created_at", None) or datetime.now(timezone.utc)
            if p_time.tzinfo is None:
                p_time = p_time.replace(tzinfo=timezone.utc)
            pred_t = p_time + timedelta(minutes=5)
        else:
            pred_t = prediction_time if prediction_time.tzinfo else prediction_time.replace(tzinfo=timezone.utc)

        # 3. Build features (strictly point-in-time)
        features = self.feature_builder.build_features_for_payment(
            payment=payment,
            prediction_time=pred_t,
        )

        # 4. Load active model
        model = self._get_active_model()
        model_name = getattr(model, "MODEL_NAME", DEFAULT_MODEL_NAME)
        model_version = getattr(model, "MODEL_VERSION", DEFAULT_MODEL_VERSION)
        feature_version = getattr(model, "FEATURE_VERSION", DEFAULT_FEATURE_VERSION)

        # 5. Generate probability & confidence
        prob, conf = model.predict_single(features)

        # 6. Validate outputs
        self._validate_prediction_output(
            probability=prob,
            eligible_revenue=payment.amount,
            model_version=model_version,
            feature_version=feature_version,
            prediction_time=pred_t,
        )

        # 7. Calculate expected recovery value & opportunity score
        eligible_rev = payment.amount * Decimal("0.85")
        erv = RecoveryOpportunityRanker.calculate_expected_recovery_value(
            recovery_probability=prob,
            eligible_revenue=eligible_rev,
        )
        opp_score = RecoveryOpportunityRanker.calculate_opportunity_score(
            expected_recovery_value=float(erv),
            recovery_probability=prob,
            customer_ltv=features.get("customer_lifetime_value_before_prediction", 0.0),
            age_hours=features.get("days_since_transaction", 0.0) * 24.0,
            risk_level="low",
        )

        # 8. Extract explainability factors
        contributing_factors = model.explain_prediction(features)

        # 9. Persist prediction audit record
        if persist_audit:
            serializable_features = {
                k: (v.isoformat() if isinstance(v, datetime) else v)
                for k, v in features.items()
            }
            pred_record = ModelPrediction(
                id=uuid.uuid4(),
                model_name=model_name,
                model_version=model_version,
                entity_type="payment",
                entity_id=payment.id,
                input_features_json=serializable_features,
                prediction=Decimal(str(round(prob, 4))),
                confidence=Decimal(str(round(conf, 4))),
                input_reference=f"payment:{payment.id}",
            )
            self.db.add(pred_record)
            self.db.commit()

        # 10. Return result
        return {
            "transaction_id": payment.id,
            "merchant_id": payment.merchant_id,
            "prediction_time": pred_t,
            "model_name": model_name,
            "model_version": model_version,
            "feature_version": feature_version,
            "recovery_probability": round(prob, 4),
            "confidence": round(conf, 4),
            "eligible_revenue": eligible_rev,
            "expected_recovery_value": erv,
            "opportunity_score": opp_score,
            "contributing_factors": contributing_factors,
            "input_features": features,
            "created_at": datetime.now(timezone.utc),
        }

    def _validate_prediction_output(
        self,
        probability: float,
        eligible_revenue: Decimal,
        model_version: str,
        feature_version: str,
        prediction_time: datetime,
    ) -> None:
        """
        Verify all mandatory safety invariants for model predictions.
        Fails safely if any constraint is violated.
        """
        if not (0.0 <= probability <= 1.0):
            raise InferenceValidationError(f"Invalid recovery_probability: {probability} outside [0.0, 1.0]")
        if eligible_revenue < Decimal("0.00"):
            raise InferenceValidationError(f"Invalid eligible_revenue: {eligible_revenue} < 0")
        if not model_version:
            raise InferenceValidationError("Missing model_version")
        if not feature_version:
            raise InferenceValidationError("Missing feature_version")
        if prediction_time is None:
            raise InferenceValidationError("Missing prediction_time")

    def generate_recovery_opportunities(
        self,
        merchant_id: Optional[uuid.UUID] = None,
        max_candidates: int = 200,
    ) -> List[RecoveryOpportunity]:
        """
        Batch evaluation and persistence of recovery opportunities for failed transactions.
        Pre-fetches histories to eliminate N+1 queries.
        """
        query = self.db.query(Payment).filter(Payment.status == PaymentStatus.FAILED.value)
        if merchant_id:
            query = query.filter(Payment.merchant_id == merchant_id)

        failed_payments = query.order_by(desc(Payment.created_at)).limit(max_candidates).all()
        if not failed_payments:
            return []

        # Batch feature extraction
        feature_dicts = self.feature_builder.build_batch_features(failed_payments)
        model = self._get_active_model()
        probs = model.predict_proba(feature_dicts)

        candidates = []
        for idx, payment in enumerate(failed_payments):
            prob = float(probs[idx])
            amt = payment.amount
            pot_rec = quantize_dec(float(amt) * 0.85)
            erv = RecoveryOpportunityRanker.calculate_expected_recovery_value(
                recovery_probability=prob,
                eligible_revenue=pot_rec,
            )
            feats = feature_dicts[idx]
            ltv = feats.get("customer_lifetime_value_before_prediction", 0.0)
            age_h = feats.get("days_since_transaction", 0.0) * 24.0

            score = RecoveryOpportunityRanker.calculate_opportunity_score(
                expected_recovery_value=float(erv),
                recovery_probability=prob,
                customer_ltv=ltv,
                age_hours=age_h,
                risk_level="low",
            )

            priority_tier = "MEDIUM"
            if score >= 75.0:
                priority_tier = "CRITICAL"
            elif score >= 55.0:
                priority_tier = "HIGH"
            elif score <= 35.0:
                priority_tier = "LOW"

            err_code = feats.get("failure_reason", "UNKNOWN")
            explanation = (
                f"₹{amt:,.0f} transaction | "
                f"Recovery probability: {prob * 100:.0f}% | "
                f"Expected recovery: ₹{erv:,.0f} | "
                f"Failure code: {err_code} | "
                f"Priority: {priority_tier}"
            )

            actions = [
                {
                    "type": "smart_retry" if err_code == "TIMEOUT" else "payment_link",
                    "title": "Smart Retry via alternate gateway" if err_code == "TIMEOUT" else "Send 1-Click Fallback Payment Link",
                    "channel": "direct_gateway" if err_code == "TIMEOUT" else "whatsapp_sms",
                    "risk": "low",
                    "feasibility": 92.0,
                    "expected_recovery": float(erv),
                }
            ]

            now_utc = datetime.now(timezone.utc)
            opp = RecoveryOpportunity(
                id=uuid.uuid4(),
                merchant_id=payment.merchant_id,
                payment_id=payment.id,
                customer_id=payment.customer_id,
                gross_value_affected=amt,
                potentially_recoverable_value=pot_rec,
                recovery_probability=Decimal(str(round(prob, 4))),
                expected_recovered_value=erv,
                actual_recovered_value=Decimal("0.00"),
                currency=payment.currency or "INR",
                status=OpportunityStatus.OPEN.value,
                priority=priority_tier,
                priority_score=Decimal(str(score)),
                risk="low",
                failure_reason=f"Payment failed with code {err_code}",
                explanation=explanation,
                recommended_actions_json=actions,
                model_version=getattr(model, "MODEL_VERSION", DEFAULT_MODEL_VERSION),
                feature_version=getattr(model, "FEATURE_VERSION", DEFAULT_FEATURE_VERSION),
                prediction_time=now_utc,
                created_at=payment.created_at or now_utc,
                updated_at=now_utc,
            )
            candidates.append(opp)

        # Rank opportunities by priority score descending
        candidates.sort(key=lambda o: float(o.priority_score), reverse=True)
        for idx, opp in enumerate(candidates):
            opp.rank = idx + 1

        # Upsert into DB
        persisted = []
        for opp in candidates:
            existing = (
                self.db.query(RecoveryOpportunity)
                .filter(
                    RecoveryOpportunity.payment_id == opp.payment_id,
                    RecoveryOpportunity.status == OpportunityStatus.OPEN.value,
                )
                .first()
            )
            if existing:
                existing.recovery_probability = opp.recovery_probability
                existing.expected_recovered_value = opp.expected_recovered_value
                existing.priority_score = opp.priority_score
                existing.priority = opp.priority
                existing.explanation = opp.explanation
                existing.model_version = opp.model_version
                existing.feature_version = opp.feature_version
                existing.prediction_time = opp.prediction_time
                existing.updated_at = opp.updated_at
                persisted.append(existing)
            else:
                self.db.add(opp)
                persisted.append(opp)

        self.db.commit()
        return persisted


import numpy as np
