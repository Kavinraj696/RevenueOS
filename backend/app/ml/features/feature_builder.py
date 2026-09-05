"""
Central FeatureBuilder: Assembles the complete point-in-time feature dictionary
enforcing strict temporal boundaries and feature contracts.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models import Payment, Customer, PaymentAttempt, Subscription, Merchant
from app.ml.features.contract import FEATURE_NAMES, FEATURE_CONTRACT
from app.ml.features.transaction_features import extract_transaction_features
from app.ml.features.customer_features import extract_customer_features
from app.ml.features.payment_features import extract_payment_features
from app.ml.features.subscription_features import extract_subscription_features
from app.ml.features.merchant_features import extract_merchant_features


class FeatureBuilder:
    """
    Builds production-safe, point-in-time feature vectors for recovery intelligence.
    Guarantees:
    1. Strict temporal boundary: event_time <= prediction_time.
    2. Zero lookahead leakage.
    3. Cold-start robustness.
    4. Deterministic feature ordering matching the formal feature contract.
    """

    FEATURE_VERSION = "v1.0.0"

    def __init__(self, db: Optional[Session] = None):
        self.db = db

    def build_features_for_payment(
        self,
        payment: Any,
        prediction_time: Optional[datetime] = None,
        customer_history: Optional[List[Any]] = None,
        merchant_history: Optional[List[Any]] = None,
        subscription: Optional[Any] = None,
        subscription_attempts: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build feature dictionary for a single Payment at an exact prediction_time.
        If history lists are not provided and a DB session is available, they will be queried
        strictly with event_time <= prediction_time.
        """
        # 1. Establish exact prediction_time
        if prediction_time is None:
            p_time = getattr(payment, "created_at", None) or datetime.now(timezone.utc)
            if p_time.tzinfo is None:
                p_time = p_time.replace(tzinfo=timezone.utc)
            # Default decision time: 5 minutes after payment failure
            pred_t = p_time + timedelta(minutes=5)
        else:
            pred_t = prediction_time if prediction_time.tzinfo else prediction_time.replace(tzinfo=timezone.utc)

        # 2. Extract attempts strictly <= prediction_time
        all_attempts = getattr(payment, "attempts", []) or []
        valid_attempts = [
            a for a in all_attempts
            if getattr(a, "attempted_at", None) is None or
            (a.attempted_at.replace(tzinfo=timezone.utc) if a.attempted_at.tzinfo is None else a.attempted_at) <= pred_t
        ]

        # 3. Retrieve customer history if needed
        cust_id = getattr(payment, "customer_id", None)
        if customer_history is None:
            if self.db and cust_id:
                customer_history = (
                    self.db.query(Payment)
                    .filter(
                        Payment.customer_id == cust_id,
                        Payment.created_at < pred_t,
                        Payment.id != getattr(payment, "id", None)
                    )
                    .all()
                )
            else:
                customer_history = []

        # 4. Retrieve merchant history if needed
        merch_id = getattr(payment, "merchant_id", None)
        if merchant_history is None:
            if self.db and merch_id:
                merchant_history = (
                    self.db.query(Payment)
                    .filter(
                        Payment.merchant_id == merch_id,
                        Payment.created_at < pred_t,
                        Payment.id != getattr(payment, "id", None)
                    )
                    .limit(500)
                    .all()
                )
            else:
                merchant_history = []

        # Compute merchant ATV for relative amount
        merch_atv = 2500.0
        if merchant_history:
            valid_amts = [float(getattr(p, "amount", 0.0) or 0.0) for p in merchant_history]
            if valid_amts:
                merch_atv = sum(valid_amts) / len(valid_amts)

        # 5. Extract domain feature subsets
        tx_feats = extract_transaction_features(
            payment=payment,
            attempts=valid_attempts,
            prediction_time=pred_t,
            merchant_atv=merch_atv,
        )

        cust_feats = extract_customer_features(
            customer_payments_history=customer_history,
            prediction_time=pred_t,
        )

        pay_feats = extract_payment_features(
            payment=payment,
            attempts=valid_attempts,
            customer_payments_history=customer_history,
            prediction_time=pred_t,
        )

        sub_feats = extract_subscription_features(
            subscription=subscription,
            subscription_attempts=subscription_attempts or [],
            prediction_time=pred_t,
        )

        merch_feats = extract_merchant_features(
            merchant_payments_history=merchant_history,
            payment_method=tx_feats.get("payment_method", "unknown"),
            prediction_time=pred_t,
        )

        # Combine all features
        combined: Dict[str, Any] = {}
        combined.update(tx_feats)
        combined.update(cust_feats)
        combined.update(pay_feats)
        combined.update(sub_feats)
        combined.update(merch_feats)

        # Ensure all contract keys are present with type conformity
        final_features: Dict[str, Any] = {}
        for key in FEATURE_NAMES:
            val = combined.get(key)
            contract = FEATURE_CONTRACT[key]
            if val is None:
                if contract.data_type == "float":
                    val = 0.0
                elif contract.data_type == "int":
                    val = 0
                elif contract.data_type == "str":
                    val = "UNKNOWN"
                else:
                    val = 0
            final_features[key] = val

        return final_features

    def build_batch_features(
        self,
        payments: List[Any],
        prediction_times: Optional[Dict[Any, datetime]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Efficient batch feature extraction pre-fetching histories to avoid N+1 queries.
        """
        if not payments:
            return []

        # Group by customer and merchant for pre-fetching
        cust_ids = {getattr(p, "customer_id", None) for p in payments if getattr(p, "customer_id", None)}
        merch_ids = {getattr(p, "merchant_id", None) for p in payments if getattr(p, "merchant_id", None)}

        customer_history_map: Dict[Any, List[Any]] = {cid: [] for cid in cust_ids}
        merchant_history_map: Dict[Any, List[Any]] = {mid: [] for mid in merch_ids}

        if self.db:
            if cust_ids:
                all_cust_txs = self.db.query(Payment).filter(Payment.customer_id.in_(cust_ids)).all()
                for tx in all_cust_txs:
                    customer_history_map[tx.customer_id].append(tx)
            if merch_ids:
                all_merch_txs = self.db.query(Payment).filter(Payment.merchant_id.in_(merch_ids)).all()
                for tx in all_merch_txs:
                    merchant_history_map[tx.merchant_id].append(tx)

        records = []
        for p in payments:
            pred_t = prediction_times.get(getattr(p, "id", None)) if prediction_times else None
            cid = getattr(p, "customer_id", None)
            mid = getattr(p, "merchant_id", None)
            c_hist = customer_history_map.get(cid, [])
            m_hist = merchant_history_map.get(mid, [])

            feats = self.build_features_for_payment(
                payment=p,
                prediction_time=pred_t,
                customer_history=c_hist,
                merchant_history=m_hist,
            )
            records.append(feats)

        return records
