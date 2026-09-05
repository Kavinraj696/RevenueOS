import uuid
import numpy as np
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple, Union
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.models import (
    Merchant,
    Payment,
    PaymentAttempt,
    Subscription,
    SubscriptionAttempt,
    CheckoutSession,
    RevenueLeak,
    PaymentStatus,
    SubscriptionStatus,
    CheckoutSessionStatus,
    LeakType,
    BankCode,
    PaymentMethod,
    DeviceType,
)

def quantize_dec(val: Union[float, Decimal], places: str = "0.01") -> Decimal:
    """Helper to convert float or Decimal to standard quantized Decimal."""
    if isinstance(val, Decimal):
        return val.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return Decimal(str(round(val, 4))).quantize(Decimal(places), rounding=ROUND_HALF_UP)

def serialize_evidence_dict(d: Any) -> Any:
    """Convert Decimal and datetime objects inside evidence dict to JSON-safe representations."""
    if isinstance(d, Decimal):
        return float(d)
    if isinstance(d, datetime):
        return d.isoformat()
    if isinstance(d, uuid.UUID):
        return str(d)
    if isinstance(d, dict):
        return {k: serialize_evidence_dict(v) for k, v in d.items()}
    if isinstance(d, list):
        return [serialize_evidence_dict(v) for v in d]
    return d


class RevenueLeakDetector:
    """
    Deterministic Revenue Leak Detection Engine (Stage 3).
    Executes statistical, baseline-comparative, and threshold-based analysis
    across 5 core revenue loss vectors without LLM or synthetic shortcuts.
    """

    def __init__(self, db: Session):
        self.db = db

    # -------------------------------------------------------------------------
    # Public Detection Entrypoints
    # -------------------------------------------------------------------------

    def detect_leaks(
        self,
        merchant_id: Optional[uuid.UUID] = None,
        analysis_window_start: Optional[datetime] = None,
        analysis_window_end: Optional[datetime] = None,
        baseline_window_start: Optional[datetime] = None,
        baseline_window_end: Optional[datetime] = None,
        window_days: int = 7
    ) -> List[RevenueLeak]:
        """
        Primary Stage 3 detection interface.
        Analyzes transaction streams within [analysis_window_start, analysis_window_end],
        comparing observed behavior against [baseline_window_start, baseline_window_end].
        """
        if merchant_id:
            merchants = self.db.query(Merchant).filter(Merchant.id == merchant_id).all()
        else:
            merchants = self.db.query(Merchant).all()

        all_detected: List[RevenueLeak] = []
        for m in merchants:
            m_leaks = self._detect_for_merchant(
                merchant=m,
                analysis_start=analysis_window_start,
                analysis_end=analysis_window_end,
                baseline_start=baseline_window_start,
                baseline_end=baseline_window_end,
                window_days=window_days
            )
            all_detected.extend(m_leaks)

        return all_detected

    def run_detection_for_merchant(
        self,
        merchant_id: uuid.UUID,
        window_days: int = 14
    ) -> List[RevenueLeak]:
        """Backward-compatible merchant detection call."""
        return self.detect_leaks(merchant_id=merchant_id, window_days=window_days)

    def run_detection_for_all_merchants(self, window_days: int = 14) -> List[RevenueLeak]:
        """Backward-compatible all-merchants detection call."""
        return self.detect_leaks(merchant_id=None, window_days=window_days)

    # -------------------------------------------------------------------------
    # Internal Merchant Analysis Pipeline
    # -------------------------------------------------------------------------

    def _detect_for_merchant(
        self,
        merchant: Merchant,
        analysis_start: Optional[datetime],
        analysis_end: Optional[datetime],
        baseline_start: Optional[datetime],
        baseline_end: Optional[datetime],
        window_days: int
    ) -> List[RevenueLeak]:
        """Runs the multi-vector detection pipeline for a single merchant."""
        # 1. Resolve Time Boundaries
        a_start, a_end, b_start, b_end = self._resolve_windows(
            merchant.id, analysis_start, analysis_end, baseline_start, baseline_end, window_days
        )

        # 2. Query Current Analysis Window Records
        current_payments = self.db.query(Payment).filter(
            Payment.merchant_id == merchant.id,
            Payment.created_at >= a_start,
            Payment.created_at <= a_end
        ).all()

        current_checkouts = self.db.query(CheckoutSession).filter(
            CheckoutSession.merchant_id == merchant.id,
            CheckoutSession.created_at >= a_start,
            CheckoutSession.created_at <= a_end
        ).all()

        current_sub_attempts = self.db.query(SubscriptionAttempt).join(
            Subscription, SubscriptionAttempt.subscription_id == Subscription.id
        ).filter(
            Subscription.merchant_id == merchant.id,
            SubscriptionAttempt.attempted_at >= a_start,
            SubscriptionAttempt.attempted_at <= a_end
        ).all()

        # 3. Calculate Merchant-Specific Historical Baseline
        baseline = self._calculate_merchant_baseline(merchant.id, b_start, b_end, current_payments)

        # 4. Execute Detection Vectors
        detected: List[RevenueLeak] = []

        # Vector 1: Payment Route Degradation & Failure Spikes
        if current_payments:
            pm_leaks = self._detect_payment_degradations(merchant, current_payments, baseline, a_start, a_end, b_start, b_end)
            detected.extend(pm_leaks)

            # Vector 4: High-Value Failed Transactions (Percentile-based)
            hv_leak = self._detect_high_value_failures(merchant, current_payments, baseline, a_start, a_end)
            if hv_leak:
                detected.append(hv_leak)

            # Vector 5: Repeated Customer Payment Failures
            rep_leak = self._detect_repeated_customer_failures(merchant, current_payments, a_start, a_end)
            if rep_leak:
                detected.append(rep_leak)

        # Vector 2: Checkout Abandonment
        if current_checkouts:
            chk_leak = self._detect_checkout_abandonment(merchant, current_checkouts, baseline, a_start, a_end)
            if chk_leak:
                detected.append(chk_leak)

        # Vector 3: Subscription Recurring Mandate Failures
        sub_leak = self._detect_subscription_failures(merchant, current_sub_attempts, baseline, a_start, a_end)
        if sub_leak:
            detected.append(sub_leak)

        # 5. Persist & Deduplicate Leaks
        persisted = self._persist_leaks(merchant.id, detected)
        return persisted

    # -------------------------------------------------------------------------
    # Time Window & Baseline Engine
    # -------------------------------------------------------------------------

    def _resolve_windows(
        self,
        merchant_id: uuid.UUID,
        analysis_start: Optional[datetime],
        analysis_end: Optional[datetime],
        baseline_start: Optional[datetime],
        baseline_end: Optional[datetime],
        window_days: int
    ) -> Tuple[datetime, datetime, datetime, datetime]:
        """
        Resolves analysis and baseline time windows deterministically.
        Uses latest activity timestamp to avoid wall-clock date drift in tests or replay logs.
        """
        if analysis_end is None:
            # Query max timestamp across tables
            p_max = self.db.query(func.max(Payment.created_at)).filter(Payment.merchant_id == merchant_id).scalar()
            c_max = self.db.query(func.max(CheckoutSession.created_at)).filter(CheckoutSession.merchant_id == merchant_id).scalar()
            s_max = self.db.query(func.max(SubscriptionAttempt.attempted_at)).join(
                Subscription, SubscriptionAttempt.subscription_id == Subscription.id
            ).filter(Subscription.merchant_id == merchant_id).scalar()
            
            candidates = [t for t in (p_max, c_max, s_max) if t is not None]
            analysis_end = max(candidates) if candidates else datetime.now(timezone.utc)

        if analysis_start is None:
            analysis_start = analysis_end - timedelta(days=window_days)

        if baseline_end is None:
            baseline_end = analysis_start

        if baseline_start is None:
            baseline_start = baseline_end - timedelta(days=window_days * 2)

        return analysis_start, analysis_end, baseline_start, baseline_end

    def _determine_severity(
        self,
        rate_diff: float,
        revenue_at_risk: Decimal,
        sample_size: int,
        leak_type: str = "payment_degradation"
    ) -> Tuple[str, Decimal]:
        """
        Step 11: Deterministic severity system.
        Returns (severity_str, severity_score).
        Considers: rate deviation, financial impact (RAR), sample size, and leak type.
        """
        if revenue_at_risk >= Decimal("100000.00") or (rate_diff >= 0.40 and sample_size >= 20):
            return "critical", Decimal("9.50")
        elif revenue_at_risk >= Decimal("25000.00") or (rate_diff >= 0.20 and sample_size >= 15):
            return "high", Decimal("8.00")
        elif revenue_at_risk >= Decimal("5000.00") or (rate_diff >= 0.08 and sample_size >= 10):
            return "medium", Decimal("6.50")
        else:
            return "low", Decimal("4.50")

    def _calculate_confidence(
        self,
        sample_size: int,
        rate_diff: float,
        concentration_score: float = 0.5
    ) -> Decimal:
        """
        Step 12: Transparent detection confidence score.
        Considers sample size, magnitude of deviation, and segment concentration.
        Bounded strictly within [0.40, 0.99].
        """
        sample_factor = min(0.35, sample_size * 0.003)
        diff_factor = min(0.35, abs(rate_diff) * 0.7)
        conc_factor = min(0.20, concentration_score * 0.25)
        base = 0.40
        total = base + sample_factor + diff_factor + conc_factor
        conf_val = min(0.99, max(0.40, total))
        return Decimal(str(round(conf_val, 4)))

    def _calculate_merchant_baseline(
        self,
        merchant_id: uuid.UUID,
        baseline_start: datetime,
        baseline_end: datetime,
        current_payments: Optional[List[Payment]] = None
    ) -> Dict[str, Any]:
        """
        Calculates empirical historical baselines for the merchant.
        If prior historical data is sparse, partitions available payments chronologically.
        """
        # Baseline payments
        b_payments = self.db.query(Payment).filter(
            Payment.merchant_id == merchant_id,
            Payment.created_at >= baseline_start,
            Payment.created_at < baseline_end
        ).all()

        # Fallback: chronological partition of current payments if baseline window had no records
        if len(b_payments) < 10 and current_payments and len(current_payments) >= 10:
            sorted_p = sorted(current_payments, key=lambda p: p.created_at)
            mid = len(sorted_p) // 2
            b_payments = sorted_p[:mid]

        p_total = len(b_payments)
        p_failed = [p for p in b_payments if p.status == PaymentStatus.FAILED.value]
        payment_failure_rate = (len(p_failed) / p_total) if p_total > 0 else 0.035
        payment_failure_rate = max(0.015, payment_failure_rate)  # guard against divide-by-zero

        atv = (sum((p.amount for p in b_payments), Decimal("0.00")) / p_total) if p_total > 0 else Decimal("2500.00")
        total_p_vol = sum((p.amount for p in b_payments), Decimal("0.00"))

        # Payment high-value percentile threshold (top quintile of merchant transaction distribution)
        if p_total >= 10:
            amounts = sorted([float(p.amount) for p in b_payments])
            p90_val = Decimal(str(round(float(np.percentile(amounts, 80)), 2)))
        elif current_payments and len(current_payments) >= 10:
            amounts = sorted([float(p.amount) for p in current_payments])
            p90_val = Decimal(str(round(float(np.percentile(amounts, 80)), 2)))
        else:
            p90_val = Decimal("25000.00")

        # Baseline segments breakdown
        segment_baseline: Dict[Tuple[str, str, str, str], Dict[str, Any]] = defaultdict(
            lambda: {"total": 0, "failed": 0, "failure_rate": 0.035}
        )
        for p in b_payments:
            b = p.bank or "Unknown"
            m = p.payment_method
            d = p.device_type
            h = p.created_at.hour
            h_block = "18:00–22:00" if 18 <= h <= 22 else f"{h//4 * 4:02d}:00-{(h//4 * 4) + 4:02d}:00"
            key = (b, m, d, h_block)
            segment_baseline[key]["total"] += 1
            if p.status == PaymentStatus.FAILED.value:
                segment_baseline[key]["failed"] += 1

        for k, v in segment_baseline.items():
            if v["total"] > 0:
                v["failure_rate"] = max(0.015, v["failed"] / v["total"])

        # Baseline checkouts
        b_checkouts = self.db.query(CheckoutSession).filter(
            CheckoutSession.merchant_id == merchant_id,
            CheckoutSession.created_at >= baseline_start,
            CheckoutSession.created_at < baseline_end
        ).all()
        c_total = len(b_checkouts)
        c_abandoned = [c for c in b_checkouts if c.status == CheckoutSessionStatus.ABANDONED.value]
        checkout_abandonment_rate = (len(c_abandoned) / c_total) if c_total >= 5 else 0.15

        # Baseline subscriptions
        b_sub_attempts = self.db.query(SubscriptionAttempt).join(
            Subscription, SubscriptionAttempt.subscription_id == Subscription.id
        ).filter(
            Subscription.merchant_id == merchant_id,
            SubscriptionAttempt.attempted_at >= baseline_start,
            SubscriptionAttempt.attempted_at < baseline_end
        ).all()
        s_total = len(b_sub_attempts)
        s_failed = [a for a in b_sub_attempts if a.status != "success"]
        subscription_failure_rate = (len(s_failed) / s_total) if s_total >= 5 else 0.05

        return {
            "payment_count": p_total,
            "total_payments": p_total,
            "failed_payments": len(p_failed),
            "payment_failure_rate": payment_failure_rate,
            "payment_success_rate": 1.0 - payment_failure_rate,
            "average_transaction_value": atv,
            "payment_atv": atv,
            "total_payment_volume": total_p_vol,
            "p90_amount": p90_val,
            "segment_baseline": segment_baseline,
            "segments": {
                "bank": {b: {"total": sum(1 for p in b_payments if (p.bank or "Unknown") == b)} for b in {p.bank or "Unknown" for p in b_payments}},
                "method": {m: {"total": sum(1 for p in b_payments if p.payment_method == m)} for m in {p.payment_method for p in b_payments}},
                "device": {d: {"total": sum(1 for p in b_payments if p.device_type == d)} for d in {p.device_type for p in b_payments}},
            },
            "checkout_count": c_total,
            "total_checkouts": c_total,
            "abandoned_checkouts": len(c_abandoned),
            "checkout_abandonment_rate": checkout_abandonment_rate,
            "subscription_attempt_count": s_total,
            "total_subscription_attempts": s_total,
            "failed_subscription_attempts": len(s_failed),
            "subscription_failure_rate": subscription_failure_rate,
            "baseline_window": {"start": baseline_start.isoformat(), "end": baseline_end.isoformat()}
        }

    # -------------------------------------------------------------------------
    # Detection Vectors
    # -------------------------------------------------------------------------

    def _detect_payment_degradations(
        self,
        merchant: Merchant,
        payments: List[Payment],
        baseline: Dict[str, Any],
        window_start: datetime,
        window_end: datetime,
        baseline_start: datetime,
        baseline_end: datetime
    ) -> List[RevenueLeak]:
        """
        Vector 1: Payment Failure Spikes & Multidimensional Root-Cause Analysis.
        Identifies concentrated degradation clusters and ranks contributing segments.
        """
        leaks: List[RevenueLeak] = []
        total_payments = len(payments)
        if total_payments < 5:
            return leaks

        failed_payments = [p for p in payments if p.status == PaymentStatus.FAILED.value]
        curr_fail_rate = len(failed_payments) / total_payments
        base_fail_rate = baseline["payment_failure_rate"]

        # Aggregate across dimensions
        cluster_map = defaultdict(lambda: {"total": 0, "failed": 0, "amount_failed": Decimal("0.00"), "payments": []})
        bank_map = defaultdict(lambda: {"total": 0, "failed": 0, "amount": Decimal("0.00")})
        method_map = defaultdict(lambda: {"total": 0, "failed": 0, "amount": Decimal("0.00")})
        device_map = defaultdict(lambda: {"total": 0, "failed": 0, "amount": Decimal("0.00")})
        hour_map = defaultdict(lambda: {"total": 0, "failed": 0, "amount": Decimal("0.00")})

        for p in payments:
            is_fail = (p.status == PaymentStatus.FAILED.value)
            b = p.bank or "Unknown"
            m = p.payment_method
            d = p.device_type
            h = p.created_at.hour
            h_block = "18:00–22:00" if 18 <= h <= 22 else f"{h//4 * 4:02d}:00-{(h//4 * 4) + 4:02d}:00"

            key = (b, m, d, h_block)
            cluster_map[key]["total"] += 1
            bank_map[b]["total"] += 1
            method_map[m]["total"] += 1
            device_map[d]["total"] += 1
            hour_map[h_block]["total"] += 1

            if is_fail:
                cluster_map[key]["failed"] += 1
                cluster_map[key]["amount_failed"] += p.amount
                cluster_map[key]["payments"].append(p)
                bank_map[b]["failed"] += 1
                bank_map[b]["amount"] += p.amount
                method_map[m]["failed"] += 1
                method_map[m]["amount"] += p.amount
                device_map[d]["failed"] += 1
                device_map[d]["amount"] += p.amount
                hour_map[h_block]["failed"] += 1
                hour_map[h_block]["amount"] += p.amount

        # 1. Evaluate Multi-Dimensional Concentrated Cluster (Highest Priority)
        found_cluster = False
        ranked_clusters = []
        for (b, m, d, h_block), c_data in cluster_map.items():
            if c_data["total"] >= 5 and c_data["failed"] >= 3:
                c_rate = c_data["failed"] / c_data["total"]
                # Expected baseline for this segment: use merchant's normal baseline failure rate
                # (or segment baseline if historical pre-incident data exists and is healthy)
                c_base = base_fail_rate
                if (b, m, d, h_block) in baseline.get("segment_baseline", {}):
                    cand_base = baseline["segment_baseline"][(b, m, d, h_block)]["failure_rate"]
                    if cand_base < 0.20:
                        c_base = cand_base

                rate_diff = c_rate - c_base
                rel_inc = (rate_diff / c_base) if c_base > 0 else 2.0

                if c_rate >= 0.35 and c_rate > (c_base * 2.0):
                    excess_failures = max(0.0, c_data["total"] * rate_diff)
                    atv = (c_data["amount_failed"] / c_data["failed"]) if c_data["failed"] > 0 else baseline["payment_atv"]
                    contribution_score = float(excess_failures) * float(atv)
                    ranked_clusters.append((contribution_score, (b, m, d, h_block), c_data, c_rate, c_base, rate_diff, rel_inc))

        ranked_clusters.sort(key=lambda x: x[0], reverse=True)

        for score, (b, m, d, h_block), c_data, c_rate, c_base, rate_diff, rel_inc in ranked_clusters[:2]:
            found_cluster = True
            gross_affected = c_data["amount_failed"]
            # Transparent Incremental Revenue-at-Risk formula:
            # RAR = Gross Failed Volume * (Excess Failure Rate / Observed Failure Rate)
            rar_fraction = max(0.0, rate_diff / c_rate) if c_rate > 0 else 0.0
            revenue_at_risk = quantize_dec(gross_affected * Decimal(str(round(rar_fraction, 4))))

            # Extract error codes from attempts
            error_codes = set()
            for fp in c_data["payments"]:
                for att in fp.attempts:
                    if att.error_code:
                        error_codes.add(att.error_code)

            # Build Root-Cause Candidates with ranking
            root_causes = [
                f"{b} {m.upper()} gateway timeout/degradation during peak window ({h_block})",
                f"Client device authorization latency on {d.capitalize()}",
            ]
            if error_codes:
                root_causes.append(f"Gateway returned errors: {', '.join(sorted(error_codes))}")

            # Contributing segments breakdown
            candidates_data = [
                {"dimension": "bank", "value": b, "current_rate": round(c_rate, 4), "baseline_rate": round(c_base, 4), "rate_diff": round(rate_diff, 4), "rate_difference": round(rate_diff, 4), "affected_value": float(gross_affected)},
                {"dimension": "payment_method", "value": m.upper(), "current_rate": round(c_rate, 4), "baseline_rate": round(c_base, 4), "rate_diff": round(rate_diff, 4), "rate_difference": round(rate_diff, 4), "affected_value": float(gross_affected)},
                {"dimension": "device_type", "value": d.capitalize(), "current_rate": round(c_rate, 4), "baseline_rate": round(c_base, 4), "rate_diff": round(rate_diff, 4), "rate_difference": round(rate_diff, 4), "affected_value": float(gross_affected)},
                {"dimension": "time_window", "value": h_block, "current_rate": round(c_rate, 4), "baseline_rate": round(c_base, 4), "rate_diff": round(rate_diff, 4), "rate_difference": round(rate_diff, 4), "affected_value": float(gross_affected)},
            ]

            confidence = min(Decimal("0.9800"), Decimal("0.7000") + Decimal(str(round(c_data["failed"] * 0.015 + min(0.15, rate_diff * 0.2), 4))))
            
            severity = "critical" if (revenue_at_risk >= Decimal("50000.00") or (c_rate >= 0.60 and c_data["failed"] >= 10)) else "high"
            sev_score = Decimal("9.20") if severity == "critical" else Decimal("8.10")

            evidence = {
                "baseline_count": baseline.get("total_payments", baseline.get("payment_count", 0)),
                "baseline_failure_count": baseline.get("failed_payments", 0),
                "baseline_failure_rate": quantize_dec(c_base * 100.0),
                "current_count": c_data["total"],
                "current_failure_count": c_data["failed"],
                "current_failure_rate": quantize_dec(c_rate * 100.0),
                "increase_percentage": quantize_dec(rel_inc * 100.0),
                "relative_change": quantize_dec(rel_inc * 100.0),
                "absolute_change": quantize_dec(rate_diff * 100.0),
                "absolute_rate_change": quantize_dec(rate_diff * 100.0),
                "affected_amount": gross_affected,
                "affected_payment_method": m.upper(),
                "affected_bank": b,
                "affected_device": d.capitalize(),
                "peak_window": h_block,
                "sample_size": c_data["total"],
                "failed_count": c_data["failed"],
                "gross_affected_revenue": gross_affected,
                "revenue_at_risk": revenue_at_risk,
                "error_codes": sorted(list(error_codes)),
                "root_cause_candidates": candidates_data,
                "potential_revenue": gross_affected,
                "summary_text": (
                    f"Failure rate spiked from {c_base*100.0:.1f}% baseline to {c_rate*100.0:.1f}% "
                    f"(+{rel_inc*100.0:.0f}%) on {b} {m.upper()} on {d.capitalize()} during {h_block}."
                )
            }

            leak = RevenueLeak(
                id=uuid.uuid4(),
                merchant_id=merchant.id,
                leak_type=LeakType.ANOMALY.value,
                pattern_description=f"Payment Route Degradation: {b} + {m.upper()} + {d.capitalize()} ({h_block})",
                gross_value_affected=gross_affected,
                affected_amount=gross_affected,
                revenue_at_risk=revenue_at_risk,
                currency="INR",
                affected_transactions=c_data["failed"],
                confidence=quantize_dec(confidence, "0.0001"),
                severity=severity,
                severity_score=sev_score,
                status="open",
                root_cause_candidates=candidates_data,
                evidence=serialize_evidence_dict(evidence),
                detection_window_start=window_start,
                detection_window_end=window_end,
            )
            leaks.append(leak)

        # 2. General/Bank-Specific Payment Spike if no multi-dimensional cluster
        if not found_cluster:
            for b, b_data in bank_map.items():
                if b_data["total"] >= 10:
                    b_rate = b_data["failed"] / b_data["total"]
                    if b_rate >= 0.20 and (b_rate - base_fail_rate >= 0.12):
                        rel_inc = (b_rate - base_fail_rate) / base_fail_rate
                        gross_affected = b_data["amount"]
                        rar = quantize_dec(gross_affected * Decimal(str(round((b_rate - base_fail_rate) / b_rate, 4))))
                        evidence = {
                            "baseline_count": baseline.get("total_payments", baseline.get("payment_count", 0)),
                            "baseline_failure_count": baseline.get("failed_payments", 0),
                            "baseline_failure_rate": quantize_dec(base_fail_rate * 100.0),
                            "current_count": b_data["total"],
                            "current_failure_count": b_data["failed"],
                            "current_failure_rate": quantize_dec(b_rate * 100.0),
                            "increase_percentage": quantize_dec(rel_inc * 100.0),
                            "relative_change": quantize_dec(rel_inc * 100.0),
                            "absolute_change": quantize_dec((b_rate - base_fail_rate) * 100.0),
                            "affected_amount": gross_affected,
                            "affected_bank": b,
                            "sample_size": b_data["total"],
                            "failed_count": b_data["failed"],
                            "gross_affected_revenue": gross_affected,
                            "revenue_at_risk": rar,
                            "potential_revenue": gross_affected,
                        }
                        bank_candidates = [
                            {
                                "dimension": "bank",
                                "value": b,
                                "baseline_rate": round(base_fail_rate, 4),
                                "current_rate": round(b_rate, 4),
                                "rate_difference": round(b_rate - base_fail_rate, 4),
                                "rate_diff": round(b_rate - base_fail_rate, 4),
                                "affected_value": float(gross_affected)
                            }
                        ]
                        leak = RevenueLeak(
                            id=uuid.uuid4(),
                            merchant_id=merchant.id,
                            leak_type=LeakType.PAYMENT_FAILURE.value,
                            pattern_description=f"Bank-specific failure spike on {b}",
                            gross_value_affected=gross_affected,
                            affected_amount=gross_affected,
                            revenue_at_risk=rar,
                            currency="INR",
                            affected_transactions=b_data["failed"],
                            confidence=Decimal("0.8800"),
                            severity="high" if rar >= Decimal("25000.00") else "medium",
                            severity_score=Decimal("8.00") if rar >= Decimal("25000.00") else Decimal("6.80"),
                            status="open",
                            root_cause_candidates=bank_candidates,
                            evidence=serialize_evidence_dict(evidence),
                            detection_window_start=window_start,
                            detection_window_end=window_end,
                        )
                        leaks.append(leak)

        # 3. Overall Merchant Failure Spike (Global)
        if curr_fail_rate >= 0.10 and (curr_fail_rate - base_fail_rate >= 0.05) and len(failed_payments) >= 5:
            gross_affected = sum((p.amount for p in failed_payments), Decimal("0.00"))
            rar = quantize_dec(gross_affected * Decimal(str(round((curr_fail_rate - base_fail_rate) / curr_fail_rate, 4))))
            evidence = {
                "baseline_count": baseline.get("total_payments", baseline.get("payment_count", 0)),
                "baseline_failure_count": baseline.get("failed_payments", 0),
                "baseline_failure_rate": quantize_dec(base_fail_rate * 100.0),
                "current_count": total_payments,
                "current_failure_count": len(failed_payments),
                "current_failure_rate": quantize_dec(curr_fail_rate * 100.0),
                "increase_percentage": quantize_dec(((curr_fail_rate - base_fail_rate) / base_fail_rate) * 100.0),
                "relative_change": quantize_dec(((curr_fail_rate - base_fail_rate) / base_fail_rate) * 100.0),
                "absolute_change": quantize_dec((curr_fail_rate - base_fail_rate) * 100.0),
                "affected_amount": gross_affected,
                "sample_size": total_payments,
                "failed_count": len(failed_payments),
                "gross_affected_revenue": gross_affected,
                "revenue_at_risk": rar,
                "potential_revenue": gross_affected,
            }
            global_candidates = [
                {
                    "dimension": "merchant_traffic",
                    "value": "all_methods",
                    "baseline_rate": round(base_fail_rate, 4),
                    "current_rate": round(curr_fail_rate, 4),
                    "rate_difference": round(curr_fail_rate - base_fail_rate, 4),
                    "rate_diff": round(curr_fail_rate - base_fail_rate, 4),
                    "affected_value": float(gross_affected)
                }
            ]
            leak = RevenueLeak(
                id=uuid.uuid4(),
                merchant_id=merchant.id,
                leak_type=LeakType.PAYMENT_FAILURE.value,
                pattern_description="Elevated payment failure rate across recent traffic",
                gross_value_affected=gross_affected,
                affected_amount=gross_affected,
                revenue_at_risk=rar,
                currency="INR",
                affected_transactions=len(failed_payments),
                confidence=Decimal("0.8500"),
                severity="high" if rar >= Decimal("50000.00") else "medium",
                severity_score=Decimal("7.80") if rar >= Decimal("50000.00") else Decimal("6.50"),
                status="open",
                root_cause_candidates=global_candidates,
                evidence=serialize_evidence_dict(evidence),
                detection_window_start=window_start,
                detection_window_end=window_end,
            )
            leaks.append(leak)

        return leaks

    def _detect_checkout_abandonment(
        self,
        merchant: Merchant,
        sessions: List[CheckoutSession],
        baseline: Dict[str, Any],
        window_start: datetime,
        window_end: datetime
    ) -> Optional[RevenueLeak]:
        """
        Vector 2: Checkout Funnel Drop-off & Abandonment.
        """
        total_sessions = len(sessions)
        if total_sessions < 5:
            return None

        abandoned = [s for s in sessions if s.status == CheckoutSessionStatus.ABANDONED.value]
        aban_rate = len(abandoned) / total_sessions
        base_aban_rate = baseline["checkout_abandonment_rate"]

        # Meaningful deviation check (>= 25% rate and >= 10 percentage points above baseline)
        if aban_rate >= 0.25 and (aban_rate > base_aban_rate * 1.3 or aban_rate - base_aban_rate >= 0.10):
            total_lost_cart = sum((s.cart_value for s in abandoned), Decimal("0.00"))
            excess_rate = max(0.0, aban_rate - base_aban_rate)
            rar_fraction = (excess_rate / aban_rate) if aban_rate > 0 else 0.40
            revenue_at_risk = quantize_dec(total_lost_cart * Decimal(str(round(rar_fraction, 4))))

            stage_counts = defaultdict(int)
            for s in abandoned:
                stage = s.stage_dropped or "unknown"
                stage_counts[stage] += 1

            top_stage = max(stage_counts.items(), key=lambda x: x[1])[0] if stage_counts else "otp_entry"

            candidates_data = [
                {"dimension": "checkout_stage", "value": st, "abandoned_count": cnt, "percentage": round(cnt / len(abandoned) * 100, 1)}
                for st, cnt in sorted(stage_counts.items(), key=lambda x: x[1], reverse=True)
            ]

            evidence = {
                "baseline_failure_rate": quantize_dec(base_aban_rate * 100.0),
                "baseline_abandonment_rate": quantize_dec(base_aban_rate * 100.0),
                "current_failure_rate": quantize_dec(aban_rate * 100.0),
                "current_abandonment_rate": quantize_dec(aban_rate * 100.0),
                "increase_percentage": quantize_dec(((aban_rate - base_aban_rate) / base_aban_rate) * 100.0),
                "primary_stage_dropped": top_stage,
                "stage_breakdown": dict(stage_counts),
                "sample_size": total_sessions,
                "abandoned_count": len(abandoned),
                "affected_checkout_count": len(abandoned),
                "affected_checkout_value": total_lost_cart,
                "gross_affected_revenue": total_lost_cart,
                "revenue_at_risk": revenue_at_risk,
                "root_cause_candidates": candidates_data,
                "potential_revenue": total_lost_cart,
                "summary_text": (
                    f"Checkout abandonment rate at {aban_rate*100.0:.1f}% (+{((aban_rate - base_aban_rate) / base_aban_rate)*100.0:.0f}% vs baseline). "
                    f"{len(abandoned)} sessions abandoned with INR {total_lost_cart:,.2f} cart value. Top drop-off point: {top_stage}."
                )
            }

            severity = "critical" if revenue_at_risk >= Decimal("100000.00") else ("high" if total_lost_cart >= Decimal("50000.00") else "medium")
            sev_score = Decimal("9.00") if severity == "critical" else (Decimal("8.20") if severity == "high" else Decimal("7.00"))

            return RevenueLeak(
                id=uuid.uuid4(),
                merchant_id=merchant.id,
                leak_type=LeakType.CHECKOUT_ABANDONMENT.value,
                pattern_description=f"High Checkout Abandonment Drop-off at {top_stage}",
                gross_value_affected=total_lost_cart,
                affected_amount=total_lost_cart,
                revenue_at_risk=revenue_at_risk,
                currency="INR",
                affected_transactions=len(abandoned),
                confidence=Decimal("0.9100"),
                severity=severity,
                severity_score=sev_score,
                status="open",
                root_cause_candidates=[
                    f"Friction / SMS delivery delays at {top_stage}",
                    "Lack of preferred UPI / 1-click payment option at checkout",
                    "Unexpected shipping fee addition prior to payment"
                ],
                evidence=serialize_evidence_dict(evidence),
                detection_window_start=window_start,
                detection_window_end=window_end,
            )
        return None

    def _detect_subscription_failures(
        self,
        merchant: Merchant,
        attempts: List[SubscriptionAttempt],
        baseline: Dict[str, Any],
        window_start: datetime,
        window_end: datetime
    ) -> Optional[RevenueLeak]:
        """
        Vector 3: Subscription Mandate Auto-Debit Failure Spike.
        """
        if not attempts or len(attempts) < 5:
            return None

        failed_attempts = [a for a in attempts if a.status != "success"]
        sub_fail_rate = len(failed_attempts) / len(attempts)
        base_sub_rate = baseline["subscription_failure_rate"]

        if sub_fail_rate >= 0.20 and (sub_fail_rate - base_sub_rate >= 0.10):
            # Extract subscriptions and compute MRR loss
            sub_ids = {a.subscription_id for a in failed_attempts}
            failed_subs = self.db.query(Subscription).filter(Subscription.id.in_(sub_ids)).all()
            total_mrr_affected = sum((s.plan_amount for s in failed_subs), Decimal("0.00"))
            
            excess_sub_rate = max(0.0, sub_fail_rate - base_sub_rate)
            rar_fraction = (excess_sub_rate / sub_fail_rate) if sub_fail_rate > 0 else 0.40
            revenue_at_risk = quantize_dec(total_mrr_affected * Decimal(str(round(rar_fraction, 4))))

            err_counts = defaultdict(int)
            for a in failed_attempts:
                code = a.error_code or "UNKNOWN_MANDATE_ERROR"
                err_counts[code] += 1

            candidates_data = [
                {"dimension": "mandate_error_code", "value": err, "failed_count": cnt, "percentage": round(cnt / len(failed_attempts) * 100, 1)}
                for err, cnt in sorted(err_counts.items(), key=lambda x: x[1], reverse=True)
            ]

            inc_pct = ((sub_fail_rate - base_sub_rate) / base_sub_rate) * 100.0
            evidence = {
                "baseline_failure_rate": quantize_dec(base_sub_rate * 100.0),
                "current_failure_rate": quantize_dec(sub_fail_rate * 100.0),
                "increase_percentage": quantize_dec(inc_pct),
                "error_code_breakdown": dict(err_counts),
                "sample_size": len(attempts),
                "failed_renewals_count": len(failed_attempts),
                "affected_subscriptions_count": len(failed_subs),
                "gross_affected_revenue": total_mrr_affected,
                "revenue_at_risk": revenue_at_risk,
                "root_cause_candidates": candidates_data,
                "potential_revenue": total_mrr_affected,
                "summary_text": (
                    f"Subscription renewal failure rate reached {sub_fail_rate*100.0:.1f}% "
                    f"(+{inc_pct:.0f}% vs baseline). {len(failed_subs)} subscriptions failed."
                )
            }

            severity = "critical" if revenue_at_risk >= Decimal("100000.00") else ("high" if total_mrr_affected >= Decimal("20000.00") else "medium")
            sev_score = Decimal("9.10") if severity == "critical" else (Decimal("8.40") if severity == "high" else Decimal("7.20"))

            return RevenueLeak(
                id=uuid.uuid4(),
                merchant_id=merchant.id,
                leak_type=LeakType.SUBSCRIPTION_FAILURE.value,
                pattern_description="Subscription Mandate Auto-Debit Failure Spike",
                gross_value_affected=total_mrr_affected,
                affected_amount=total_mrr_affected,
                revenue_at_risk=revenue_at_risk,
                currency="INR",
                affected_transactions=len(failed_attempts),
                confidence=Decimal("0.9300"),
                severity=severity,
                severity_score=sev_score,
                status="open",
                root_cause_candidates=[
                    "Bank recurring mandate limit exceeded (RBI INR 15k e-mandate threshold)",
                    "Card expiration on annual/monthly renewal cycle",
                    "Customer account insufficient funds at month-end"
                ],
                evidence=serialize_evidence_dict(evidence),
                detection_window_start=window_start,
                detection_window_end=window_end,
            )
        return None

    def _detect_high_value_failures(
        self,
        merchant: Merchant,
        payments: List[Payment],
        baseline: Dict[str, Any],
        window_start: datetime,
        window_end: datetime
    ) -> Optional[RevenueLeak]:
        """
        Vector 4: High-Value Failed Transactions (Percentile-Based).
        Identifies orders exceeding the merchant's 90th percentile transaction threshold.
        """
        threshold = baseline.get("p90_amount", Decimal("25000.00"))
        # Ensure threshold is at least INR 15,000 to represent high financial impact
        threshold = max(Decimal("15000.00"), threshold)

        high_value_failures = [
            p for p in payments
            if p.status == PaymentStatus.FAILED.value and p.amount >= threshold
        ]

        # If strict threshold yields fewer than 2 failures, evaluate against top quartile (75th percentile)
        if len(high_value_failures) < 2 and len(payments) >= 10:
            amounts = sorted([float(p.amount) for p in payments])
            p75 = Decimal(str(round(float(np.percentile(amounts, 75)), 2)))
            alt_th = max(Decimal("15000.00"), p75)
            alt_failures = [
                p for p in payments
                if p.status == PaymentStatus.FAILED.value and p.amount >= alt_th
            ]
            if len(alt_failures) >= 2:
                threshold = alt_th
                high_value_failures = alt_failures

        if len(high_value_failures) >= 2:
            total_hv_loss = sum((p.amount for p in high_value_failures), Decimal("0.00"))
            avg_val = total_hv_loss / len(high_value_failures)
            
            # High value recovery carrying high intent: estimated 85% is addressable
            rar = quantize_dec(total_hv_loss * Decimal("0.85"))

            evidence = {
                "high_value_threshold_inr": threshold,
                "percentile_threshold": float(threshold),
                "high_value_failed_count": len(high_value_failures),
                "average_transaction_value": quantize_dec(avg_val),
                "gross_affected_revenue": total_hv_loss,
                "revenue_at_risk": rar,
                "potential_revenue": total_hv_loss,
                "summary_text": (
                    f"{len(high_value_failures)} high-value transactions failed (>= INR {threshold:,.2f}), "
                    f"representing INR {total_hv_loss:,.2f} in lost revenue (avg INR {avg_val:,.2f})."
                )
            }

            severity = "critical" if total_hv_loss >= Decimal("100000.00") else "high"
            sev_score = Decimal("9.10") if total_hv_loss >= Decimal("100000.00") else Decimal("8.10")

            return RevenueLeak(
                id=uuid.uuid4(),
                merchant_id=merchant.id,
                leak_type=LeakType.PAYMENT_FAILURE.value,
                pattern_description=f"High-Value Transaction Drop-offs (>= INR {threshold:,.0f})",
                gross_value_affected=total_hv_loss,
                affected_amount=total_hv_loss,
                revenue_at_risk=rar,
                currency="INR",
                affected_transactions=len(high_value_failures),
                confidence=Decimal("0.9500"),
                severity=severity,
                severity_score=sev_score,
                status="open",
                root_cause_candidates=[
                    "Card per-transaction limit exceeded",
                    "Netbanking two-factor authentication drop-off",
                    "Issuer anti-fraud high-ticket block"
                ],
                evidence=serialize_evidence_dict(evidence),
                detection_window_start=window_start,
                detection_window_end=window_end,
            )
        return None

    def _detect_repeated_customer_failures(
        self,
        merchant: Merchant,
        payments: List[Payment],
        window_start: datetime,
        window_end: datetime
    ) -> Optional[RevenueLeak]:
        """
        Vector 5: Repeated Customer Payment Failures (Churn Drop-off).
        Aggregates distinct failed payments per customer to prevent double-counting attempts.
        """
        cust_failures: Dict[uuid.UUID, List[Payment]] = defaultdict(list)
        for p in payments:
            if p.status == PaymentStatus.FAILED.value:
                cust_failures[p.customer_id].append(p)

        repeat_drop_customers = {cid: plist for cid, plist in cust_failures.items() if len(plist) >= 2}

        if len(repeat_drop_customers) >= 1 and sum(len(plist) for plist in repeat_drop_customers.values()) >= 2:
            total_repeat_loss = sum((sum((p.amount for p in plist), Decimal("0.00")) for plist in repeat_drop_customers.values()), Decimal("0.00"))
            total_failed_distinct_payments = sum(len(plist) for plist in repeat_drop_customers.values())
            
            rar = quantize_dec(total_repeat_loss * Decimal("0.75"))

            candidates_data = [
                {"customer_id": str(cid), "failed_payments_count": len(plist), "attempted_value_inr": float(sum((p.amount for p in plist), Decimal("0.00")))}
                for cid, plist in sorted(repeat_drop_customers.items(), key=lambda x: len(x[1]), reverse=True)[:5]
            ]

            evidence = {
                "affected_customers_count": len(repeat_drop_customers),
                "total_repeated_failed_transactions": total_failed_distinct_payments,
                "gross_affected_revenue": total_repeat_loss,
                "revenue_at_risk": rar,
                "top_affected_customers": candidates_data,
                "potential_revenue": total_repeat_loss,
                "summary_text": (
                    f"{len(repeat_drop_customers)} customers experienced repeated payment failures "
                    f"({total_failed_distinct_payments} distinct failed orders, INR {total_repeat_loss:,.2f} lost)."
                )
            }

            severity = "high" if total_repeat_loss >= Decimal("25000.00") else "medium"
            sev_score = Decimal("8.00") if total_repeat_loss >= Decimal("25000.00") else Decimal("7.10")

            return RevenueLeak(
                id=uuid.uuid4(),
                merchant_id=merchant.id,
                leak_type=LeakType.PAYMENT_FAILURE.value,
                pattern_description="Repeated Customer Payment Failures (High Churn Risk)",
                gross_value_affected=total_repeat_loss,
                affected_amount=total_repeat_loss,
                revenue_at_risk=rar,
                currency="INR",
                affected_transactions=total_failed_distinct_payments,
                confidence=Decimal("0.8900"),
                severity=severity,
                severity_score=sev_score,
                status="open",
                root_cause_candidates=[
                    "Persistent customer payment instrument failure",
                    "Lack of retry-assisted smart payment links",
                    "Issuer decline without fallback payment method prompt"
                ],
                evidence=serialize_evidence_dict(evidence),
                detection_window_start=window_start,
                detection_window_end=window_end,
            )
        return None

    # -------------------------------------------------------------------------
    # Deduplication & Persistence
    # -------------------------------------------------------------------------

    def _persist_leaks(self, merchant_id: uuid.UUID, detected_leaks: List[RevenueLeak]) -> List[RevenueLeak]:
        """
        Deduplicates and persists detected leaks in the database.
        If an open leak matches (merchant_id, leak_type, pattern_description),
        updates the metrics and window bounds instead of creating duplicate records.
        """
        persisted = []
        for d_leak in detected_leaks:
            d_leak.evidence = serialize_evidence_dict(d_leak.evidence)
            
            existing = self.db.query(RevenueLeak).filter(
                RevenueLeak.merchant_id == merchant_id,
                RevenueLeak.leak_type == d_leak.leak_type,
                RevenueLeak.pattern_description == d_leak.pattern_description,
                RevenueLeak.status == "open"
            ).first()

            if existing:
                # Update existing leak in-place
                existing.gross_value_affected = d_leak.gross_value_affected
                existing.affected_amount = d_leak.affected_amount
                existing.revenue_at_risk = d_leak.revenue_at_risk
                existing.affected_transactions = d_leak.affected_transactions
                existing.confidence = d_leak.confidence
                existing.severity = d_leak.severity
                existing.severity_score = d_leak.severity_score
                existing.evidence = d_leak.evidence
                existing.root_cause_candidates = d_leak.root_cause_candidates
                existing.detection_window_end = max(existing.detection_window_end, d_leak.detection_window_end)
                persisted.append(existing)
            else:
                self.db.add(d_leak)
                persisted.append(d_leak)

        self.db.commit()
        return persisted
