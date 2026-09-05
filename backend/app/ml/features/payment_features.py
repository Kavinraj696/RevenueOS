"""
Payment gateway and failure feature extractor with error code categorization.
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional


KNOWN_BANKS = {"HDFC", "ICICI", "SBI", "AXIS", "KOTAK", "YES_BANK", "PNB", "BOB"}
KNOWN_METHODS = {"upi", "card", "netbanking", "wallet"}
KNOWN_DEVICES = {"android", "ios", "desktop", "mobile_web"}


def categorize_error_code(error_code: Optional[str], failure_reason: Optional[str] = None) -> str:
    """Categorize raw error codes or failure strings into standard risk categories."""
    raw = f"{error_code or ''} {failure_reason or ''}".upper()
    if not raw.strip():
        return "UNKNOWN"
    if any(k in raw for k in ("TIMEOUT", "NETWORK", "GATEWAY", "DOWN", "LATENCY", "504", "502")):
        return "TIMEOUT"
    if any(k in raw for k in ("FUNDS", "BALANCE", "INSUFFICIENT", "LOW")):
        return "INSUFFICIENT_FUNDS"
    if any(k in raw for k in ("LIMIT", "EXCEEDS", "EXCEEDED", "MAX_AMOUNT")):
        return "LIMIT_EXCEEDED"
    if any(k in raw for k in ("AUTH", "OTP", "EXPIRED", "DECLINE", "PIN", "CVV", "PASSWORD")):
        return "AUTH_FAILURE"
    return "OTHER"


def extract_payment_features(
    payment: Any,
    attempts: List[Any],
    customer_payments_history: List[Any],
    prediction_time: datetime,
) -> Dict[str, Any]:
    """
    Extract payment-level attributes, failure codes, and method-specific historical success rates.
    """
    pred_t = prediction_time if prediction_time.tzinfo else prediction_time.replace(tzinfo=timezone.utc)

    # Filter attempts strictly <= prediction_time
    valid_attempts = []
    for a in attempts:
        att_time = getattr(a, "attempted_at", None)
        if att_time is not None:
            if att_time.tzinfo is None:
                att_time = att_time.replace(tzinfo=timezone.utc)
            if att_time <= pred_t:
                valid_attempts.append((att_time, a))

    valid_attempts.sort(key=lambda x: x[0])
    previous_attempt_count = max(1, len(valid_attempts))

    latest_attempt = valid_attempts[-1][1] if valid_attempts else None
    err_code = getattr(latest_attempt, "error_code", None) if latest_attempt else None
    fail_msg = getattr(latest_attempt, "failure_reason", None) if latest_attempt else None
    failure_cat = categorize_error_code(err_code, fail_msg)

    time_since_failure = 0.0
    if valid_attempts:
        t_fail = valid_attempts[-1][0]
        time_since_failure = max(0.0, round((pred_t - t_fail).total_seconds(), 2))

    # Bank handling
    raw_bank = str(getattr(payment, "bank", "UNKNOWN") or "UNKNOWN").upper()
    bank = raw_bank if raw_bank in KNOWN_BANKS else ("OTHER" if raw_bank not in ("", "NONE", "UNKNOWN") else "UNKNOWN")

    # Device handling
    raw_device = str(getattr(payment, "device_type", "unknown") or "unknown").lower()
    device = raw_device if raw_device in KNOWN_DEVICES else "unknown"

    # Payment method historical success rate for this customer
    current_method = str(getattr(payment, "payment_method", "unknown") or "unknown").lower()
    method_total = 0
    method_success = 0
    for p in customer_payments_history:
        p_created = getattr(p, "created_at", None)
        if p_created is not None:
            if p_created.tzinfo is None:
                p_created = p_created.replace(tzinfo=timezone.utc)
            if p_created < pred_t:
                p_m = str(getattr(p, "payment_method", "")).lower()
                if p_m == current_method:
                    method_total += 1
                    p_st = str(getattr(p, "status", "")).lower()
                    if p_st in ("success", "recovered", "captured"):
                        method_success += 1

    method_rate = round(method_success / method_total, 4) if method_total > 0 else 0.50

    return {
        "failure_reason": failure_cat,
        "bank": bank,
        "device_type": device,
        "previous_payment_method_success_rate": method_rate,
        "previous_attempt_count": previous_attempt_count,
        "time_since_failure": time_since_failure,
    }
