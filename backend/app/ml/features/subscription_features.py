"""
Subscription feature extractor with point-in-time filtering for recurring transactions.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional


def extract_subscription_features(
    subscription: Optional[Any],
    subscription_attempts: List[Any],
    prediction_time: datetime,
) -> Dict[str, Any]:
    """
    Extract subscription and recurring mandate features strictly available at prediction_time.
    """
    if subscription is None:
        return {
            "is_subscription": 0,
            "subscription_age_days": 0.0,
            "renewal_number": 0,
            "previous_renewal_count": 0,
            "previous_renewal_success_rate": 0.50,
            "plan_value": 0.0,
            "subscription_status": "none",
        }

    pred_t = prediction_time if prediction_time.tzinfo else prediction_time.replace(tzinfo=timezone.utc)

    sub_created = getattr(subscription, "created_at", None)
    if sub_created is not None:
        if sub_created.tzinfo is None:
            sub_created = sub_created.replace(tzinfo=timezone.utc)
        sub_age = max(0.0, round((pred_t - sub_created).total_seconds() / 86400.0, 4))
    else:
        sub_age = 0.0

    # Filter attempts strictly <= prediction_time
    valid_attempts = []
    for a in subscription_attempts:
        att_time = getattr(a, "attempted_at", None)
        if att_time is not None:
            if att_time.tzinfo is None:
                att_time = att_time.replace(tzinfo=timezone.utc)
            if att_time <= pred_t:
                valid_attempts.append((att_time, a))

    renewal_num = len(valid_attempts)
    prior_attempts = [a[1] for a in valid_attempts[:-1]] if len(valid_attempts) > 1 else []
    prior_count = len(prior_attempts)

    prior_successes = sum(
        1 for a in prior_attempts if str(getattr(a, "status", "")).lower() in ("success", "captured")
    )
    prior_rate = round(prior_successes / prior_count, 4) if prior_count > 0 else 0.50

    plan_val = float(getattr(subscription, "plan_amount", 0.0) or 0.0)
    status_str = str(getattr(subscription, "status", "active") or "active").lower()

    return {
        "is_subscription": 1,
        "subscription_age_days": sub_age,
        "renewal_number": max(1, renewal_num),
        "previous_renewal_count": prior_count,
        "previous_renewal_success_rate": prior_rate,
        "plan_value": plan_val,
        "subscription_status": status_str,
    }
