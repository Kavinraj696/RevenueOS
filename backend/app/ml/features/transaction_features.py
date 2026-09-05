"""
Transaction-level feature extractor with strict point-in-time calculation.
"""

import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Any, List, Optional


def extract_transaction_features(
    payment: Any,
    attempts: List[Any],
    prediction_time: datetime,
    merchant_atv: float = 2500.0,
) -> Dict[str, Any]:
    """
    Extract transaction-level features strictly available at prediction_time.
    """
    amt = float(getattr(payment, "amount", 0.0) or 0.0)
    log_amt = math.log1p(max(0.0, amt))
    atv = max(100.0, merchant_atv)
    amt_relative = round(amt / atv, 4)

    created_at = getattr(payment, "created_at", None)
    if created_at is None:
        created_at = prediction_time
    elif created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    pred_t = prediction_time if prediction_time.tzinfo else prediction_time.replace(tzinfo=timezone.utc)

    hour = created_at.hour
    day_of_week = created_at.weekday()
    days_since_tx = max(0.0, round((pred_t - created_at).total_seconds() / 86400.0, 4))

    # Filter attempts strictly <= prediction_time
    valid_attempts = []
    for a in attempts:
        att_time = getattr(a, "attempted_at", None)
        if att_time is not None:
            if att_time.tzinfo is None:
                att_time = att_time.replace(tzinfo=timezone.utc)
            if att_time <= pred_t:
                valid_attempts.append((att_time, a))
        else:
            valid_attempts.append((created_at, a))

    valid_attempts.sort(key=lambda x: x[0])
    attempt_number = max(1, len(valid_attempts))

    time_since_prev = 0.0
    if len(valid_attempts) > 1:
        t_latest = valid_attempts[-1][0]
        t_prev = valid_attempts[-2][0]
        time_since_prev = max(0.0, round((t_latest - t_prev).total_seconds(), 2))

    method = str(getattr(payment, "payment_method", "unknown") or "unknown").lower()

    return {
        "transaction_amount": amt,
        "log_amount": log_amt,
        "amount_percentile_for_merchant": amt_relative,
        "payment_method": method,
        "transaction_hour": hour,
        "transaction_day_of_week": day_of_week,
        "days_since_transaction": days_since_tx,
        "attempt_number": attempt_number,
        "time_since_previous_attempt": time_since_prev,
    }
