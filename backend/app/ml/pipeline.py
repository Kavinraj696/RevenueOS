import math
from datetime import datetime
from decimal import Decimal
from typing import List, Dict, Any, Tuple, Optional
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler

def categorize_error_code(error_code: Optional[str]) -> str:
    """Categorize raw error codes into high-level risk categories."""
    if not error_code:
        return "UNKNOWN"
    code = error_code.upper()
    if "TIMEOUT" in code or "NETWORK" in code or "GATEWAY" in code:
        return "TIMEOUT"
    if "FUNDS" in code or "BALANCE" in code:
        return "INSUFFICIENT_FUNDS"
    if "LIMIT" in code or "EXCEEDS" in code:
        return "LIMIT_EXCEEDED"
    if "AUTH" in code or "OTP" in code or "EXPIRED" in code or "DECLINE" in code:
        return "AUTH_FAILURE"
    return "OTHER"

class PaymentFeatureExtractor:
    """
    Extracts numerical and categorical features from Payment domain records.
    Guarantees strict schema and non-null defaults.
    """

    FEATURE_KEYS = [
        "log_amount", "attempt_count", "customer_ltv",
        "hour_of_day", "day_of_week",
        "payment_method", "bank", "device_type",
        "customer_risk_segment", "error_code_category"
    ]

    @classmethod
    def extract_from_payment(cls, payment: Any) -> Dict[str, Any]:
        """Extract a single feature vector dictionary from a Payment record."""
        amt = float(payment.amount) if hasattr(payment, "amount") else float(payment.get("amount", 0.0))
        log_amount = math.log1p(max(0.0, amt))

        attempts = getattr(payment, "attempts", []) or []
        attempt_count = max(1, len(attempts))

        customer = getattr(payment, "customer", None)
        if customer:
            ltv = float(getattr(customer, "lifetime_value", 0.0) or 0.0)
            risk_seg = str(getattr(customer, "risk_segment", "medium") or "medium")
        else:
            ltv = 0.0
            risk_seg = "medium"

        created_at = getattr(payment, "created_at", None) or datetime.utcnow()
        hour_of_day = created_at.hour
        day_of_week = created_at.weekday()

        method = str(getattr(payment, "payment_method", "upi") or "upi").lower()
        bank = str(getattr(payment, "bank", "OTHER") or "OTHER").upper()
        device = str(getattr(payment, "device_type", "android") or "android").lower()

        err_code = None
        if attempts and len(attempts) > 0:
            err_code = getattr(attempts[0], "error_code", None)
        err_category = categorize_error_code(err_code)

        return {
            "amount": amt,
            "log_amount": log_amount,
            "attempt_count": attempt_count,
            "customer_ltv": ltv,
            "hour_of_day": hour_of_day,
            "day_of_week": day_of_week,
            "payment_method": method,
            "bank": bank,
            "device_type": device,
            "customer_risk_segment": risk_seg,
            "error_code_category": err_category,
            "created_at": created_at,
        }

    @classmethod
    def build_dataset_from_payments(cls, payments: List[Any]) -> List[Dict[str, Any]]:
        """Construct structured records list from a collection of payments."""
        records = []
        for p in payments:
            feat = cls.extract_from_payment(p)
            feat["payment_id"] = str(getattr(p, "id", ""))
            feat["merchant_id"] = str(getattr(p, "merchant_id", ""))
            
            status = getattr(p, "status", "")
            if status == "recovered":
                target = 1
            elif status == "failed":
                target = 0
            else:
                attempts = getattr(p, "attempts", []) or []
                had_fail = any(getattr(a, "status", "") != "success" for a in attempts)
                target = 1 if (had_fail and status == "success") else None

            feat["target"] = target
            records.append(feat)

        return records

class TemporalDataSplitter:
    """
    Executes a strict chronological train/test split on transaction data.
    Guarantees no future lookahead leakage.
    """

    @staticmethod
    def split(
        records: List[Dict[str, Any]],
        time_key: str = "created_at",
        train_ratio: float = 0.75
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Sort by time_key and split into train and test subsets."""
        if not records:
            return [], []

        sorted_recs = sorted(records, key=lambda x: x[time_key])
        split_idx = int(len(sorted_recs) * train_ratio)
        if split_idx >= len(sorted_recs) and len(sorted_recs) > 1:
            split_idx = len(sorted_recs) - 1

        train_recs = sorted_recs[:split_idx]
        test_recs = sorted_recs[split_idx:]
        return train_recs, test_recs

    @staticmethod
    def split_train_val_test(
        records: List[Any],
        time_key: str = "prediction_time",
        train_ratio: float = 0.60,
        val_ratio: float = 0.20,
    ) -> Tuple[List[Any], List[Any], List[Any], Dict[str, Any]]:
        """
        Executes strict 3-way chronological split (Train / Validation / Test).
        Enforces: max(train) <= min(val) and max(val) <= min(test).
        Returns: (train_records, val_records, test_records, metadata)
        """
        if not records:
            return [], [], [], {
                "train_samples": 0, "val_samples": 0, "test_samples": 0,
                "train_range": (None, None), "val_range": (None, None), "test_range": (None, None),
            }

        def get_time(item):
            if isinstance(item, dict):
                return item[time_key]
            return getattr(item, time_key)

        sorted_recs = sorted(records, key=get_time)
        n = len(sorted_recs)

        idx_train = max(1, int(n * train_ratio))
        idx_val = max(idx_train + 1, int(n * (train_ratio + val_ratio)))
        if idx_val >= n and n > 2:
            idx_val = n - 1

        train_recs = sorted_recs[:idx_train]
        val_recs = sorted_recs[idx_train:idx_val]
        test_recs = sorted_recs[idx_val:]

        train_min = get_time(train_recs[0]) if train_recs else None
        train_max = get_time(train_recs[-1]) if train_recs else None
        val_min = get_time(val_recs[0]) if val_recs else None
        val_max = get_time(val_recs[-1]) if val_recs else None
        test_min = get_time(test_recs[0]) if test_recs else None
        test_max = get_time(test_recs[-1]) if test_recs else None

        # Verify chronological ordering
        if train_max and val_min:
            assert train_max <= val_min, f"Temporal leakage: train_max ({train_max}) > val_min ({val_min})"
        if val_max and test_min:
            assert val_max <= test_min, f"Temporal leakage: val_max ({val_max}) > test_min ({test_min})"

        metadata = {
            "total_samples": n,
            "train_samples": len(train_recs),
            "val_samples": len(val_recs),
            "test_samples": len(test_recs),
            "train_range": (train_min.isoformat() if hasattr(train_min, "isoformat") else str(train_min),
                            train_max.isoformat() if hasattr(train_max, "isoformat") else str(train_max)),
            "val_range": (val_min.isoformat() if hasattr(val_min, "isoformat") else str(val_min),
                          val_max.isoformat() if hasattr(val_max, "isoformat") else str(val_max)),
            "test_range": (test_min.isoformat() if hasattr(test_min, "isoformat") else str(test_min),
                           test_max.isoformat() if hasattr(test_max, "isoformat") else str(test_max)),
        }

        return train_recs, val_recs, test_recs, metadata

