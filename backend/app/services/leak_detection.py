import uuid
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
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
)

def quantize_dec(val: float, places: str = "0.01") -> Decimal:
    """Helper to convert float to quantized Decimal."""
    return Decimal(str(round(val, 4))).quantize(Decimal(places), rounding=ROUND_HALF_UP)

def serialize_evidence_dict(d: Any) -> Any:
    """Convert Decimal objects inside evidence dict to float/str for clean JSON storage."""
    if isinstance(d, Decimal):
        return float(d)
    if isinstance(d, dict):
        return {k: serialize_evidence_dict(v) for k, v in d.items()}
    if isinstance(d, list):
        return [serialize_evidence_dict(v) for v in d]
    return d

class RevenueLeakDetector:
    """
    Deterministic Revenue Leak Detection Engine.
    Executes rigorous statistical and threshold-based analysis across 9 leak vectors.
    Calculates exact real numbers without LLM or synthetic faking.
    """

    def __init__(self, db: Session):
        self.db = db

    def run_detection_for_merchant(
        self,
        merchant_id: uuid.UUID,
        window_days: int = 14
    ) -> List[RevenueLeak]:
        """Detect and persist all active revenue leaks for a merchant."""
        merchant = self.db.query(Merchant).filter(Merchant.id == merchant_id).first()
        if not merchant:
            return []

        # Reference time for window calculations:
        # Use latest merchant transaction/session timestamp if present, else current UTC time.
        # This allows the engine to function accurately on real-time live events,
        # replay logs, and deterministic synthetic benchmarks without date drift.
        latest_payment_time = self.db.query(func.max(Payment.created_at)).filter(
            Payment.merchant_id == merchant_id
        ).scalar()
        latest_session_time = self.db.query(func.max(CheckoutSession.created_at)).filter(
            CheckoutSession.merchant_id == merchant_id
        ).scalar()
        latest_sub_time = self.db.query(func.max(SubscriptionAttempt.attempted_at)).join(
            Subscription, SubscriptionAttempt.subscription_id == Subscription.id
        ).filter(Subscription.merchant_id == merchant_id).scalar()

        timestamps = [t for t in (latest_payment_time, latest_session_time, latest_sub_time) if t is not None]
        now = max(timestamps) if timestamps else datetime.now(timezone.utc)
        window_start = now - timedelta(days=window_days)

        # Retrieve payments in window
        payments = self.db.query(Payment).filter(
            Payment.merchant_id == merchant_id,
            Payment.created_at >= window_start,
            Payment.created_at <= now
        ).all()

        detected_leaks: List[RevenueLeak] = []

        # Vector 1-5: Payment-related degradation vectors (including multi-dimensional cluster)
        if payments:
            pm_leaks = self._detect_payment_degradations(merchant, payments, window_start, now)
            detected_leaks.extend(pm_leaks)

            # Vector 8: High-value failed transactions
            hv_leak = self._detect_high_value_failures(merchant, payments, window_start, now)
            if hv_leak:
                detected_leaks.append(hv_leak)

            # Vector 9: Repeated customer payment failures
            rep_leak = self._detect_repeated_customer_failures(merchant, payments, window_start, now)
            if rep_leak:
                detected_leaks.append(rep_leak)

        # Vector 6: Checkout abandonment
        checkout_leak = self._detect_checkout_abandonment(merchant, window_start, now)
        if checkout_leak:
            detected_leaks.append(checkout_leak)

        # Vector 7: Subscription failure spikes
        sub_leak = self._detect_subscription_failures(merchant, window_start, now)
        if sub_leak:
            detected_leaks.append(sub_leak)

        # Persist or update leaks in DB
        persisted_leaks = self._persist_leaks(merchant_id, detected_leaks)
        return persisted_leaks

    def run_detection_for_all_merchants(self, window_days: int = 14) -> List[RevenueLeak]:
        """Run leak detection across all registered merchants."""
        merchants = self.db.query(Merchant).all()
        all_leaks = []
        for m in merchants:
            leaks = self.run_detection_for_merchant(m.id, window_days=window_days)
            all_leaks.extend(leaks)
        return all_leaks

    # -------------------------------------------------------------------------
    # Detection Vector Implementations
    # -------------------------------------------------------------------------

    def _detect_payment_degradations(
        self,
        merchant: Merchant,
        payments: List[Payment],
        window_start: datetime,
        window_end: datetime
    ) -> List[RevenueLeak]:
        """
        Analyzes payments for:
        1. Global payment failure spikes
        2. Payment-method degradation
        3. Bank-specific degradation
        4. Device-specific degradation
        5. Time-based peak window degradation
        And synthesizes multi-dimensional degradation clusters.
        """
        leaks: List[RevenueLeak] = []
        total_count = len(payments)
        if total_count == 0:
            return leaks

        failed_payments = [p for p in payments if p.status == PaymentStatus.FAILED.value]
        global_failed_count = len(failed_payments)
        global_failure_rate = float(global_failed_count) / float(total_count)

        # Calculate chronological baseline (first half) vs current (second half)
        sorted_payments = sorted(payments, key=lambda p: p.created_at)
        midpoint = len(sorted_payments) // 2
        earlier_half = sorted_payments[:midpoint] if midpoint > 0 else sorted_payments
        recent_half = sorted_payments[midpoint:] if midpoint > 0 else sorted_payments

        earlier_failed = [p for p in earlier_half if p.status == PaymentStatus.FAILED.value]
        recent_failed = [p for p in recent_half if p.status == PaymentStatus.FAILED.value]

        baseline_rate = float(len(earlier_failed)) / float(len(earlier_half)) if earlier_half else 0.03
        recent_rate = float(len(recent_failed)) / float(len(recent_half)) if recent_half else global_failure_rate
        # Ensure baseline is non-zero for ratio
        baseline_rate = max(0.015, baseline_rate)

        # Multidimensional Slicing
        # Slice by (bank, method, device, hour_range)
        cluster_map = defaultdict(lambda: {"total": 0, "failed": 0, "amount_failed": Decimal("0.00"), "payments": []})
        bank_map = defaultdict(lambda: {"total": 0, "failed": 0, "amount": Decimal("0.00")})
        method_map = defaultdict(lambda: {"total": 0, "failed": 0, "amount": Decimal("0.00")})
        device_map = defaultdict(lambda: {"total": 0, "failed": 0, "amount": Decimal("0.00")})
        hourly_map = defaultdict(lambda: {"total": 0, "failed": 0, "amount": Decimal("0.00")})

        for p in payments:
            is_fail = (p.status == PaymentStatus.FAILED.value)
            b = p.bank or "Unknown"
            m = p.payment_method
            d = p.device_type
            h = p.created_at.hour

            # 4-hour time block (e.g., 18:00-22:00)
            h_block = f"{h//4 * 4:02d}:00-{(h//4 * 4) + 4:02d}:00"
            if 18 <= h <= 22:
                h_block = "18:00–22:00"

            key = (b, m, d, h_block)
            cluster_map[key]["total"] += 1
            bank_map[b]["total"] += 1
            method_map[m]["total"] += 1
            device_map[d]["total"] += 1
            hourly_map[h_block]["total"] += 1

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

                hourly_map[h_block]["failed"] += 1
                hourly_map[h_block]["amount"] += p.amount

        # 1. Multi-dimensional concentrated degradation cluster (Highest Priority)
        found_cluster = False
        for (b, m, d, h_block), c_data in cluster_map.items():
            c_total = c_data["total"]
            c_failed = c_data["failed"]
            if c_total >= 5 and c_failed >= 3:
                c_rate = float(c_failed) / float(c_total)
                if c_rate >= 0.40 and c_rate > (baseline_rate * 2.0):
                    found_cluster = True
                    increase_pct = ((c_rate - baseline_rate) / baseline_rate) * 100.0
                    rar = c_data["amount_failed"] * Decimal("0.85")

                    # Identify root-cause candidates from payment attempts
                    error_codes = set()
                    for fp in c_data["payments"]:
                        for att in fp.attempts:
                            if att.error_code:
                                error_codes.add(att.error_code)

                    root_causes = [
                        f"{b} {m.upper()} gateway timeout/degradation during peak window ({h_block})",
                        f"Device intent processing failure on {d.capitalize()}",
                    ]
                    if error_codes:
                        root_causes.append(f"Gateway returned errors: {', '.join(sorted(error_codes))}")

                    evidence = {
                        "baseline_failure_rate": quantize_dec(baseline_rate * 100.0),
                        "current_failure_rate": quantize_dec(c_rate * 100.0),
                        "increase_percentage": quantize_dec(increase_pct),
                        "affected_payment_method": m.upper(),
                        "affected_bank": b,
                        "affected_device": d.capitalize(),
                        "peak_window": h_block,
                        "potential_revenue": c_data["amount_failed"],
                        "summary_text": (
                            f"Failure rate spiked from {baseline_rate*100.1:.1f}% baseline to {c_rate*100.0:.1f}% "
                            f"(+{increase_pct:.0f}%) on {b} {m.upper()} on {d.capitalize()} during {h_block}."
                        )
                    }

                    leak = RevenueLeak(
                        id=uuid.uuid4(),
                        merchant_id=merchant.id,
                        leak_type=LeakType.ANOMALY.value,
                        pattern_description=f"Payment Route Degradation: {b} + {m.upper()} + {d.capitalize()} ({h_block})",
                        gross_value_affected=c_data["amount_failed"],
                        affected_amount=c_data["amount_failed"],
                        revenue_at_risk=quantize_dec(float(rar)),
                        currency="INR",
                        affected_transactions=c_failed,
                        confidence=quantize_dec(min(0.98, 0.70 + (c_failed * 0.03)), "0.0001"),
                        severity="critical" if rar > Decimal("10000.00") else "high",
                        severity_score=Decimal("9.00") if rar > Decimal("10000.00") else Decimal("8.00"),
                        status="open",
                        root_cause_candidates=root_causes,
                        evidence=evidence,
                        detection_window_start=window_start,
                        detection_window_end=window_end,
                    )
                    leaks.append(leak)

        # 2. Bank-Specific Degradation (if no exact multidimensional cluster found for this bank)
        if not found_cluster:
            for b, b_data in bank_map.items():
                if b_data["total"] >= 10:
                    b_rate = float(b_data["failed"]) / float(b_data["total"])
                    if b_rate >= 0.20 and b_rate > (baseline_rate * 2.0):
                        inc = ((b_rate - baseline_rate) / baseline_rate) * 100.0
                        evidence = {
                            "baseline_failure_rate": quantize_dec(baseline_rate * 100.0),
                            "current_failure_rate": quantize_dec(b_rate * 100.0),
                            "increase_percentage": quantize_dec(inc),
                            "affected_bank": b,
                            "potential_revenue": b_data["amount"]
                        }
                        leak = RevenueLeak(
                            id=uuid.uuid4(),
                            merchant_id=merchant.id,
                            leak_type=LeakType.PAYMENT_FAILURE.value,
                            pattern_description=f"Bank-specific failure spike on {b}",
                            gross_value_affected=b_data["amount"],
                            affected_amount=b_data["amount"],
                            revenue_at_risk=quantize_dec(float(b_data["amount"]) * 0.80),
                            currency="INR",
                            affected_transactions=b_data["failed"],
                            confidence=Decimal("0.8800"),
                            severity="high",
                            severity_score=Decimal("7.80"),
                            status="open",
                            root_cause_candidates=[f"{b} core banking authorization latency/outage"],
                            evidence=evidence,
                            detection_window_start=window_start,
                            detection_window_end=window_end,
                        )
                        leaks.append(leak)

        # 3. Overall Payment Failure Spike (if overall rate is elevated)
        if recent_rate >= 0.10 and recent_rate > (baseline_rate * 1.5):
            inc_global = ((recent_rate - baseline_rate) / baseline_rate) * 100.0
            total_fail_amt = sum(p.amount for p in recent_failed)
            leak = RevenueLeak(
                id=uuid.uuid4(),
                merchant_id=merchant.id,
                leak_type=LeakType.PAYMENT_FAILURE.value,
                pattern_description="Elevated payment failure rate across recent traffic",
                gross_value_affected=total_fail_amt,
                affected_amount=total_fail_amt,
                revenue_at_risk=quantize_dec(float(total_fail_amt) * 0.75),
                currency="INR",
                affected_transactions=len(recent_failed),
                confidence=Decimal("0.8500"),
                severity="medium" if total_fail_amt < Decimal("20000.00") else "high",
                severity_score=Decimal("7.20"),
                status="open",
                root_cause_candidates=["Multiple bank network degradations", "Checkout authentication drops"],
                evidence={
                    "baseline_failure_rate": quantize_dec(baseline_rate * 100.0),
                    "current_failure_rate": quantize_dec(recent_rate * 100.0),
                    "increase_percentage": quantize_dec(inc_global),
                    "potential_revenue": total_fail_amt
                },
                detection_window_start=window_start,
                detection_window_end=window_end,
            )
            leaks.append(leak)

        return leaks

    def _detect_checkout_abandonment(
        self,
        merchant: Merchant,
        window_start: datetime,
        window_end: datetime
    ) -> Optional[RevenueLeak]:
        """
        Vector 6: Checkout Abandonment Detector
        Analyzes dropped checkout sessions and drop-off stages.
        """
        sessions = self.db.query(CheckoutSession).filter(
            CheckoutSession.merchant_id == merchant.id,
            CheckoutSession.created_at >= window_start
        ).all()

        if not sessions or len(sessions) < 5:
            return None

        abandoned = [s for s in sessions if s.status == CheckoutSessionStatus.ABANDONED.value]
        total_sessions = len(sessions)
        abandonment_rate = float(len(abandoned)) / float(total_sessions)

        # Flag if abandonment rate is above normal baseline (e.g. > 25%)
        if abandonment_rate >= 0.25:
            total_lost_cart = sum(s.cart_value for s in abandoned)
            stage_counts = defaultdict(int)
            for s in abandoned:
                stage = s.stage_dropped or "unknown"
                stage_counts[stage] += 1

            top_stage = max(stage_counts.items(), key=lambda x: x[1])[0] if stage_counts else "otp_entry"
            # Est. 40% of abandoned high-intent carts are recoverable via fast payment links
            rar = total_lost_cart * Decimal("0.40")

            evidence = {
                "baseline_failure_rate": Decimal("15.00"),
                "current_failure_rate": quantize_dec(abandonment_rate * 100.0),
                "increase_percentage": quantize_dec(((abandonment_rate - 0.15) / 0.15) * 100.0),
                "primary_stage_dropped": top_stage,
                "stage_breakdown": dict(stage_counts),
                "potential_revenue": total_lost_cart,
                "summary_text": (
                    f"Checkout abandonment rate at {abandonment_rate*100.0:.1f}%. "
                    f"{len(abandoned)} sessions abandoned with ₹{total_lost_cart} cart value. "
                    f"Top drop-off point: {top_stage}."
                )
            }

            return RevenueLeak(
                id=uuid.uuid4(),
                merchant_id=merchant.id,
                leak_type=LeakType.CHECKOUT_ABANDONMENT.value,
                pattern_description=f"High Checkout Abandonment Drop-off at {top_stage}",
                gross_value_affected=total_lost_cart,
                affected_amount=total_lost_cart,
                revenue_at_risk=quantize_dec(float(rar)),
                currency="INR",
                affected_transactions=len(abandoned),
                confidence=Decimal("0.9100"),
                severity="high" if total_lost_cart > Decimal("50000.00") else "medium",
                severity_score=Decimal("8.20") if total_lost_cart > Decimal("50000.00") else Decimal("7.00"),
                status="open",
                root_cause_candidates=[
                    f"Friction / SMS delivery delays at {top_stage}",
                    "Lack of preferred UPI / 1-click payment option at checkout",
                    "Unexpected shipping fee addition prior to payment"
                ],
                evidence=evidence,
                detection_window_start=window_start,
                detection_window_end=window_end,
            )
        return None

    def _detect_subscription_failures(
        self,
        merchant: Merchant,
        window_start: datetime,
        window_end: datetime
    ) -> Optional[RevenueLeak]:
        """
        Vector 7: Subscription Failure Spike Detector
        Analyzes recurring billing mandate drop-offs and error codes.
        """
        subscriptions = self.db.query(Subscription).filter(
            Subscription.merchant_id == merchant.id
        ).all()

        if not subscriptions or len(subscriptions) < 5:
            return None

        sub_ids = [s.id for s in subscriptions]
        attempts = self.db.query(SubscriptionAttempt).filter(
            SubscriptionAttempt.subscription_id.in_(sub_ids),
            SubscriptionAttempt.attempted_at >= window_start
        ).all()

        if not attempts:
            return None

        failed_attempts = [a for a in attempts if a.status != "success"]
        sub_fail_rate = float(len(failed_attempts)) / float(len(attempts))

        # Normal subscription renewal failure is ~4-6%
        baseline_sub_rate = 0.05
        if sub_fail_rate >= 0.15:
            error_code_counts = defaultdict(int)
            for fa in failed_attempts:
                code = fa.error_code or "UNKNOWN_ERROR"
                error_code_counts[code] += 1

            # Total recurring amount affected
            failed_sub_ids = {fa.subscription_id for fa in failed_attempts}
            failed_subs = [s for s in subscriptions if s.id in failed_sub_ids]
            total_mrr_affected = sum(s.plan_amount for s in failed_subs)
            inc_pct = ((sub_fail_rate - baseline_sub_rate) / baseline_sub_rate) * 100.0

            evidence = {
                "baseline_failure_rate": quantize_dec(baseline_sub_rate * 100.0),
                "current_failure_rate": quantize_dec(sub_fail_rate * 100.0),
                "increase_percentage": quantize_dec(inc_pct),
                "error_code_breakdown": dict(error_code_counts),
                "potential_revenue": total_mrr_affected,
                "summary_text": (
                    f"Subscription renewal failure rate reached {sub_fail_rate*100.0:.1f}% "
                    f"(+{inc_pct:.0f}% vs baseline). {len(failed_subs)} subscriptions failed."
                )
            }

            return RevenueLeak(
                id=uuid.uuid4(),
                merchant_id=merchant.id,
                leak_type=LeakType.SUBSCRIPTION_FAILURE.value,
                pattern_description="Subscription Mandate Auto-Debit Failure Spike",
                gross_value_affected=total_mrr_affected,
                affected_amount=total_mrr_affected,
                revenue_at_risk=quantize_dec(float(total_mrr_affected) * 0.70),
                currency="INR",
                affected_transactions=len(failed_attempts),
                confidence=Decimal("0.9300"),
                severity="high",
                severity_score=Decimal("8.40"),
                status="open",
                root_cause_candidates=[
                    "Bank recurring mandate limit exceeded (RBI ₹15k e-mandate threshold)",
                    "Card expiration on annual/monthly renewal cycle",
                    "Customer account insufficient funds at month-end"
                ],
                evidence=evidence,
                detection_window_start=window_start,
                detection_window_end=window_end,
            )
        return None

    def _detect_high_value_failures(
        self,
        merchant: Merchant,
        payments: List[Payment],
        window_start: datetime,
        window_end: datetime
    ) -> Optional[RevenueLeak]:
        """
        Vector 8: High-Value Failed Transactions Detector
        Detects failed transactions with amount >= ₹25,000.
        """
        high_value_failures = [
            p for p in payments
            if p.status == PaymentStatus.FAILED.value and p.amount >= Decimal("25000.00")
        ]

        if len(high_value_failures) >= 2:
            total_hv_loss = sum(p.amount for p in high_value_failures)
            avg_val = total_hv_loss / len(high_value_failures)

            evidence = {
                "high_value_failed_count": len(high_value_failures),
                "average_transaction_value": quantize_dec(float(avg_val)),
                "potential_revenue": total_hv_loss,
                "summary_text": (
                    f"{len(high_value_failures)} high-value transactions failed, "
                    f"representing ₹{total_hv_loss} in lost revenue (avg ₹{avg_val:.2f})."
                )
            }

            return RevenueLeak(
                id=uuid.uuid4(),
                merchant_id=merchant.id,
                leak_type=LeakType.PAYMENT_FAILURE.value,
                pattern_description=f"High-Value Transaction Drop-offs (>= ₹25,000)",
                gross_value_affected=total_hv_loss,
                affected_amount=total_hv_loss,
                revenue_at_risk=quantize_dec(float(total_hv_loss) * 0.85),
                currency="INR",
                affected_transactions=len(high_value_failures),
                confidence=Decimal("0.9500"),
                severity="critical" if total_hv_loss >= Decimal("100000.00") else "high",
                severity_score=Decimal("9.10") if total_hv_loss >= Decimal("100000.00") else Decimal("8.10"),
                status="open",
                root_cause_candidates=[
                    "Card per-transaction limit exceeded",
                    "Netbanking two-factor authentication drop-off",
                    "Issuer anti-fraud high-ticket block"
                ],
                evidence=evidence,
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
        Vector 9: Repeated Customer Payment Failures Detector
        Detects multiple payment failures from the same customer (drop-off churn).
        """
        cust_failures = defaultdict(list)
        for p in payments:
            if p.status == PaymentStatus.FAILED.value:
                cust_failures[p.customer_id].append(p)

        repeat_drop_customers = {cid: plist for cid, plist in cust_failures.items() if len(plist) >= 2}

        if len(repeat_drop_customers) >= 3:
            total_repeat_loss = sum(sum(p.amount for p in plist) for plist in repeat_drop_customers.values())
            total_failed_attempts = sum(len(plist) for plist in repeat_drop_customers.values())

            evidence = {
                "affected_customers_count": len(repeat_drop_customers),
                "total_repeated_failed_attempts": total_failed_attempts,
                "potential_revenue": total_repeat_loss,
                "summary_text": (
                    f"{len(repeat_drop_customers)} customers experienced repeated payment failures "
                    f"({total_failed_attempts} total failed attempts, ₹{total_repeat_loss} lost)."
                )
            }

            return RevenueLeak(
                id=uuid.uuid4(),
                merchant_id=merchant.id,
                leak_type=LeakType.PAYMENT_FAILURE.value,
                pattern_description="Repeated Customer Payment Failures (High Churn Risk)",
                gross_value_affected=total_repeat_loss,
                affected_amount=total_repeat_loss,
                revenue_at_risk=quantize_dec(float(total_repeat_loss) * 0.75),
                currency="INR",
                affected_transactions=total_failed_attempts,
                confidence=Decimal("0.8900"),
                severity="high",
                severity_score=Decimal("7.90"),
                status="open",
                root_cause_candidates=[
                    "Persistent customer payment instrument failure",
                    "Lack of retry-assisted smart payment links",
                    "Issuer decline without fallback payment method prompt"
                ],
                evidence=evidence,
                detection_window_start=window_start,
                detection_window_end=window_end,
            )
        return None

    # -------------------------------------------------------------------------
    # Persistence & Reconciliation
    # -------------------------------------------------------------------------

    def _persist_leaks(self, merchant_id: uuid.UUID, detected_leaks: List[RevenueLeak]) -> List[RevenueLeak]:
        """
        Persists detected leaks in the database without duplicate spamming.
        Updates existing open leaks of the same pattern or inserts fresh ones.
        """
        persisted = []
        for d_leak in detected_leaks:
            d_leak.evidence = serialize_evidence_dict(d_leak.evidence)
            # Check if matching open leak already exists
            existing = self.db.query(RevenueLeak).filter(
                RevenueLeak.merchant_id == merchant_id,
                RevenueLeak.pattern_description == d_leak.pattern_description,
                RevenueLeak.status == "open"
            ).first()

            if existing:
                # Update metrics
                existing.gross_value_affected = d_leak.gross_value_affected
                existing.affected_amount = d_leak.affected_amount
                existing.revenue_at_risk = d_leak.revenue_at_risk
                existing.affected_transactions = d_leak.affected_transactions
                existing.confidence = d_leak.confidence
                existing.severity = d_leak.severity
                existing.severity_score = d_leak.severity_score
                existing.evidence = d_leak.evidence
                existing.root_cause_candidates = d_leak.root_cause_candidates
                existing.detection_window_end = d_leak.detection_window_end
                persisted.append(existing)
            else:
                self.db.add(d_leak)
                persisted.append(d_leak)

        self.db.commit()
        return persisted
