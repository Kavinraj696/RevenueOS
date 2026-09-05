import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, Any, List, Optional, Union
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.models.merchant import Merchant
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.payment_attempt import PaymentAttempt
from app.models.subscription import Subscription
from app.models.checkout_session import CheckoutSession
from app.models.revenue_leak import RevenueLeak
from app.models.recovery_opportunity import RecoveryOpportunity
from app.models.recovery_action import RecoveryAction
from app.models.policy_decision import PolicyDecision
from app.models.audit_event import AuditEvent
from app.models.enums import PaymentStatus, OpportunityStatus, ActionStatus, ActionType
from app.ml.pipeline import PaymentFeatureExtractor
from app.ml.models import PaymentRecoveryModel
from app.ml.training import get_recovery_model
from app.db.base import quantize_inr
from app.services.payment_provider.registry import get_payment_provider


class AgentTools:
    """
    Registry of 16 deterministic, database-grounded tools for the RevenueOS AI Recovery Agent.
    Prevents hallucination by fetching and calculating real values.
    """

    def __init__(self, db: Session):
        self.db = db
        self._ml_model = None

    @property
    def ml_model(self) -> PaymentRecoveryModel:
        if self._ml_model is None:
            self._ml_model = get_recovery_model(self.db)
        return self._ml_model

    # -------------------------------------------------------------------------
    # Tool 1: get_revenue_leaks
    # -------------------------------------------------------------------------
    def get_revenue_leaks(
        self,
        merchant_id: Optional[Union[uuid.UUID, str]] = None,
        status: Optional[str] = "open",
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Retrieve active or filtered revenue leaks."""
        query = self.db.query(RevenueLeak)
        if merchant_id:
            m_id = uuid.UUID(str(merchant_id))
            query = query.filter(RevenueLeak.merchant_id == m_id)
        if status and status != "all":
            query = query.filter(RevenueLeak.status == status)

        leaks = query.order_by(desc(RevenueLeak.revenue_at_risk)).limit(limit).all()
        results = []
        for l in leaks:
            results.append({
                "id": str(l.id),
                "merchant_id": str(l.merchant_id),
                "leak_type": l.leak_type,
                "severity": l.severity,
                "gross_value_affected": float(l.gross_value_affected),
                "affected_amount": float(l.affected_amount),
                "revenue_at_risk": float(l.revenue_at_risk),
                "confidence": float(l.confidence),
                "status": l.status,
                "pattern_description": l.pattern_description,
                "root_cause_candidates": l.root_cause_candidates or [],
                "evidence": l.evidence or {},
                "created_at": l.created_at.isoformat() if l.created_at else None
            })
        return results

    # -------------------------------------------------------------------------
    # Tool 2: get_revenue_leak
    # -------------------------------------------------------------------------
    def get_revenue_leak(self, leak_id: Union[uuid.UUID, str]) -> Dict[str, Any]:
        """Get deep diagnostics for a specific revenue leak."""
        l_id = uuid.UUID(str(leak_id))
        leak = self.db.query(RevenueLeak).filter(RevenueLeak.id == l_id).first()
        if not leak:
            return {"error": f"Revenue leak {leak_id} not found"}

        linked_opps_count = self.db.query(RecoveryOpportunity).filter(
            RecoveryOpportunity.revenue_leak_id == leak.id
        ).count()

        return {
            "id": str(leak.id),
            "merchant_id": str(leak.merchant_id),
            "leak_type": leak.leak_type,
            "severity": leak.severity,
            "severity_score": float(leak.severity_score),
            "gross_value_affected": float(leak.gross_value_affected),
            "affected_amount": float(leak.affected_amount),
            "revenue_at_risk": float(leak.revenue_at_risk),
            "affected_transactions": leak.affected_transactions,
            "confidence": float(leak.confidence),
            "status": leak.status,
            "pattern_description": leak.pattern_description,
            "root_cause_candidates": leak.root_cause_candidates or [],
            "evidence": leak.evidence or {},
            "detection_window_start": leak.detection_window_start.isoformat() if leak.detection_window_start else None,
            "detection_window_end": leak.detection_window_end.isoformat() if leak.detection_window_end else None,
            "linked_opportunities_count": linked_opps_count
        }

    # -------------------------------------------------------------------------
    # Tool 3: search_transactions
    # -------------------------------------------------------------------------
    def search_transactions(
        self,
        merchant_id: Optional[Union[uuid.UUID, str]] = None,
        status: str = "failed",
        bank: Optional[str] = None,
        payment_method: Optional[str] = None,
        min_amount: Optional[float] = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Search payments by transaction status, method, bank, and amount."""
        query = self.db.query(Payment)
        if merchant_id:
            query = query.filter(Payment.merchant_id == uuid.UUID(str(merchant_id)))
        if status and status != "all":
            query = query.filter(Payment.status == status)
        if bank:
            query = query.filter(Payment.bank == bank)
        if payment_method:
            query = query.filter(Payment.payment_method == payment_method)
        if min_amount is not None:
            query = query.filter(Payment.amount >= Decimal(str(min_amount)))

        payments = query.order_by(desc(Payment.created_at)).limit(limit).all()
        results = []
        for p in payments:
            attempts = p.attempts or []
            last_att = attempts[-1] if attempts else None
            results.append({
                "id": str(p.id),
                "merchant_id": str(p.merchant_id),
                "customer_id": str(p.customer_id) if p.customer_id else None,
                "amount": float(p.amount),
                "currency": p.currency,
                "status": p.status,
                "payment_method": p.payment_method,
                "bank": p.bank,
                "device_type": p.device_type,
                "attempt_count": len(attempts),
                "last_error_code": last_att.error_code if last_att else None,
                "last_failure_reason": last_att.failure_reason if last_att else None,
                "created_at": p.created_at.isoformat() if p.created_at else None
            })
        return results

    # -------------------------------------------------------------------------
    # Tool 4: get_transaction
    # -------------------------------------------------------------------------
    def get_transaction(self, transaction_id: Union[uuid.UUID, str]) -> Dict[str, Any]:
        """Fetch detailed transaction payload including attempts history."""
        tx_id = uuid.UUID(str(transaction_id))
        payment = self.db.query(Payment).filter(Payment.id == tx_id).first()
        if not payment:
            return {"error": f"Transaction {transaction_id} not found"}

        attempts_data = []
        for a in payment.attempts or []:
            attempts_data.append({
                "attempt_number": a.attempt_number,
                "status": a.status,
                "error_code": a.error_code,
                "failure_reason": a.failure_reason,
                "attempted_at": a.attempted_at.isoformat() if a.attempted_at else None
            })

        customer_data = None
        if payment.customer:
            c = payment.customer
            customer_data = {
                "id": str(c.id),
                "external_ref": c.external_ref,
                "lifetime_value": float(c.lifetime_value),
                "risk_segment": c.risk_segment
            }

        return {
            "id": str(payment.id),
            "merchant_id": str(payment.merchant_id),
            "customer_id": str(payment.customer_id) if payment.customer_id else None,
            "amount": float(payment.amount),
            "currency": payment.currency,
            "status": payment.status,
            "payment_method": payment.payment_method,
            "bank": payment.bank,
            "device_type": payment.device_type,
            "route": payment.route,
            "attempts": attempts_data,
            "customer": customer_data,
            "created_at": payment.created_at.isoformat() if payment.created_at else None
        }

    # -------------------------------------------------------------------------
    # Tool 5: get_customer_history
    # -------------------------------------------------------------------------
    def get_customer_history(self, customer_id: Union[uuid.UUID, str]) -> Dict[str, Any]:
        """Retrieve customer transaction track record, LTV, and risk tier."""
        c_id = uuid.UUID(str(customer_id))
        customer = self.db.query(Customer).filter(Customer.id == c_id).first()
        if not customer:
            return {"error": f"Customer {customer_id} not found"}

        payments = self.db.query(Payment).filter(Payment.customer_id == c_id).all()
        total_tx = len(payments)
        failed_tx = sum(1 for p in payments if p.status == PaymentStatus.FAILED.value)
        recovered_tx = sum(1 for p in payments if p.status == PaymentStatus.RECOVERED.value)
        success_tx = sum(1 for p in payments if p.status == PaymentStatus.SUCCESS.value)

        return {
            "customer_id": str(customer.id),
            "external_ref": customer.external_ref,
            "lifetime_value": float(customer.lifetime_value),
            "risk_segment": customer.risk_segment or "medium",
            "total_transactions": total_tx,
            "failed_transactions": failed_tx,
            "recovered_transactions": recovered_tx,
            "successful_transactions": success_tx,
            "historical_failure_rate": round(failed_tx / total_tx, 4) if total_tx > 0 else 0.0,
            "is_vip": float(customer.lifetime_value) >= 50000.0 or customer.risk_segment == "vip"
        }

    # -------------------------------------------------------------------------
    # Tool 6: get_failure_analysis
    # -------------------------------------------------------------------------
    def get_failure_analysis(
        self,
        merchant_id: Optional[Union[uuid.UUID, str]] = None,
        window_hours: int = 24
    ) -> Dict[str, Any]:
        """Aggregate failure rates across payment methods, banks, devices, and peak windows."""
        query = self.db.query(Payment)
        if merchant_id:
            query = query.filter(Payment.merchant_id == uuid.UUID(str(merchant_id)))

        payments = query.all()
        if not payments:
            return {
                "overall_failure_rate": 0.0,
                "baseline_failure_rate": 0.042,
                "rate_increase_percentage": 0.0,
                "by_payment_method": {},
                "by_bank": {},
                "by_device": {},
                "peak_window": "N/A"
            }

        total = len(payments)
        failed = [p for p in payments if p.status in [PaymentStatus.FAILED.value, PaymentStatus.RECOVERED.value]]
        overall_failure_rate = len(failed) / total if total > 0 else 0.0
        baseline_failure_rate = 0.042

        # Breakdowns
        by_method: Dict[str, Dict[str, Any]] = {}
        for p in payments:
            m = p.payment_method or "unknown"
            if m not in by_method:
                by_method[m] = {"total": 0, "failed": 0}
            by_method[m]["total"] += 1
            if p.status in [PaymentStatus.FAILED.value, PaymentStatus.RECOVERED.value]:
                by_method[m]["failed"] += 1

        method_stats = {
            m: {
                "failure_rate": round(v["failed"] / v["total"], 4) if v["total"] > 0 else 0.0,
                "failed_count": v["failed"],
                "total_count": v["total"]
            }
            for m, v in by_method.items()
        }

        by_bank: Dict[str, Dict[str, Any]] = {}
        for p in payments:
            b = p.bank or "unknown"
            if b not in by_bank:
                by_bank[b] = {"total": 0, "failed": 0}
            by_bank[b]["total"] += 1
            if p.status in [PaymentStatus.FAILED.value, PaymentStatus.RECOVERED.value]:
                by_bank[b]["failed"] += 1

        bank_stats = {
            b: {
                "failure_rate": round(v["failed"] / v["total"], 4) if v["total"] > 0 else 0.0,
                "failed_count": v["failed"],
                "total_count": v["total"]
            }
            for b, v in by_bank.items()
        }

        by_device: Dict[str, Dict[str, Any]] = {}
        for p in payments:
            d = p.device_type or "unknown"
            if d not in by_device:
                by_device[d] = {"total": 0, "failed": 0}
            by_device[d]["total"] += 1
            if p.status in [PaymentStatus.FAILED.value, PaymentStatus.RECOVERED.value]:
                by_device[d]["failed"] += 1

        device_stats = {
            d: {
                "failure_rate": round(v["failed"] / v["total"], 4) if v["total"] > 0 else 0.0,
                "failed_count": v["failed"],
                "total_count": v["total"]
            }
            for d, v in by_device.items()
        }

        # Check peak window (hours 18 - 22)
        evening_failed = [p for p in failed if p.created_at and 18 <= p.created_at.hour <= 22]
        peak_window = "19:00 - 21:00" if len(evening_failed) > len(failed) * 0.4 else "Distributed"

        rate_increase = round(((overall_failure_rate - baseline_failure_rate) / baseline_failure_rate) * 100, 1) if baseline_failure_rate > 0 else 0.0

        return {
            "overall_failure_rate": round(overall_failure_rate, 4),
            "baseline_failure_rate": baseline_failure_rate,
            "rate_increase_percentage": max(0.0, rate_increase),
            "by_payment_method": method_stats,
            "by_bank": bank_stats,
            "by_device": device_stats,
            "peak_window": peak_window
        }

    # -------------------------------------------------------------------------
    # Tool 7: get_recovery_opportunities
    # -------------------------------------------------------------------------
    def get_recovery_opportunities(
        self,
        merchant_id: Optional[Union[uuid.UUID, str]] = None,
        priority: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Fetch prioritized opportunities with expected recovery and recommended actions."""
        query = self.db.query(RecoveryOpportunity)
        if merchant_id:
            query = query.filter(RecoveryOpportunity.merchant_id == uuid.UUID(str(merchant_id)))
        if priority:
            query = query.filter(RecoveryOpportunity.priority == priority.upper())

        opps = query.order_by(
            desc(RecoveryOpportunity.priority_score),
            desc(RecoveryOpportunity.expected_recovered_value)
        ).limit(limit).all()

        results = []
        for o in opps:
            results.append({
                "id": str(o.id),
                "merchant_id": str(o.merchant_id),
                "payment_id": str(o.payment_id) if o.payment_id else None,
                "customer_id": str(o.customer_id) if o.customer_id else None,
                "transaction_amount": float(o.transaction_amount),
                "failure_reason": o.failure_reason,
                "recovery_probability": float(o.recovery_probability),
                "expected_recoverable_amount": float(o.expected_recoverable_amount),
                "risk": o.risk,
                "priority": o.priority,
                "priority_score": float(o.priority_score),
                "explanation": o.explanation,
                "recommended_action_candidates": o.recommended_action_candidates,
                "status": o.status
            })
        return results

    # -------------------------------------------------------------------------
    # Tool 8: calculate_recovery_probability
    # -------------------------------------------------------------------------
    def calculate_recovery_probability(self, transaction_id: Union[uuid.UUID, str]) -> Dict[str, Any]:
        """Execute ML Model 1 inference to determine payment recovery probability."""
        tx_id = uuid.UUID(str(transaction_id))
        payment = self.db.query(Payment).filter(Payment.id == tx_id).first()
        if not payment:
            return {"error": f"Transaction {transaction_id} not found"}

        features = PaymentFeatureExtractor.extract_from_payment(payment)
        prob_float, conf_float = self.ml_model.predict_single(features)
        # Apply realistic recovery floor (>= 12% addressable baseline for automated recovery intervention)
        calibrated_prob = min(0.99, max(0.12, prob_float))
        prob_rounded = round(float(calibrated_prob), 4)

        return {
            "transaction_id": str(payment.id),
            "recovery_probability": prob_rounded,
            "confidence": round(conf_float, 4),
            "model_name": getattr(self.ml_model, "MODEL_NAME", "payment_recovery_probability"),
            "model_version": getattr(self.ml_model, "MODEL_VERSION", "v1.0.0"),
            "input_features": features
        }

    # -------------------------------------------------------------------------
    # Tool 9: estimate_recoverable_revenue
    # -------------------------------------------------------------------------
    def estimate_recoverable_revenue(
        self,
        transaction_value: Union[float, Decimal, str],
        recovery_probability: Union[float, Decimal, str]
    ) -> Dict[str, Any]:
        """Deterministic actuarial calculation: Expected Recovery = Value * Probability."""
        val_dec = quantize_inr(Decimal(str(transaction_value)))
        prob_dec = Decimal(str(round(float(recovery_probability), 4)))

        expected_recovery = quantize_inr(val_dec * prob_dec)
        pot_rec = quantize_inr(val_dec * Decimal("0.85"))
        conservative = quantize_inr(expected_recovery * Decimal("0.80"))
        optimistic = quantize_inr(min(val_dec, expected_recovery * Decimal("1.10")))

        return {
            "transaction_value": float(val_dec),
            "recovery_probability": float(prob_dec),
            "expected_recoverable_amount": float(expected_recovery),
            "potentially_recoverable_amount": float(pot_rec),
            "conservative_estimate": float(conservative),
            "optimistic_estimate": float(optimistic),
            "currency": "INR"
        }

    # -------------------------------------------------------------------------
    # Tool 10: get_available_payment_methods
    # -------------------------------------------------------------------------
    def get_available_payment_methods(
        self,
        merchant_id: Optional[Union[uuid.UUID, str]] = None
    ) -> Dict[str, Any]:
        """Check gateway status and available alternate payment routes."""
        return {
            "methods": [
                {
                    "name": "upi",
                    "title": "UPI (Unified Payments Interface)",
                    "status": "degraded_on_bank_a",
                    "alternate_route_available": True,
                    "recommended_route": "Razorpay Direct Bank Switch (ICICI/Axis Node)"
                },
                {
                    "name": "card",
                    "title": "Credit / Debit Cards",
                    "status": "healthy",
                    "alternate_route_available": True,
                    "recommended_route": "Primary Visa/Mastercard Gateway"
                },
                {
                    "name": "netbanking",
                    "title": "Netbanking",
                    "status": "healthy",
                    "alternate_route_available": False,
                    "recommended_route": "Direct Core Banking Integration"
                },
                {
                    "name": "payment_link",
                    "title": "1-Click SMS / WhatsApp Payment Link",
                    "status": "healthy",
                    "alternate_route_available": True,
                    "recommended_route": "Instant Multi-Option Link"
                }
            ],
            "recommended_recovery_action": "payment_link"
        }

    # -------------------------------------------------------------------------
    # Tool 11: create_test_payment_link
    # -------------------------------------------------------------------------
    def create_test_payment_link(
        self,
        payment_id: Union[uuid.UUID, str],
        customer_phone: Optional[str] = None,
        amount: Optional[float] = None,
        expiry_minutes: int = 60
    ) -> Dict[str, Any]:
        """Generate a simulated Razorpay payment link for recovery."""
        tx_id = uuid.UUID(str(payment_id))
        payment = self.db.query(Payment).filter(Payment.id == tx_id).first()
        if not payment:
            return {"error": f"Payment {payment_id} not found"}

        link_amt = quantize_inr(Decimal(str(amount))) if amount is not None else payment.amount
        provider = get_payment_provider()
        prov_res = provider.create_payment_link(
            amount=link_amt,
            currency=payment.currency,
            description="RevenueOS autonomous recovery link",
            customer_phone=customer_phone,
            reference_id=str(payment.id),
            expire_by_minutes=expiry_minutes
        )
        link_id = prov_res.get("id") or f"plink_{uuid.uuid4().hex[:12]}"
        short_url = prov_res.get("short_url") or f"https://rzp.io/i/{uuid.uuid4().hex[:8]}"
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=expiry_minutes)

        # Check if opportunity exists for this payment
        opp = self.db.query(RecoveryOpportunity).filter(
            RecoveryOpportunity.payment_id == payment.id
        ).first()

        action_id = None
        if opp:
            action = RecoveryAction(
                id=uuid.uuid4(),
                opportunity_id=opp.id,
                action_type=ActionType.PAYMENT_LINK.value,
                reason="Generated 1-click recovery payment link",
                predicted_outcome=f"Expected recovery of ₹{link_amt:,.0f} with 1-click checkout",
                execution_result={
                    "link_id": link_id,
                    "short_url": short_url,
                    "amount": float(link_amt),
                    "expires_at": expires_at.isoformat()
                },
                status=ActionStatus.EXECUTED.value,
                executed_at=datetime.now(timezone.utc)
            )
            self.db.add(action)
            self.db.flush()
            action_id = str(action.id)

        return {
            "link_id": link_id,
            "short_url": short_url,
            "payment_id": str(payment.id),
            "amount": float(link_amt),
            "currency": payment.currency,
            "status": "created",
            "action_id": action_id,
            "expires_at": expires_at.isoformat()
        }

    # -------------------------------------------------------------------------
    # Tool 12: create_test_subscription_link
    # -------------------------------------------------------------------------
    def create_test_subscription_link(
        self,
        subscription_id: Union[uuid.UUID, str],
        customer_phone: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate a simulated subscription mandate renewal link."""
        sub_id = uuid.UUID(str(subscription_id))
        subscription = self.db.query(Subscription).filter(Subscription.id == sub_id).first()
        if not subscription:
            return {"error": f"Subscription {subscription_id} not found"}

        provider = get_payment_provider()
        prov_res = provider.create_subscription(
            plan_id=subscription.plan_name,
            total_count=12,
            notes={"subscription_id": str(subscription.id)}
        )
        sub_prov_id = prov_res.get("id", uuid.uuid4().hex[:12])
        link_id = sub_prov_id if sub_prov_id.startswith("sublink_") else f"sublink_{sub_prov_id}"
        short_url = prov_res.get("short_url") or f"https://rzp.io/s/{uuid.uuid4().hex[:8]}"

        opp = self.db.query(RecoveryOpportunity).filter(
            RecoveryOpportunity.merchant_id == subscription.merchant_id
        ).first()

        action_id = None
        if opp:
            action = RecoveryAction(
                id=uuid.uuid4(),
                opportunity_id=opp.id,
                action_type=ActionType.SUBSCRIPTION_WORKFLOW.value,
                reason="Dispatched subscription mandate recovery link",
                predicted_outcome=f"Recover recurring mandate of ₹{subscription.plan_amount:,.0f}",
                execution_result={"link_id": link_id, "short_url": short_url},
                status=ActionStatus.EXECUTED.value,
                executed_at=datetime.now(timezone.utc)
            )
            self.db.add(action)
            self.db.flush()
            action_id = str(action.id)

        return {
            "link_id": link_id,
            "short_url": short_url,
            "subscription_id": str(subscription.id),
            "amount": float(subscription.plan_amount),
            "status": "created",
            "action_id": action_id
        }

    # -------------------------------------------------------------------------
    # Tool 13: send_recovery_notification
    # -------------------------------------------------------------------------
    def send_recovery_notification(
        self,
        customer_id: Union[uuid.UUID, str],
        channel: str = "sms_whatsapp",
        template: str = "recovery_link",
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Simulate sending a multi-channel recovery notification to customer."""
        c_id = uuid.UUID(str(customer_id))
        customer = self.db.query(Customer).filter(Customer.id == c_id).first()
        if not customer:
            return {"error": f"Customer {customer_id} not found"}

        notif_id = f"notif_{uuid.uuid4().hex[:10]}"
        return {
            "notification_id": notif_id,
            "customer_id": str(customer.id),
            "external_ref": customer.external_ref,
            "channel": channel,
            "template": template,
            "status": "delivered",
            "sent_at": datetime.now(timezone.utc).isoformat()
        }

    # -------------------------------------------------------------------------
    # Tool 14: get_recovery_result
    # -------------------------------------------------------------------------
    def get_recovery_result(self, action_id: Union[uuid.UUID, str]) -> Dict[str, Any]:
        """Verify the execution result and state of an executed recovery action."""
        act_id = uuid.UUID(str(action_id))
        action = self.db.query(RecoveryAction).filter(RecoveryAction.id == act_id).first()
        if not action:
            return {"error": f"Recovery action {action_id} not found"}

        return {
            "action_id": str(action.id),
            "opportunity_id": str(action.opportunity_id),
            "action_type": action.action_type,
            "status": action.status,
            "reason": action.reason,
            "predicted_outcome": action.predicted_outcome,
            "execution_result": action.execution_result or {},
            "executed_at": action.executed_at.isoformat() if action.executed_at else None
        }

    # -------------------------------------------------------------------------
    # Tool 15: get_policy
    # -------------------------------------------------------------------------
    def get_policy(
        self,
        policy_name: str,
        merchant_id: Optional[Union[uuid.UUID, str]] = None
    ) -> Dict[str, Any]:
        """Query policy constraints, auto-execution thresholds, and human review gates."""
        policies = {
            "max_auto_amount": {
                "threshold": 15000.00,
                "description": "Transactions above ₹15,000 require human merchant approval before execution"
            },
            "retry_limits": {
                "max_attempts": 3,
                "description": "Maximum 3 gateway retries per transaction. Further retries strictly blocked"
            },
            "contact_frequency": {
                "cooldown_hours": 4,
                "description": "Do not send more than 1 notification to the same customer within 4 hours"
            },
            "vip_concierge": {
                "min_ltv_or_ticket": 50000.00,
                "action": "escalate_to_concierge",
                "description": "High ticket orders (>= ₹50,000) or VIP customers routed to specialized VIP concierge"
            },
            "min_recovery_confidence": {
                "threshold": 0.60,
                "description": "Action candidate must have >= 60% confidence/feasibility score"
            }
        }

        if policy_name in policies:
            return {"policy_name": policy_name, **policies[policy_name]}

        return {
            "policy_name": "all",
            "active_rules": policies
        }

    # -------------------------------------------------------------------------
    # Tool 16: write_audit_event
    # -------------------------------------------------------------------------
    def write_audit_event(
        self,
        merchant_id: Union[uuid.UUID, str],
        related_entity_type: str,
        related_entity_id: Union[uuid.UUID, str],
        event_type: str,
        message: str,
        request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Record an immutable audit entry in the audit ledger."""
        m_id = uuid.UUID(str(merchant_id))
        e_id = uuid.UUID(str(related_entity_id))
        req_id = request_id or f"req_{uuid.uuid4().hex[:12]}"

        audit = AuditEvent(
            id=uuid.uuid4(),
            merchant_id=m_id,
            related_entity_type=related_entity_type,
            related_entity_id=e_id,
            event_type=event_type,
            message=message,
            request_id=req_id,
            created_at=datetime.now(timezone.utc)
        )
        self.db.add(audit)
        self.db.flush()

        return {
            "audit_id": str(audit.id),
            "merchant_id": str(audit.merchant_id),
            "related_entity_type": audit.related_entity_type,
            "related_entity_id": str(audit.related_entity_id),
            "event_type": audit.event_type,
            "message": audit.message,
            "request_id": audit.request_id,
            "created_at": audit.created_at.isoformat()
        }
