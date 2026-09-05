"""
Customer historical features with explicit cold-start handling and strict point-in-time filtering.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional


def extract_customer_features(
    customer_payments_history: List[Any],
    prediction_time: datetime,
) -> Dict[str, Any]:
    """
    Compute customer historical metrics strictly using transactions
    occurring prior to prediction_time.
    """
    pred_t = prediction_time if prediction_time.tzinfo else prediction_time.replace(tzinfo=timezone.utc)

    # Filter transactions strictly before prediction_time
    prior_txs = []
    for p in customer_payments_history:
        p_created = getattr(p, "created_at", None)
        if p_created is not None:
            if p_created.tzinfo is None:
                p_created = p_created.replace(tzinfo=timezone.utc)
            if p_created < pred_t:
                prior_txs.append((p_created, p))

    if not prior_txs:
        # Explicit cold-start
        return {
            "customer_transaction_count_before_prediction": 0,
            "customer_success_count": 0,
            "customer_failure_count": 0,
            "customer_historical_success_rate": 0.50,
            "customer_historical_failure_rate": 0.50,
            "customer_lifetime_value_before_prediction": 0.0,
            "days_since_last_success": -1.0,
            "days_since_last_transaction": -1.0,
            "is_cold_start": 1,
        }

    prior_txs.sort(key=lambda x: x[0])
    total_count = len(prior_txs)

    success_count = 0
    failure_count = 0
    ltv = 0.0
    latest_success_time: Optional[datetime] = None
    latest_tx_time = prior_txs[-1][0]

    for t_time, p in prior_txs:
        st = str(getattr(p, "status", "")).lower()
        amt = float(getattr(p, "amount", 0.0) or 0.0)

        # Successful or recovered transactions contribute to settled revenue
        if st in ("success", "recovered", "captured"):
            success_count += 1
            ltv += amt
            latest_success_time = t_time
        elif st in ("failed", "dropped", "cancelled"):
            failure_count += 1

    success_rate = round(success_count / total_count, 4)
    failure_rate = round(failure_count / total_count, 4)

    days_since_tx = max(0.0, round((pred_t - latest_tx_time).total_seconds() / 86400.0, 4))
    if latest_success_time:
        days_since_success = max(0.0, round((pred_t - latest_success_time).total_seconds() / 86400.0, 4))
    else:
        days_since_success = -1.0

    return {
        "customer_transaction_count_before_prediction": total_count,
        "customer_success_count": success_count,
        "customer_failure_count": failure_count,
        "customer_historical_success_rate": success_rate,
        "customer_historical_failure_rate": failure_rate,
        "customer_lifetime_value_before_prediction": round(ltv, 2),
        "days_since_last_success": days_since_success,
        "days_since_last_transaction": days_since_tx,
        "is_cold_start": 0,
    }
