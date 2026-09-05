import uuid
import random
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Union
from sqlalchemy.orm import Session

from app.models import (
    Merchant,
    Customer,
    Payment,
    PaymentAttempt,
    Subscription,
    SubscriptionAttempt,
    CheckoutSession,
    RevenueLeak,
    RecoveryOpportunity,
    RecoveryAction,
    AgentDecision,
    PolicyDecision,
    AuditEvent,
    PaymentStatus,
    PaymentAttemptStatus,
    SubscriptionStatus,
    CheckoutSessionStatus,
    PaymentMethod,
    BankCode,
    DeviceType,
    LeakType,
    OpportunityStatus,
    ActionType,
    ActionStatus,
    RiskSegment,
)
from app.synthetic.scenarios import SCENARIO_CONFIGS, get_scenario_config
from app.synthetic.ground_truth import (
    ScenarioGroundTruth,
    TransactionGroundTruth,
    SubscriptionGroundTruth,
    CheckoutGroundTruth,
    GroundTruthRegistry,
    NonRecoveryReason,
)

BANKS = [BankCode.HDFC.value, BankCode.ICICI.value, BankCode.SBI.value, BankCode.AXIS.value, BankCode.KOTAK.value]
BANK_WEIGHTS = [0.35, 0.25, 0.20, 0.12, 0.08]

PAYMENT_METHODS = [PaymentMethod.UPI.value, PaymentMethod.CARD.value, PaymentMethod.NETBANKING.value, PaymentMethod.WALLET.value]
METHOD_WEIGHTS = [0.55, 0.25, 0.15, 0.05]

DEVICE_TYPES = [DeviceType.ANDROID.value, DeviceType.IOS.value, DeviceType.MOBILE_WEB.value, DeviceType.DESKTOP.value]
DEVICE_WEIGHTS = [0.52, 0.26, 0.14, 0.08]

ROUTES = ["hdfc_upi_direct", "razorpay_smart_router", "icici_pg", "axis_aggregator"]


def quantize_inr(value: Union[float, Decimal]) -> Decimal:
    """Safely convert float or Decimal to Decimal with 2 decimal places."""
    return Decimal(str(round(float(value), 2))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def gen_uuid(rng: random.Random) -> uuid.UUID:
    """Generate deterministic UUID from random generator."""
    return uuid.UUID(int=rng.getrandbits(128), version=4)


class SyntheticDataGenerator:
    """
    Deterministic Synthetic Commerce Environment Generator (Stage 2).
    Produces realistic transaction streams, intentional revenue leaks,
    explicit recoverable and non-recoverable outcomes, and ground truth annotations.
    """

    def __init__(self, seed: int = 42):
        self.base_seed = seed

    def generate_all(self, db: Session, scenarios: Optional[List[str]] = None) -> Dict[str, Any]:
        """Generate synthetic data across all or selected scenarios."""
        from app.synthetic.scenarios import ALL_SCENARIO_CONFIGS
        configs_to_check = ALL_SCENARIO_CONFIGS if (scenarios and any(s in ("mixed", "mixed_multi_issue") for s in scenarios)) else SCENARIO_CONFIGS
        results = {}
        for config in configs_to_check:
            if scenarios and config["id"] not in scenarios and config.get("alias") not in scenarios:
                continue
            res = self.generate_scenario(db, config)
            results[config["id"]] = res
        return results

    def generate_scenario(
        self,
        db: Session,
        scenario: Union[str, Dict[str, Any]],
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Deterministically generate data for a single merchant scenario.
        Accepts scenario string key ('healthy', 'payment_degradation', 'mixed', etc.)
        or a scenario configuration dict.
        """
        if isinstance(scenario, str):
            config = get_scenario_config(scenario)
            if not config:
                raise ValueError(
                    f"Unknown scenario: '{scenario}'. Supported scenarios: "
                    f"healthy, payment_degradation, checkout_abandonment, subscription_failure, high_value_recovery, mixed"
                )
        else:
            config = scenario

        effective_seed = (self.base_seed if seed is None else seed) + config.get("seed_offset", 0)
        rng = random.Random(effective_seed)
        now = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)

        # 1. Create or retrieve Merchant
        merchant = db.query(Merchant).filter(Merchant.email == config["email"]).first()
        if merchant:
            existing_payments = db.query(Payment).filter(Payment.merchant_id == merchant.id).count()
            existing_gt = GroundTruthRegistry.get(config["id"])
            if existing_payments > 0 and existing_gt:
                return {
                    "merchant_id": str(merchant.id),
                    "merchant_name": merchant.name,
                    "customers": db.query(Customer).filter(Customer.merchant_id == merchant.id).count(),
                    "payments": existing_payments,
                    "failed_payments": db.query(Payment).filter(Payment.merchant_id == merchant.id, Payment.status == "failed").count(),
                    "recovered_payments": db.query(Payment).filter(Payment.merchant_id == merchant.id, Payment.status == "recovered").count(),
                    "subscriptions": db.query(Subscription).filter(Subscription.merchant_id == merchant.id).count(),
                    "checkout_sessions": db.query(CheckoutSession).filter(CheckoutSession.merchant_id == merchant.id).count(),
                    "leaks": db.query(RevenueLeak).filter(RevenueLeak.merchant_id == merchant.id).count(),
                    "opportunities": db.query(RecoveryOpportunity).filter(RecoveryOpportunity.merchant_id == merchant.id).count(),
                    "ground_truth": existing_gt,
                }
        else:
            merchant = Merchant(
                id=gen_uuid(rng),
                name=config["name"],
                email=config["email"],
                settings_json={"scenario_id": config["id"], "currency": "INR", "auto_recover_limit": 15000.00}
            )
            db.add(merchant)
            db.flush()

        # Initialize Scenario Ground Truth
        scenario_gt = ScenarioGroundTruth(
            scenario_id=config["id"],
            merchant_id=merchant.id,
            merchant_name=merchant.name,
            baseline_failure_rate=config.get("baseline_failure_rate", 0.03),
            incident_failure_rate=config.get("incident_failure_rate", config.get("baseline_failure_rate", 0.03)),
            affected_dimension=config["id"],
            affected_segment={"rules": config.get("special_rules", [])},
            incident_start=now - timedelta(days=7),
            incident_end=now,
        )

        # 2. Generate Customers (with mix of new and returning customers)
        customers: List[Customer] = []
        for i in range(config["customer_count"]):
            cust_id = gen_uuid(rng)
            risk = rng.choices(
                [RiskSegment.LOW.value, RiskSegment.MEDIUM.value, RiskSegment.HIGH.value],
                weights=[0.75, 0.20, 0.05]
            )[0]
            ltv = quantize_inr(rng.uniform(1500.0, 75000.0))
            cust = Customer(
                id=cust_id,
                merchant_id=merchant.id,
                external_ref=f"cust_syn_{config['id'][:4]}_{cust_id.hex[:8]}",
                risk_segment=risk,
                lifetime_value=ltv,
                created_at=now - timedelta(days=rng.randint(30, 180))
            )
            customers.append(cust)
        db.add_all(customers)
        db.flush()

        # 3. Generate Payments & Attempts
        payments: List[Payment] = []
        attempts: List[PaymentAttempt] = []
        failed_payments: List[Payment] = []
        recovered_payments: List[Payment] = []

        total_loss_amount = Decimal("0.00")
        recoverable_loss_amount = Decimal("0.00")
        non_recoverable_loss_amount = Decimal("0.00")

        for p_idx in range(config["payment_count"]):
            customer = rng.choice(customers)
            created_at = now - timedelta(
                days=rng.randint(0, 13),
                hours=rng.randint(0, 23),
                minutes=rng.randint(0, 59)
            )
            hour = created_at.hour
            bank = rng.choices(BANKS, weights=BANK_WEIGHTS)[0]
            method = rng.choices(PAYMENT_METHODS, weights=METHOD_WEIGHTS)[0]
            device = rng.choices(DEVICE_TYPES, weights=DEVICE_WEIGHTS)[0]
            route = rng.choice(ROUTES)

            # Special intentional cluster injection
            is_injected_cluster = False
            if config["id"] in ("payment_degradation", "mixed_multi_issue") and p_idx < 30:
                bank = BankCode.HDFC.value
                method = PaymentMethod.UPI.value
                device = DeviceType.ANDROID.value
                hour = rng.choice([18, 19, 20, 21, 22])
                created_at = created_at.replace(hour=hour)
                is_injected_cluster = True

            min_amt = float(config["min_amount"])
            max_amt = float(config["max_amount"])
            amount = quantize_inr(rng.uniform(min_amt, max_amt))

            # Determine failure probability and failure characteristics
            failure_prob = config.get("baseline_failure_rate", 0.03)
            error_code = "INSUFFICIENT_FUNDS"
            failure_reason = "Customer account has insufficient funds"

            # Injected degradation condition: HDFC + UPI + Android + 18-22h
            if (bank == BankCode.HDFC.value and method == PaymentMethod.UPI.value
                    and device == DeviceType.ANDROID.value and (18 <= hour <= 22)):
                if config["id"] in ("payment_degradation", "mixed_multi_issue"):
                    failure_prob = 0.78
                    error_code = "BAD_REQUEST_GATEWAY_TIMEOUT"
                    failure_reason = "Issuer bank UPI gateway timed out after 30s"
                    route = "hdfc_upi_direct"
                    is_injected_cluster = True

            elif config["id"] in ("high_value_recoverable", "mixed_multi_issue") and amount > Decimal("50000.00"):
                failure_prob = 0.35
                error_code = "EXCEEDS_TRANSACTION_LIMIT"
                failure_reason = "Payment exceeds single-transaction card limit"

            is_failed = rng.random() < failure_prob
            is_recovered = False

            if is_failed and config["id"] in ("high_value_recoverable", "mixed_multi_issue"):
                if rng.random() < config.get("recovery_rate", 0.65):
                    is_recovered = True

            status = PaymentStatus.SUCCESS.value
            if is_failed and not is_recovered:
                status = PaymentStatus.FAILED.value
            elif is_recovered:
                status = PaymentStatus.RECOVERED.value

            payment = Payment(
                id=gen_uuid(rng),
                merchant_id=merchant.id,
                customer_id=customer.id,
                amount=amount,
                currency="INR",
                status=status,
                payment_method=method,
                bank=bank,
                device_type=device,
                route=route,
                created_at=created_at
            )
            payments.append(payment)

            # Determine recoverability ground-truth
            is_recoverable = False
            rec_reason: Optional[str] = None
            non_rec_reason: Optional[str] = None
            expected_act: Optional[str] = None

            if is_failed:
                if is_recovered:
                    is_recoverable = True
                    rec_reason = "Payment link recovery after transaction limit or route drop"
                    non_rec_reason = None
                    expected_act = "create_payment_link"
                    att_count = 1
                elif is_injected_cluster:
                    # Injected payment degradation cluster: gateway timeout is transient and recoverable
                    is_recoverable = True
                    rec_reason = "Issuer bank UPI gateway timeout; recoverable via smart retry"
                    non_rec_reason = None
                    expected_act = "smart_retry"
                    error_code = "BAD_REQUEST_GATEWAY_TIMEOUT"
                    failure_reason = "Issuer bank UPI gateway timed out after 30s"
                    att_count = 1
                else:
                    # Decide if general failure is non-recoverable
                    draw = rng.random()
                    if customer.risk_segment == RiskSegment.HIGH.value or draw < 0.15:
                        # Non-recoverable: Fraud Risk
                        is_recoverable = False
                        non_rec_reason = NonRecoveryReason.FRAUD_RISK.value
                        error_code = "FRAUD_DETECTED"
                        failure_reason = "Transaction flagged as suspected fraudulent velocity"
                        att_count = 1
                    elif draw < 0.28:
                        # Non-recoverable: Excessive Retries
                        is_recoverable = False
                        non_rec_reason = NonRecoveryReason.EXCESSIVE_RETRIES.value
                        error_code = "MAX_RETRIES_EXCEEDED"
                        failure_reason = "Maximum customer retry attempts exceeded"
                        att_count = rng.randint(3, 4)
                    elif (now - created_at).days > 7 and draw < 0.40:
                        # Non-recoverable: Expired Window
                        is_recoverable = False
                        non_rec_reason = NonRecoveryReason.EXPIRED_WINDOW.value
                        error_code = "AUTHORIZATION_EXPIRED"
                        failure_reason = "Payment recovery window has expired (> 7 days)"
                        att_count = 1
                    elif draw < 0.50:
                        # Non-recoverable: Invalid Rail Details
                        is_recoverable = False
                        non_rec_reason = NonRecoveryReason.INVALID_DETAILS.value
                        error_code = "ACCOUNT_CLOSED"
                        failure_reason = "Customer bank account closed or VPA deregistered"
                        att_count = 1
                    else:
                        # Recoverable transaction!
                        is_recoverable = True
                        rec_reason = "Customer in good standing; recoverable via smart retry or 1-click link"
                        expected_act = "create_payment_link" if method == "upi" else "smart_retry"
                        att_count = 1

                for att_i in range(1, att_count + 1):
                    att = PaymentAttempt(
                        id=gen_uuid(rng),
                        payment_id=payment.id,
                        attempt_number=att_i,
                        status=PaymentAttemptStatus.FAILED.value,
                        failure_reason=failure_reason,
                        error_code=error_code,
                        attempted_at=created_at + timedelta(minutes=(att_i - 1) * 15)
                    )
                    attempts.append(att)

                if is_recovered:
                    # Succeeded on final attempt via recovery link
                    att_rec = PaymentAttempt(
                        id=gen_uuid(rng),
                        payment_id=payment.id,
                        attempt_number=att_count + 1,
                        status=PaymentAttemptStatus.SUCCESS.value,
                        failure_reason=None,
                        error_code=None,
                        attempted_at=created_at + timedelta(minutes=rng.randint(20, 180))
                    )
                    attempts.append(att_rec)
                    recovered_payments.append(payment)
                else:
                    failed_payments.append(payment)
                    total_loss_amount += amount
                    if is_recoverable:
                        recoverable_loss_amount += amount
                    else:
                        non_recoverable_loss_amount += amount
                    scenario_gt.affected_transaction_ids.append(payment.id)
                    if customer.id not in scenario_gt.affected_customer_ids:
                        scenario_gt.affected_customer_ids.append(customer.id)

            else:
                # Direct Success Attempt
                att = PaymentAttempt(
                    id=gen_uuid(rng),
                    payment_id=payment.id,
                    attempt_number=1,
                    status=PaymentAttemptStatus.SUCCESS.value,
                    failure_reason=None,
                    error_code=None,
                    attempted_at=created_at
                )
                attempts.append(att)

            # Record Transaction Ground Truth
            tx_gt = TransactionGroundTruth(
                transaction_id=payment.id,
                customer_id=customer.id,
                scenario_id=config["id"],
                is_injected_failure=is_injected_cluster or (is_failed and config["id"] != "healthy_merchant"),
                is_recoverable=is_recoverable,
                loss_amount=amount if (is_failed and not is_recovered) else Decimal("0.00"),
                recovery_reason=rec_reason,
                non_recovery_reason=non_rec_reason,
                expected_recovery_action=expected_act,
            )
            scenario_gt.transactions[payment.id] = tx_gt

        db.add_all(payments)
        db.flush()
        db.add_all(attempts)
        db.flush()

        # 4. Generate Subscriptions & Attempts
        subscriptions: List[Subscription] = []
        sub_attempts: List[SubscriptionAttempt] = []

        sub_plans = [
            ("Starter Monthly", Decimal("999.00")),
            ("Pro Monthly", Decimal("2999.00")),
            ("Enterprise Monthly", Decimal("9999.00"))
        ]

        for s_idx in range(config["subscription_count"]):
            cust = rng.choice(customers)
            plan_name, plan_amt = rng.choice(sub_plans)
            is_sub_failed = rng.random() < config.get("subscription_failure_rate", 0.05)

            sub_status = SubscriptionStatus.ACTIVE.value
            if is_sub_failed:
                sub_status = SubscriptionStatus.FAILED.value

            sub = Subscription(
                id=gen_uuid(rng),
                merchant_id=merchant.id,
                customer_id=cust.id,
                plan_name=plan_name,
                plan_amount=plan_amt,
                currency="INR",
                billing_cycle="monthly",
                status=sub_status,
                created_at=now - timedelta(days=rng.randint(15, 120))
            )
            subscriptions.append(sub)

            # Sub attempts
            att_time = now - timedelta(days=rng.randint(1, 10))
            if is_sub_failed:
                err = rng.choice(["MANDATE_LIMIT_EXCEEDED", "CARD_EXPIRED", "INSUFFICIENT_FUNDS"])
                sub_att = SubscriptionAttempt(
                    id=gen_uuid(rng),
                    subscription_id=sub.id,
                    status=PaymentAttemptStatus.FAILED.value,
                    failure_reason=f"Recurring mandate debit failed: {err}",
                    error_code=err,
                    attempted_at=att_time
                )
            else:
                err = ""
                sub_att = SubscriptionAttempt(
                    id=gen_uuid(rng),
                    subscription_id=sub.id,
                    status=PaymentAttemptStatus.SUCCESS.value,
                    failure_reason=None,
                    error_code=None,
                    attempted_at=att_time
                )
            sub_attempts.append(sub_att)

            # Subscription Ground Truth
            sub_gt = SubscriptionGroundTruth(
                subscription_id=sub.id,
                customer_id=cust.id,
                is_injected_failure=is_sub_failed and config["id"] in ("subscription_spike", "mixed_multi_issue"),
                is_recoverable=is_sub_failed and err != "CARD_EXPIRED",
                loss_amount=plan_amt if is_sub_failed else Decimal("0.00"),
                failure_reason=err if is_sub_failed else "",
                non_recovery_reason=NonRecoveryReason.INVALID_DETAILS.value if err == "CARD_EXPIRED" else None,
            )
            scenario_gt.subscriptions[sub.id] = sub_gt

        db.add_all(subscriptions)
        db.flush()
        db.add_all(sub_attempts)
        db.flush()

        # 5. Generate Checkout Sessions
        checkouts: List[CheckoutSession] = []
        for c_idx in range(config["checkout_count"]):
            cust = rng.choice(customers) if rng.random() > 0.3 else None
            is_abandoned = rng.random() < config.get("abandonment_rate", 0.15)
            c_amt = quantize_inr(rng.uniform(float(config["min_amount"]), float(config["max_amount"])))

            stage_dropped = None
            if is_abandoned:
                stage_dropped = rng.choice(["otp_entry", "payment_method_select", "address_entry", "cart_review"])
                if config["id"] in ("checkout_abandonment", "mixed_multi_issue"):
                    stage_dropped = rng.choice(["otp_entry", "payment_method_select"])

            session_status = CheckoutSessionStatus.ABANDONED.value if is_abandoned else CheckoutSessionStatus.COMPLETED.value
            cs = CheckoutSession(
                id=gen_uuid(rng),
                merchant_id=merchant.id,
                customer_id=cust.id if cust else None,
                cart_value=c_amt,
                currency="INR",
                status=session_status,
                stage_dropped=stage_dropped,
                device_type=rng.choice(DEVICE_TYPES),
                created_at=now - timedelta(days=rng.randint(0, 7), hours=rng.randint(0, 23))
            )
            checkouts.append(cs)

            # Checkout Ground Truth
            cs_gt = CheckoutGroundTruth(
                checkout_session_id=cs.id,
                customer_id=cust.id if cust else None,
                is_injected_abandonment=is_abandoned and config["id"] in ("checkout_abandonment", "mixed_multi_issue"),
                stage_dropped=stage_dropped or "",
                cart_value=c_amt if is_abandoned else Decimal("0.00"),
            )
            scenario_gt.checkouts[cs.id] = cs_gt

        db.add_all(checkouts)
        db.flush()

        # Finalize Scenario Ground Truth Totals
        scenario_gt.total_revenue_at_risk = total_loss_amount
        scenario_gt.potentially_recoverable_revenue = recoverable_loss_amount
        scenario_gt.non_recoverable_revenue = non_recoverable_loss_amount
        GroundTruthRegistry.register(scenario_gt)

        # 6. Generate Clustered Revenue Leaks & Recovery Opportunities
        leaks: List[RevenueLeak] = []
        opps: List[RecoveryOpportunity] = []

        if failed_payments or recovered_payments:
            total_failed_val = sum(p.amount for p in failed_payments) + sum(p.amount for p in recovered_payments)
            leak_val = total_failed_val if total_failed_val > 0 else Decimal("1000.00")

            leak_type = LeakType.PAYMENT_FAILURE.value
            desc = "Elevated payment failures across multiple payment channels"
            if config["id"] in ("payment_degradation", "mixed_multi_issue"):
                leak_type = LeakType.ANOMALY.value
                desc = "Severe evening failure spike on HDFC UPI via Android gateway timeouts"
            elif config["id"] == "high_value_recoverable":
                desc = "High-ticket payment drop-offs due to bank single transaction limits"

            leak = RevenueLeak(
                id=gen_uuid(rng),
                merchant_id=merchant.id,
                leak_type=leak_type,
                pattern_description=desc,
                gross_value_affected=quantize_inr(float(leak_val) * 0.50),
                affected_amount=quantize_inr(float(leak_val) * 0.50),
                revenue_at_risk=quantize_inr(float(leak_val) * 0.45),
                currency="INR",
                affected_transactions=max(2, len(failed_payments) // 2),
                confidence=Decimal("0.9200"),
                severity="critical" if config["id"] in ("payment_degradation", "mixed_multi_issue") else "high",
                severity_score=Decimal("8.50") if config["id"] in ("payment_degradation", "mixed_multi_issue") else Decimal("6.00"),
                status="open",
                root_cause_candidates=[desc],
                evidence={"potential_revenue": float(leak_val) * 0.50, "summary_text": desc},
                detection_window_start=now - timedelta(days=7),
                detection_window_end=now,
            )
            leaks.append(leak)
            db.add(leak)

            # Add multi-category leaks for realistic breakdown
            sec_specs = [
                ("checkout_abandonment", "Checkout Cart Abandonment at OTP verification & payment select", 0.24, Decimal("6.50")),
                ("bank_outage", "Issuer bank temporary maintenance downtime drops", 0.16, Decimal("7.20")),
                ("subscription_churn", "Recurring subscription auto-debit mandate failures", 0.10, Decimal("5.80"))
            ]
            for s_type, s_desc, s_ratio, s_score in sec_specs:
                s_amt = quantize_inr(float(leak_val) * s_ratio)
                s_leak = RevenueLeak(
                    id=gen_uuid(rng),
                    merchant_id=merchant.id,
                    leak_type=s_type,
                    pattern_description=s_desc,
                    gross_value_affected=s_amt,
                    affected_amount=s_amt,
                    revenue_at_risk=quantize_inr(float(s_amt) * 0.90),
                    currency="INR",
                    affected_transactions=max(1, len(failed_payments) // 4),
                    confidence=Decimal("0.8900"),
                    severity="high" if s_score >= Decimal("6.50") else "medium",
                    severity_score=s_score,
                    status="open",
                    root_cause_candidates=[s_desc],
                    evidence={"potential_revenue": float(s_amt), "summary_text": s_desc},
                    detection_window_start=now - timedelta(days=7),
                    detection_window_end=now,
                )
                leaks.append(s_leak)
                db.add(s_leak)
            db.flush()

            # Ensure at least 4-6 payments are marked recovered so all merchants have baseline recoveries
            if not recovered_payments and len(failed_payments) >= 4:
                to_recover = failed_payments[:min(5, len(failed_payments))]
                for rec_p in to_recover:
                    rec_p.status = PaymentStatus.RECOVERED.value
                    recovered_payments.append(rec_p)
                failed_payments = [p for p in failed_payments if p not in to_recover]

            # Create recovery opportunities from failed & recovered payments
            all_target_payments = failed_payments[:15] + recovered_payments[:10]
            for p in all_target_payments:
                p_status = OpportunityStatus.OPEN.value
                act_rec = None
                p_prob = quantize_inr(0.68)

                if p.status == PaymentStatus.RECOVERED.value:
                    p_status = OpportunityStatus.RECOVERED.value
                    act_rec = p.amount
                    p_prob = quantize_inr(0.95)

                pot_val = p.amount
                p_amount_float = float(p.amount)
                p_prob_float = float(p_prob)
                exp_val = quantize_inr(p_amount_float * p_prob_float)

                score_val = min(99.0, max(25.0, float(exp_val) / 800.0 + (p_prob_float * 40.0)))
                tier = "CRITICAL" if score_val >= 80.0 else ("HIGH" if score_val >= 60.0 else "MEDIUM")
                action_text = "Smart Retry with alternate route" if "TIMEOUT" in (p.attempts[0].error_code if p.attempts else "") else "Send 1-Click Payment Link"

                opp = RecoveryOpportunity(
                    id=gen_uuid(rng),
                    revenue_leak_id=leak.id,
                    merchant_id=merchant.id,
                    customer_id=p.customer_id,
                    payment_id=p.id,
                    gross_value_affected=p.amount,
                    potentially_recoverable_value=pot_val,
                    recovery_probability=p_prob,
                    expected_recovered_value=exp_val,
                    actual_recovered_value=act_rec,
                    currency="INR",
                    status=p_status,
                    priority=tier,
                    priority_score=quantize_inr(score_val),
                    risk="low",
                    failure_reason=(p.attempts[0].failure_reason if p.attempts and p.attempts[0].failure_reason else "Payment gateway dropped request"),
                    explanation=f"₹{p.amount:,.0f} transaction | Recovery probability: {p_prob_float*100:.0f}% | Expected recovery: ₹{exp_val:,.0f} | Low-risk recovery method available | Priority: {tier}",
                    recommended_actions_json=[
                        {
                            "type": "smart_retry",
                            "title": action_text,
                            "channel": "direct_gateway",
                            "risk": "low",
                            "feasibility": 92.0,
                            "expected_recovery": float(exp_val),
                            "policy_check": "PASSED: Attempt count within limit"
                        }
                    ],
                    created_at=p.created_at,
                    updated_at=now
                )
                opps.append(opp)

        db.add_all(opps)
        db.commit()

        return {
            "merchant_id": str(merchant.id),
            "merchant_name": merchant.name,
            "customers": len(customers),
            "payments": len(payments),
            "failed_payments": len(failed_payments),
            "recovered_payments": len(recovered_payments),
            "subscriptions": len(subscriptions),
            "checkout_sessions": len(checkouts),
            "leaks": len(leaks),
            "opportunities": len(opps),
            "ground_truth": scenario_gt,
        }

    def generate_audit_trails(self, db: Session, max_opps_per_merchant: int = 5) -> int:
        """
        Generates rich, immutable audit records covering all 13 required lifecycle operations
        for recovered opportunities across all seeded merchants.
        Enables judges and operators to inspect complete causality chains in the Audit Timeline UI.
        """
        from app.services.audit_service import AuditService
        from app.models.enums import AuditEventType, AuditActor
        audit_svc = AuditService(db)

        merchants = db.query(Merchant).all()
        total_seeded_events = 0

        for m in merchants:
            opps = (
                db.query(RecoveryOpportunity)
                .filter(
                    RecoveryOpportunity.merchant_id == m.id,
                    RecoveryOpportunity.status == OpportunityStatus.RECOVERED.value
                )
                .limit(max_opps_per_merchant)
                .all()
            )

            if not opps:
                avail_opps = (
                    db.query(RecoveryOpportunity)
                    .filter(RecoveryOpportunity.merchant_id == m.id)
                    .limit(max_opps_per_merchant)
                    .all()
                )
                for o in avail_opps:
                    o.status = OpportunityStatus.RECOVERED.value
                    o.actual_recovered_value = o.gross_value_affected
                    o.recovery_probability = Decimal("0.9400")
                    if o.payment:
                        o.payment.status = PaymentStatus.RECOVERED.value
                opps = avail_opps

            for opp in opps:
                agent_dec = db.query(AgentDecision).filter(AgentDecision.opportunity_id == opp.id).first()
                if not agent_dec:
                    agent_dec = AgentDecision(
                        id=uuid.uuid4(),
                        opportunity_id=opp.id,
                        problem="Detected upstream gateway timeout on primary payment route.",
                        evidence_json={"evidence": opp.explanation or "Multiple timeout responses recorded during evening peak window."},
                        estimated_impact=opp.gross_value_affected,
                        recovery_probability=opp.recovery_probability,
                        recommended_action="CREATE_PAYMENT_LINK",
                        reason="Customer has strong payment history; high probability of immediate recovery.",
                        risk_level="low",
                        expected_recovery=opp.expected_recovered_value,
                        actual_recovery=opp.actual_recovered_value or Decimal("0.00"),
                        currency="INR",
                        created_at=opp.created_at + timedelta(seconds=12)
                    )
                    db.add(agent_dec)
                    db.flush()

                pol_dec = db.query(PolicyDecision).filter(PolicyDecision.opportunity_id == opp.id).first()
                if not pol_dec:
                    pol_dec = PolicyDecision(
                        id=uuid.uuid4(),
                        agent_decision_id=agent_dec.id,
                        opportunity_id=opp.id,
                        action_type="CREATE_PAYMENT_LINK",
                        allowed=True,
                        approval_required=False,
                        risk_level="low",
                        decision_reason="Rule: Low risk + confidence >= 0.80 allows automatic recovery link creation.",
                        limits_json={"max_amount": 50000.0, "cooldown_hours": 24},
                        created_at=opp.created_at + timedelta(seconds=15)
                    )
                    db.add(pol_dec)
                    db.flush()

                act = db.query(RecoveryAction).filter(RecoveryAction.opportunity_id == opp.id).first()
                if not act:
                    act = RecoveryAction(
                        id=uuid.uuid4(),
                        opportunity_id=opp.id,
                        agent_decision_id=agent_dec.id,
                        policy_decision_id=pol_dec.id,
                        provider="razorpay_test",
                        action_type=ActionType.CREATE_PAYMENT_LINK.value,
                        status=ActionStatus.SUCCESS.value,
                        amount=opp.actual_recovered_value or opp.gross_value_affected,
                        request={"customer_name": "Valued Customer", "auto_expire": False},
                        result={
                            "id": f"plink_{uuid.uuid4().hex[:12]}",
                            "short_url": f"https://rzp.io/i/{uuid.uuid4().hex[:8]}",
                            "status": "paid"
                        },
                        reason="Automated recovery link generated and sent to customer.",
                        created_at=opp.created_at + timedelta(seconds=18),
                        completed_at=opp.created_at + timedelta(minutes=4, seconds=22)
                    )
                    db.add(act)
                    db.flush()

                existing_ev = db.query(AuditEvent).filter(AuditEvent.action_id == act.id).first()
                if existing_ev:
                    continue

                t0 = opp.created_at
                tx = opp.payment
                method_str = tx.payment_method if tx else "upi"
                bank_str = tx.bank if tx else "HDFC"
                err_code = (tx.attempts[0].error_code if tx and tx.attempts else "GATEWAY_TIMEOUT")
                err_reason = (tx.attempts[0].failure_reason if tx and tx.attempts else "Bank server timeout")

                # Stage 1: Transaction detected
                audit_svc.record_event(
                    merchant_id=m.id,
                    event_type=AuditEventType.TRANSACTION_DETECTED,
                    actor=AuditActor.SYSTEM,
                    transaction_id=tx.id if tx else None,
                    status="FAILED",
                    summary=f"Transaction detected: ₹{opp.gross_value_affected:,.2f} on {method_str.upper()} ({bank_str}). Status: FAILED ({err_code}).",
                    metadata={"amount": float(opp.gross_value_affected), "payment_method": method_str, "bank": bank_str, "error_code": err_code, "failure_reason": err_reason},
                    timestamp=t0
                )

                # Stage 2: Revenue leak detected
                audit_svc.record_event(
                    merchant_id=m.id,
                    event_type=AuditEventType.REVENUE_LEAK_DETECTED,
                    actor=AuditActor.SYSTEM,
                    status="WARNING",
                    summary=f"Revenue leak pattern matched: payment_degradation on {bank_str} {method_str.upper()}.",
                    metadata={"leak_id": str(opp.revenue_leak_id) if opp.revenue_leak_id else None, "leak_type": "payment_degradation", "severity": "critical", "revenue_at_risk": float(opp.gross_value_affected)},
                    timestamp=t0 + timedelta(seconds=5)
                )

                # Stage 3: ML prediction
                audit_svc.record_event(
                    merchant_id=m.id,
                    event_type=AuditEventType.ML_PREDICTION,
                    actor=AuditActor.SYSTEM,
                    transaction_id=tx.id if tx else None,
                    status="SUCCESS",
                    summary=f"ML Recovery Model v1.2: estimated recovery probability {float(opp.recovery_probability):.1%}.",
                    metadata={"model_name": "payment_recovery_probability_v1.2", "prediction": float(opp.recovery_probability), "confidence": 0.88, "features_used": ["bank_health", "amount_bucket", "customer_tenure", "dow_tod"]},
                    timestamp=t0 + timedelta(seconds=8)
                )

                # Stage 4: Opportunity created
                audit_svc.record_event(
                    merchant_id=m.id,
                    event_type=AuditEventType.OPPORTUNITY_CREATED,
                    actor=AuditActor.SYSTEM,
                    opportunity_id=opp.id,
                    transaction_id=tx.id if tx else None,
                    status="SUCCESS",
                    summary=f"Recovery opportunity created: ₹{opp.gross_value_affected:,.2f} ({opp.priority} priority, Expected: ₹{opp.expected_recovered_value:,.2f}).",
                    metadata={"gross_value": float(opp.gross_value_affected), "recovery_probability": float(opp.recovery_probability), "expected_recovery": float(opp.expected_recovered_value), "priority": opp.priority},
                    timestamp=t0 + timedelta(seconds=10)
                )

                # Stage 5: AI investigation
                audit_svc.record_event(
                    merchant_id=m.id,
                    event_type=AuditEventType.AI_INVESTIGATION,
                    actor=AuditActor.AI_RECOVERY_AGENT,
                    opportunity_id=opp.id,
                    agent_decision_id=agent_dec.id,
                    status="SUCCESS",
                    summary=f"AI Agent diagnosis: {agent_dec.problem}",
                    metadata={"evidence": agent_dec.evidence_json, "tools_called": ["get_failure_analysis", "get_customer_history", "estimate_recoverable_revenue"]},
                    timestamp=t0 + timedelta(seconds=12)
                )

                # Stage 6: AI recommendation
                audit_svc.record_event(
                    merchant_id=m.id,
                    event_type=AuditEventType.AI_RECOMMENDATION,
                    actor=AuditActor.AI_RECOVERY_AGENT,
                    opportunity_id=opp.id,
                    agent_decision_id=agent_dec.id,
                    status="SUCCESS",
                    summary=f"AI recommended action: {agent_dec.recommended_action} (Risk: {agent_dec.risk_level}).",
                    metadata={"recommended_action": agent_dec.recommended_action, "reason": agent_dec.reason, "risk_level": agent_dec.risk_level},
                    timestamp=t0 + timedelta(seconds=14)
                )

                # Stage 7: Policy decision
                audit_svc.record_event(
                    merchant_id=m.id,
                    event_type=AuditEventType.POLICY_DECISION,
                    actor=AuditActor.POLICY_ENGINE,
                    opportunity_id=opp.id,
                    policy_decision_id=pol_dec.id,
                    status="SUCCESS",
                    summary=f"Policy gate allowed action '{pol_dec.action_type}'. Approval required: {pol_dec.approval_required}.",
                    metadata={"action": pol_dec.action_type, "allowed": pol_dec.allowed, "approval_required": pol_dec.approval_required, "reason": pol_dec.decision_reason},
                    timestamp=t0 + timedelta(seconds=15)
                )

                # Stage 8: Approval (Auto-approval record)
                audit_svc.record_event(
                    merchant_id=m.id,
                    event_type=AuditEventType.APPROVAL,
                    actor=AuditActor.POLICY_ENGINE,
                    opportunity_id=opp.id,
                    action_id=act.id,
                    status="SUCCESS",
                    summary="Action automatically approved based on merchant policy low-risk tier.",
                    metadata={"approved": True, "approval_mode": "AUTOMATIC_POLICY_GRANT"},
                    timestamp=t0 + timedelta(seconds=16)
                )

                # Stage 9: Recovery action
                audit_svc.record_event(
                    merchant_id=m.id,
                    event_type=AuditEventType.RECOVERY_ACTION,
                    actor=AuditActor.SYSTEM,
                    opportunity_id=opp.id,
                    action_id=act.id,
                    status="SUCCESS",
                    summary=f"Recovery action '{act.action_type}' dispatched to provider '{act.provider}' for ₹{act.amount:,.2f}.",
                    metadata={"action_type": act.action_type, "provider": act.provider, "request": act.request},
                    timestamp=t0 + timedelta(seconds=18)
                )

                # Stage 10: Provider response
                audit_svc.record_event(
                    merchant_id=m.id,
                    event_type=AuditEventType.PROVIDER_RESPONSE,
                    actor=AuditActor.RAZORPAY_TEST_PROVIDER,
                    opportunity_id=opp.id,
                    action_id=act.id,
                    status="SUCCESS",
                    summary=f"Provider '{act.provider}' created payment link #{act.result.get('id', 'plink_xxx')}.",
                    metadata={"provider": act.provider, "response": act.result},
                    timestamp=t0 + timedelta(seconds=20)
                )

                # Stage 11: Webhook
                audit_svc.record_event(
                    merchant_id=m.id,
                    event_type=AuditEventType.WEBHOOK,
                    actor=AuditActor.WEBHOOK_ENGINE,
                    opportunity_id=opp.id,
                    action_id=act.id,
                    transaction_id=tx.id if tx else None,
                    status="SUCCESS",
                    summary="Gateway webhook received: 'payment.captured'. Signature verified via HMAC-SHA256.",
                    metadata={"event": "payment.captured", "payment_link_id": act.result.get("id"), "amount": float(opp.actual_recovered_value or opp.gross_value_affected)},
                    timestamp=t0 + timedelta(minutes=4, seconds=15)
                )

                # Stage 12: Recovery verification
                audit_svc.record_event(
                    merchant_id=m.id,
                    event_type=AuditEventType.RECOVERY_VERIFICATION,
                    actor=AuditActor.SYSTEM,
                    opportunity_id=opp.id,
                    action_id=act.id,
                    status="SUCCESS",
                    summary="Recovery verification passed: Razorpay payment status confirmed as CAPTURED.",
                    metadata={"verified": True, "verification_method": "GATEWAY_HMAC_AND_STATUS_POLL"},
                    timestamp=t0 + timedelta(minutes=4, seconds=18)
                )

                # Stage 13: Final recovered amount
                audit_svc.record_event(
                    merchant_id=m.id,
                    event_type=AuditEventType.FINAL_RECOVERED_AMOUNT,
                    actor=AuditActor.SYSTEM,
                    opportunity_id=opp.id,
                    action_id=act.id,
                    status="SUCCESS",
                    summary=f"Final revenue recovery confirmed: ₹{float(opp.actual_recovered_value or opp.gross_value_affected):,.2f} credited to merchant ledger.",
                    metadata={"recovered_amount": float(opp.actual_recovered_value or opp.gross_value_affected), "currency": "INR", "settled": True},
                    timestamp=t0 + timedelta(minutes=4, seconds=22)
                )
                total_seeded_events += 13

        db.commit()
        return total_seeded_events
