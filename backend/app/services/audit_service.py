import uuid
from decimal import Decimal
from datetime import datetime, timezone, date
from typing import Optional, Dict, Any, List, Union, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.models.audit_event import AuditEvent
from app.models.recovery_action import RecoveryAction
from app.models.recovery_opportunity import RecoveryOpportunity
from app.models.enums import AuditEventType, AuditActor


SENSITIVE_KEY_PATTERNS = {
    "secret", "key_secret", "webhook_secret", "authorization", "auth",
    "password", "api_secret", "private_key", "token", "signature_secret"
}


def sanitize_metadata(data: Any) -> Any:
    """Recursively redact secrets and sensitive credentials from audit metadata."""
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(pattern in k_lower for pattern in SENSITIVE_KEY_PATTERNS):
                cleaned[k] = "[REDACTED]"
            elif k_lower == "key_id" and isinstance(v, str) and len(v) > 8:
                # Mask key id
                cleaned[k] = f"{v[:6]}...{v[-4:]}"
            else:
                cleaned[k] = sanitize_metadata(v)
        return cleaned
    elif isinstance(data, list):
        return [sanitize_metadata(item) for item in data]
    elif isinstance(data, Decimal):
        return float(data)
    elif isinstance(data, uuid.UUID):
        return str(data)
    elif isinstance(data, datetime):
        return data.isoformat()
    return data


class AuditService:
    """
    Service for writing and querying immutable-style audit records in RevenueOS.
    Ensures end-to-end operational traceability without exposing secrets.
    """

    def __init__(self, db: Session):
        self.db = db

    def record_event(
        self,
        merchant_id: uuid.UUID,
        event_type: Union[str, AuditEventType],
        summary: str,
        actor: Union[str, AuditActor] = AuditActor.SYSTEM.value,
        transaction_id: Optional[uuid.UUID] = None,
        opportunity_id: Optional[uuid.UUID] = None,
        action_id: Optional[uuid.UUID] = None,
        agent_decision_id: Optional[uuid.UUID] = None,
        policy_decision_id: Optional[uuid.UUID] = None,
        status: str = "SUCCESS",
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> AuditEvent:
        """Record an immutable audit event with automatic secret scrubbing."""
        ev_type_str = event_type.value if isinstance(event_type, AuditEventType) else str(event_type)
        actor_str = actor.value if isinstance(actor, AuditActor) else str(actor)

        clean_meta = sanitize_metadata(metadata or {})
        now = timestamp or datetime.now(timezone.utc)

        # Fallback resolution if opportunity_id is passed but not transaction_id
        if opportunity_id and not transaction_id:
            opp = self.db.query(RecoveryOpportunity).filter(RecoveryOpportunity.id == opportunity_id).first()
            if opp and opp.payment_id:
                transaction_id = opp.payment_id

        event = AuditEvent(
            id=uuid.uuid4(),
            merchant_id=merchant_id,
            event_type=ev_type_str,
            actor=actor_str,
            transaction_id=transaction_id,
            opportunity_id=opportunity_id,
            action_id=action_id,
            agent_decision_id=agent_decision_id,
            policy_decision_id=policy_decision_id,
            status=status.upper(),
            summary=summary,
            metadata_json=clean_meta,
            created_at=now,
            request_id=f"req_{uuid.uuid4().hex[:12]}"
        )
        self.db.add(event)
        self.db.commit()
        return event

    # -------------------------------------------------------------------------
    # 13 CORE LIFECYCLE OPERATION LOGGERS
    # -------------------------------------------------------------------------

    def log_transaction_detected(
        self,
        merchant_id: uuid.UUID,
        transaction_id: uuid.UUID,
        amount: Decimal,
        payment_method: str,
        bank: str,
        error_code: Optional[str] = None,
        failure_reason: Optional[str] = None
    ) -> AuditEvent:
        return self.record_event(
            merchant_id=merchant_id,
            event_type=AuditEventType.TRANSACTION_DETECTED,
            actor=AuditActor.SYSTEM,
            transaction_id=transaction_id,
            status="INFO" if not error_code else "FAILED",
            summary=f"Transaction detected on {payment_method.upper()} ({bank}). Status: {'FAILED (' + str(error_code) + ')' if error_code else 'CAPTURED'}.",
            metadata={
                "amount": float(amount),
                "payment_method": payment_method,
                "bank": bank,
                "error_code": error_code,
                "failure_reason": failure_reason
            }
        )

    def log_revenue_leak_detected(
        self,
        merchant_id: uuid.UUID,
        leak_id: uuid.UUID,
        leak_type: str,
        severity: str,
        revenue_at_risk: Decimal,
        root_causes: List[str]
    ) -> AuditEvent:
        return self.record_event(
            merchant_id=merchant_id,
            event_type=AuditEventType.REVENUE_LEAK_DETECTED,
            actor=AuditActor.SYSTEM,
            status="WARNING",
            summary=f"Revenue leak detected: {leak_type} (Severity: {severity}, Risk: ₹{revenue_at_risk:,.2f}).",
            metadata={
                "leak_id": str(leak_id),
                "leak_type": leak_type,
                "severity": severity,
                "revenue_at_risk": float(revenue_at_risk),
                "root_cause_candidates": root_causes
            }
        )

    def log_ml_prediction(
        self,
        merchant_id: uuid.UUID,
        transaction_id: Optional[uuid.UUID],
        model_name: str,
        prediction: float,
        confidence: float,
        features: Dict[str, Any]
    ) -> AuditEvent:
        return self.record_event(
            merchant_id=merchant_id,
            event_type=AuditEventType.ML_PREDICTION,
            actor=AuditActor.SYSTEM,
            transaction_id=transaction_id,
            status="SUCCESS",
            summary=f"ML prediction ({model_name}): probability {prediction:.2%}, confidence {confidence:.2%}.",
            metadata={
                "model_name": model_name,
                "prediction": prediction,
                "confidence": confidence,
                "features_used": list(features.keys())
            }
        )

    def log_opportunity_created(
        self,
        merchant_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        transaction_id: Optional[uuid.UUID],
        amount: Decimal,
        recovery_prob: float,
        expected_recovery: Decimal,
        priority: str
    ) -> AuditEvent:
        return self.record_event(
            merchant_id=merchant_id,
            event_type=AuditEventType.OPPORTUNITY_CREATED,
            actor=AuditActor.SYSTEM,
            opportunity_id=opportunity_id,
            transaction_id=transaction_id,
            status="SUCCESS",
            summary=f"Recovery opportunity created: ₹{amount:,.2f} ({priority} priority, Expected: ₹{expected_recovery:,.2f}).",
            metadata={
                "gross_value": float(amount),
                "recovery_probability": recovery_prob,
                "expected_recovery": float(expected_recovery),
                "priority": priority
            }
        )

    def log_ai_investigation(
        self,
        merchant_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        problem: str,
        evidence: str,
        agent_decision_id: Optional[uuid.UUID] = None
    ) -> AuditEvent:
        return self.record_event(
            merchant_id=merchant_id,
            event_type=AuditEventType.AI_INVESTIGATION,
            actor=AuditActor.AI_RECOVERY_AGENT,
            opportunity_id=opportunity_id,
            agent_decision_id=agent_decision_id,
            status="SUCCESS",
            summary=f"AI Agent investigation completed: {problem}",
            metadata={"evidence": evidence}
        )

    def log_ai_recommendation(
        self,
        merchant_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        recommended_action: str,
        reason: str,
        risk_level: str,
        agent_decision_id: Optional[uuid.UUID] = None
    ) -> AuditEvent:
        return self.record_event(
            merchant_id=merchant_id,
            event_type=AuditEventType.AI_RECOMMENDATION,
            actor=AuditActor.AI_RECOVERY_AGENT,
            opportunity_id=opportunity_id,
            agent_decision_id=agent_decision_id,
            status="SUCCESS",
            summary=f"AI recommended action: {recommended_action} (Risk: {risk_level}).",
            metadata={"reason": reason, "risk_level": risk_level}
        )

    def log_policy_decision(
        self,
        merchant_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        action_type: str,
        allowed: bool,
        approval_required: bool,
        reason: str,
        policy_decision_id: Optional[uuid.UUID] = None,
        limits: Optional[Dict[str, Any]] = None
    ) -> AuditEvent:
        status_str = "SUCCESS" if allowed and not approval_required else ("PENDING" if approval_required else "BLOCKED")
        return self.record_event(
            merchant_id=merchant_id,
            event_type=AuditEventType.POLICY_DECISION,
            actor=AuditActor.POLICY_ENGINE,
            opportunity_id=opportunity_id,
            policy_decision_id=policy_decision_id,
            status=status_str,
            summary=f"Policy verdict for '{action_type}': allowed={allowed}, approval_required={approval_required}. Reason: {reason}",
            metadata={
                "action_type": action_type,
                "allowed": allowed,
                "approval_required": approval_required,
                "policy_limits": limits or {}
            }
        )

    def log_approval(
        self,
        merchant_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        action_id: uuid.UUID,
        approved: bool,
        operator_notes: Optional[str] = None
    ) -> AuditEvent:
        return self.record_event(
            merchant_id=merchant_id,
            event_type=AuditEventType.APPROVAL,
            actor=AuditActor.MERCHANT_OPERATOR,
            opportunity_id=opportunity_id,
            action_id=action_id,
            status="SUCCESS" if approved else "BLOCKED",
            summary=f"Merchant operator {'approved' if approved else 'rejected'} action {action_id}. Notes: {operator_notes or 'None'}",
            metadata={"approved": approved, "notes": operator_notes}
        )

    def log_recovery_action(
        self,
        merchant_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        action_id: uuid.UUID,
        action_type: str,
        provider: str,
        amount: Decimal,
        request_data: Dict[str, Any]
    ) -> AuditEvent:
        return self.record_event(
            merchant_id=merchant_id,
            event_type=AuditEventType.RECOVERY_ACTION,
            actor=AuditActor.SYSTEM,
            opportunity_id=opportunity_id,
            action_id=action_id,
            status="SUCCESS",
            summary=f"Recovery action '{action_type}' dispatched to provider '{provider}' for ₹{amount:,.2f}.",
            metadata={"action_type": action_type, "provider": provider, "request": request_data}
        )

    def log_provider_response(
        self,
        merchant_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        action_id: uuid.UUID,
        provider: str,
        status: str,
        response_data: Dict[str, Any]
    ) -> AuditEvent:
        actor_name = AuditActor.RAZORPAY_TEST_PROVIDER if provider == "razorpay_test" else AuditActor.MOCK_PROVIDER
        return self.record_event(
            merchant_id=merchant_id,
            event_type=AuditEventType.PROVIDER_RESPONSE,
            actor=actor_name,
            opportunity_id=opportunity_id,
            action_id=action_id,
            status="SUCCESS" if status == "success" else "FAILED",
            summary=f"Provider '{provider}' returned status: {status}.",
            metadata={"provider": provider, "response": response_data}
        )

    def log_webhook(
        self,
        merchant_id: uuid.UUID,
        event_name: str,
        event_id: str,
        payment_id: Optional[str] = None,
        status: str = "PROCESSED"
    ) -> AuditEvent:
        return self.record_event(
            merchant_id=merchant_id,
            event_type=AuditEventType.WEBHOOK,
            actor=AuditActor.WEBHOOK_ENGINE,
            status="SUCCESS" if status == "PROCESSED" else "INFO",
            summary=f"Gateway webhook received: '{event_name}' (Event ID: {event_id}). Status: {status}.",
            metadata={"event_name": event_name, "event_id": event_id, "payment_id": payment_id}
        )

    def log_recovery_verification(
        self,
        merchant_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        action_id: uuid.UUID,
        verified: bool,
        verification_method: str,
        details: Dict[str, Any]
    ) -> AuditEvent:
        return self.record_event(
            merchant_id=merchant_id,
            event_type=AuditEventType.RECOVERY_VERIFICATION,
            actor=AuditActor.SYSTEM,
            opportunity_id=opportunity_id,
            action_id=action_id,
            status="SUCCESS" if verified else "FAILED",
            summary=f"Recovery verification {'passed' if verified else 'pending'} via {verification_method}.",
            metadata={"verified": verified, "verification_method": verification_method, "details": details}
        )

    def log_final_recovered_amount(
        self,
        merchant_id: uuid.UUID,
        opportunity_id: uuid.UUID,
        recovered_amount: Decimal,
        action_id: Optional[uuid.UUID] = None
    ) -> AuditEvent:
        return self.record_event(
            merchant_id=merchant_id,
            event_type=AuditEventType.FINAL_RECOVERED_AMOUNT,
            actor=AuditActor.SYSTEM,
            opportunity_id=opportunity_id,
            action_id=action_id,
            status="SUCCESS",
            summary=f"Final revenue recovery confirmed: ₹{recovered_amount:,.2f} credited to merchant ledger.",
            metadata={"recovered_amount": float(recovered_amount)}
        )

    # -------------------------------------------------------------------------
    # QUERY & TIMELINE BUILDER
    # -------------------------------------------------------------------------

    def query_events(
        self,
        merchant_id: Optional[uuid.UUID] = None,
        transaction_id: Optional[uuid.UUID] = None,
        opportunity_id: Optional[uuid.UUID] = None,
        action_id: Optional[uuid.UUID] = None,
        event_type: Optional[str] = None,
        actor: Optional[str] = None,
        status: Optional[str] = None,
        date_str: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[AuditEvent], int]:
        """Query audit ledger with multi-dimensional filtering."""
        q = self.db.query(AuditEvent)

        if merchant_id:
            q = q.filter(AuditEvent.merchant_id == merchant_id)
        if transaction_id:
            q = q.filter(AuditEvent.transaction_id == transaction_id)
        if opportunity_id:
            q = q.filter(AuditEvent.opportunity_id == opportunity_id)
        if action_id:
            q = q.filter(AuditEvent.action_id == action_id)
        if event_type:
            ev_clean = event_type.lower().strip()
            q = q.filter(
                (func.lower(AuditEvent.event_type) == ev_clean) |
                (func.lower(AuditEvent.event_type).startswith(f"{ev_clean}_"))
            )
        if actor:
            q = q.filter(func.lower(AuditEvent.actor) == actor.lower().strip())
        if status:
            q = q.filter(func.lower(AuditEvent.status) == status.lower().strip())

        if date_str:
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
                q = q.filter(func.date(AuditEvent.created_at) == d)
            except ValueError:
                pass

        if date_from:
            q = q.filter(AuditEvent.created_at >= date_from)
        if date_to:
            q = q.filter(AuditEvent.created_at <= date_to)

        total = q.count()
        events = q.order_by(desc(AuditEvent.created_at)).offset(offset).limit(limit).all()
        return events, total

    def get_action_causality_timeline(self, action_id: uuid.UUID) -> List[AuditEvent]:
        """
        Builds the complete chronological causality timeline for a specific recovery action.
        Pulls all connected events across transaction failure, leak detection,
        ML prediction, opportunity ranking, AI investigation, policy gate,
        provider dispatch, and final settlement.
        """
        act = self.db.query(RecoveryAction).filter(RecoveryAction.id == action_id).first()
        if not act:
            # Try to find direct events with action_id
            return self.db.query(AuditEvent).filter(
                AuditEvent.action_id == action_id
            ).order_by(AuditEvent.created_at.asc()).all()

        opp_id = act.opportunity_id
        opp = act.opportunity

        # Gather relevant entity IDs
        target_action_id = act.id
        target_opp_id = opp_id
        target_tx_id = opp.payment_id if opp else None
        target_policy_id = act.policy_decision_id
        target_agent_id = act.agent_decision_id

        # Query events related to this action chain
        events = self.db.query(AuditEvent).filter(
            (AuditEvent.action_id == target_action_id) |
            (AuditEvent.opportunity_id == target_opp_id) |
            (AuditEvent.transaction_id == target_tx_id) |
            (AuditEvent.policy_decision_id == target_policy_id) |
            (AuditEvent.agent_decision_id == target_agent_id)
        ).order_by(AuditEvent.created_at.asc()).all()

        return events
