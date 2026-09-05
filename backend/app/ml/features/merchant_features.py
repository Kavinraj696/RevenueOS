"""
Merchant baseline feature extractor with historical-only window calculations.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional


def extract_merchant_features(
    merchant_payments_history: List[Any],
    payment_method: str,
    prediction_time: datetime,
) -> Dict[str, Any]:
    """
    Extract merchant-level historical performance metrics strictly prior to prediction_time.
    """
    pred_t = prediction_time if prediction_time.tzinfo else prediction_time.replace(tzinfo=timezone.utc)
    target_method = str(payment_method or "unknown").lower()

    total_count = 0
    success_count = 0
    failure_count = 0
    total_amount = 0.0

    method_count = 0
    method_success = 0

    for p in merchant_payments_history:
        p_created = getattr(p, "created_at", None)
        if p_created is not None:
            if p_created.tzinfo is None:
                p_created = p_created.replace(tzinfo=timezone.utc)
            if p_created < pred_t:
                total_count += 1
                amt = float(getattr(p, "amount", 0.0) or 0.0)
                total_amount += amt

                st = str(getattr(p, "status", "")).lower()
                if st in ("success", "recovered", "captured"):
                    success_count += 1
                elif st in ("failed", "dropped", "cancelled"):
                    failure_count += 1

                p_m = str(getattr(p, "payment_method", "")).lower()
                if p_m == target_method:
                    method_count += 1
                    if st in ("success", "recovered", "captured"):
                        method_success += 1

    if total_count == 0:
        return {
            "merchant_payment_success_rate": 0.80,
            "merchant_failure_rate": 0.20,
            "merchant_average_transaction_value": 2500.0,
            "merchant_payment_method_success_rate": 0.80,
        }

    succ_rate = round(success_count / total_count, 4)
    fail_rate = round(failure_count / total_count, 4)
    atv = round(total_amount / total_count, 2)
    m_rate = round(method_success / method_count, 4) if method_count > 0 else succ_rate

    return {
        "merchant_payment_success_rate": succ_rate,
        "merchant_failure_rate": fail_rate,
        "merchant_average_transaction_value": atv,
        "merchant_payment_method_success_rate": m_rate,
    }
