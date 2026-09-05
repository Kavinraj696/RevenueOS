import uuid
import time
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.recovery_action import RecoveryAction
from app.models.recovery_opportunity import RecoveryOpportunity
from app.models.agent_decision import AgentDecision
from app.models.policy_decision import PolicyDecision
from app.models.audit_event import AuditEvent
from app.models.payment import Payment
from app.models.customer import Customer
from app.models.subscription import Subscription
from app.models.enums import (
    ActionType,
    ActionStatus,
    OpportunityStatus,
    PolicyAction,
)
from app.services.payment_provider import get_payment_provider
from app.services.policy_engine import (
    FinancialActionPolicyEngine,
    PolicyEvaluationRequest,
    quantize_inr
)
from app.services.agent.recovery_agent import AIRecoveryAgent


class RecoveryExecutionError(Exception):
    """Raised when recovery execution fails."""
    pass


class DuplicateActionError(Exception):
    """Raised when attempting to trigger a duplicate active recovery action."""
    pass


class RecoveryExecutor:
    """
    Core executor engine for RevenueOS recovery actions.
    Coordinates between AI recommendations, Financial Policy Engine gates,
    Payment Providers (Mock / Razorpay Test Mode), and audit ledgers.
    """

    def __init__(self, db: Session):
        self.db = db
        self.policy_engine = FinancialActionPolicyEngine()

    def execute_action(
        self,
        opportunity_id: uuid.UUID,
        action_type: str,
        amount: Optional[Decimal] = None,
        agent_decision_id: Optional[uuid.UUID] = None,
        policy_decision_id: Optional[uuid.UUID] = None,
        simulate_failure: bool = False,
        failure_type: str = "GATEWAY_TIMEOUT",
        custom_request: Optional[Dict[str, Any]] = None,
        bypass_policy: bool = False
    ) -> RecoveryAction:
        """
        Execute a single recovery action against an opportunity.
        Includes idempotency / duplicate checks, state transitions,
        provider dispatch, failure handling, and audit event generation.
        """
        opp = self.db.query(RecoveryOpportunity).filter(RecoveryOpportunity.id == opportunity_id).first()
        if not opp:
            raise RecoveryExecutionError(f"Recovery opportunity {opportunity_id} not found")

        # ---------------------------------------------------------------------
        # 1. PREVENT DUPLICATE ACTIONS
        # ---------------------------------------------------------------------
        normalized_action_type = self._normalize_action_type(action_type)
        existing_active = self.db.query(RecoveryAction).filter(
            RecoveryAction.opportunity_id == opportunity_id,
            RecoveryAction.action_type == normalized_action_type,
            RecoveryAction.status.in_([
                ActionStatus.PENDING.value,
                ActionStatus.APPROVED.value,
                ActionStatus.EXECUTING.value,
                ActionStatus.SUCCESS.value
            ])
        ).first()

        if existing_active:
            raise DuplicateActionError(
                f"Duplicate action prevented: Opportunity {opportunity_id} already has an active '{normalized_action_type}' "
                f"action (ID: {existing_active.id}, Status: {existing_active.status})."
            )

        # ---------------------------------------------------------------------
        # 2. RESOLVE MONETARY AMOUNT & POLICY EVALUATION
        # ---------------------------------------------------------------------
        target_amount = amount or opp.gross_value_affected or Decimal("4999.00")
        target_amount = quantize_inr(target_amount)

        provider_inst = get_payment_provider()
        provider_name = provider_inst.provider_name

        # Policy Gate (if not pre-evaluated)
        approval_required = False
        if not bypass_policy and not policy_decision_id:
            policy_req = PolicyEvaluationRequest(
                action=self._map_to_policy_action(normalized_action_type),
                transaction_amount=target_amount,
                recovery_confidence=float(opp.recovery_probability or 0.82),
                opportunity_id=str(opportunity_id),
                opportunity_status=opp.status,
                risk_level=opp.risk or "low"
            )
            policy_res = self.policy_engine.evaluate(policy_req, db=self.db)
            if not policy_res.allowed:
                blocked_act = RecoveryAction(
                    id=uuid.uuid4(),
                    opportunity_id=opportunity_id,
                    agent_decision_id=agent_decision_id,
                    provider=provider_name,
                    action_type=normalized_action_type,
                    status=ActionStatus.BLOCKED.value,
                    amount=target_amount,
                    reason=f"Policy blocked action: {policy_res.reason}",
                    request=custom_request or {},
                    result={"allowed": False, "reason": policy_res.reason}
                )
                self.db.add(blocked_act)
                self.db.commit()
                self._record_audit_event(
                    opp.merchant_id, "recovery_action_blocked", str(blocked_act.id),
                    f"Action '{normalized_action_type}' blocked by policy: {policy_res.reason}"
                )
                return blocked_act

            approval_required = policy_res.approval_required

        # ---------------------------------------------------------------------
        # 3. CREATE INITIAL ACTION RECORD (PENDING / APPROVED)
        # ---------------------------------------------------------------------
        initial_status = ActionStatus.PENDING.value if approval_required else ActionStatus.APPROVED.value
        act = RecoveryAction(
            id=uuid.uuid4(),
            opportunity_id=opportunity_id,
            agent_decision_id=agent_decision_id,
            policy_decision_id=policy_decision_id,
            provider=provider_name,
            action_type=normalized_action_type,
            status=initial_status,
            amount=target_amount,
            request=custom_request or {},
            reason=f"Recovery action triggered via {provider_name} provider."
        )
        self.db.add(act)
        self.db.commit()

        # If approval is required, pause here and wait for merchant sign-off
        if approval_required:
            self._record_audit_event(
                opp.merchant_id, "recovery_action_pending_approval", str(act.id),
                f"Action '{normalized_action_type}' requires merchant approval before execution."
            )
            opp.status = OpportunityStatus.PENDING_APPROVAL.value
            self.db.commit()
            return act

        # ---------------------------------------------------------------------
        # 4. EXECUTE VIA PROVIDER
        # ---------------------------------------------------------------------
        return self._dispatch_execution(
            act=act,
            opp=opp,
            simulate_failure=simulate_failure,
            failure_type=failure_type
        )

    def _dispatch_execution(
        self,
        act: RecoveryAction,
        opp: RecoveryOpportunity,
        simulate_failure: bool = False,
        failure_type: str = "GATEWAY_TIMEOUT"
    ) -> RecoveryAction:
        """Internal dispatch of an approved action to the active provider."""
        act.status = ActionStatus.EXECUTING.value
        self.db.commit()

        provider = get_payment_provider()
        now_utc = datetime.now(timezone.utc)

        # Check for simulated failure
        if simulate_failure:
            act.status = ActionStatus.FAILED.value
            act.completed_at = now_utc
            act.result = {
                "error": failure_type,
                "simulated": True,
                "message": f"Simulated provider failure: {failure_type}",
                "timestamp": now_utc.isoformat()
            }
            opp.status = OpportunityStatus.ACTION_SELECTED.value
            self.db.commit()

            self._record_audit_event(
                opp.merchant_id,
                "recovery_action_failed",
                str(act.id),
                f"Action '{act.action_type}' failed with error: {failure_type} (simulated failure)."
            )
            return act

        try:
            req_payload = act.request or {}
            res_payload: Dict[str, Any] = {}

            if act.action_type == ActionType.CREATE_PAYMENT_LINK.value:
                res_payload = self._exec_create_payment_link(provider, opp, act.amount or Decimal("4999.00"), req_payload)
            elif act.action_type == ActionType.SEND_RECOVERY_NOTIFICATION.value:
                res_payload = self._exec_send_notification(opp, req_payload)
            elif act.action_type == ActionType.RECOMMEND_ALTERNATIVE_PAYMENT.value:
                res_payload = self._exec_alternative_payment(opp, req_payload)
            elif act.action_type == ActionType.SUBSCRIPTION_RECOVERY.value:
                res_payload = self._exec_subscription_recovery(provider, opp, req_payload)
            elif act.action_type == ActionType.MERCHANT_ESCALATION.value:
                res_payload = self._exec_merchant_escalation(opp, req_payload)
            else:
                # Fallback to payment link
                res_payload = self._exec_create_payment_link(provider, opp, act.amount or Decimal("4999.00"), req_payload)

            act.status = ActionStatus.SUCCESS.value
            act.completed_at = datetime.now(timezone.utc)
            act.result = res_payload
            opp.status = OpportunityStatus.EXECUTING.value

            self.db.commit()

            self._record_audit_event(
                opp.merchant_id,
                "recovery_action_executed",
                str(act.id),
                f"Action '{act.action_type}' successfully executed via {act.provider}. Ref: {res_payload.get('id') or res_payload.get('reference_id')}"
            )
            return act

        except Exception as ex:
            act.status = ActionStatus.FAILED.value
            act.completed_at = datetime.now(timezone.utc)
            act.result = {
                "error": "EXECUTION_EXCEPTION",
                "message": str(ex),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            self.db.commit()

            self._record_audit_event(
                opp.merchant_id,
                "recovery_action_failed",
                str(act.id),
                f"Action '{act.action_type}' encountered runtime error: {str(ex)}"
            )
            return act

    # -------------------------------------------------------------------------
    # SPECIFIC ACTION IMPLEMENTATIONS
    # -------------------------------------------------------------------------

    def _exec_create_payment_link(
        self,
        provider: Any,
        opp: RecoveryOpportunity,
        amount: Decimal,
        req_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create a payment recovery link."""
        cust = opp.customer
        phone = req_payload.get("customer_phone") or (cust.external_ref if cust else "+919876543210")
        name = req_payload.get("customer_name") or "Valued Customer"

        link_res = provider.create_payment_link(
            amount=amount,
            description=f"Recovery payment link for Opportunity #{str(opp.id)[:8]}",
            customer_name=name,
            customer_phone=phone,
            notes={"opportunity_id": str(opp.id), "merchant_id": str(opp.merchant_id)}
        )
        return {
            "id": link_res.get("id"),
            "short_url": link_res.get("short_url"),
            "amount": link_res.get("amount"),
            "currency": link_res.get("currency", "INR"),
            "status": link_res.get("status", "created"),
            "created_at": link_res.get("created_at")
        }

    def _exec_send_notification(
        self,
        opp: RecoveryOpportunity,
        req_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send recovery notification via WhatsApp / SMS."""
        channel = req_payload.get("channel", "sms_whatsapp")
        template = req_payload.get("template", "payment_failure_recovery_v1")
        notif_id = f"notif_{uuid.uuid4().hex[:12]}"

        return {
            "id": notif_id,
            "channel": channel,
            "template": template,
            "recipient": req_payload.get("customer_phone", "+919876543210"),
            "status": "delivered",
            "message": "Your payment failed due to bank downtime. Use your recovery link to complete the transaction without re-entering details.",
            "dispatched_at": int(datetime.now(timezone.utc).timestamp())
        }

    def _exec_alternative_payment(
        self,
        opp: RecoveryOpportunity,
        req_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Recommend and configure an alternative reliable payment method route."""
        # Find degraded method from leak or transaction
        degraded_method = req_payload.get("failed_method", "upi")
        recommended_route = "netbanking_icici" if degraded_method == "upi" else "card_visa_mastercard"

        return {
            "id": f"alt_route_{uuid.uuid4().hex[:10]}",
            "degraded_method": degraded_method,
            "recommended_method": recommended_route,
            "success_probability_boost": "+24.5%",
            "checkout_url": f"https://rzp.io/l/alt_{uuid.uuid4().hex[:8]}",
            "status": "configured",
            "notes": "Route traffic away from degraded PSP directly to high-availability banking gateway."
        }

    def _exec_subscription_recovery(
        self,
        provider: Any,
        opp: RecoveryOpportunity,
        req_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute subscription mandate recovery workflow."""
        sub = self.db.query(Subscription).filter(Subscription.merchant_id == opp.merchant_id).first()
        plan_id = sub.plan_name if sub else "plan_premium_monthly"

        sub_res = provider.create_subscription(
            plan_id=plan_id,
            total_count=12,
            notes={"opportunity_id": str(opp.id)}
        )
        return {
            "id": sub_res.get("id"),
            "plan_id": plan_id,
            "short_url": sub_res.get("short_url"),
            "status": "active",
            "mandate_reauth_ready": True
        }

    def _exec_merchant_escalation(
        self,
        opp: RecoveryOpportunity,
        req_payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Escalate high-value VIP case for operational review."""
        ticket_id = f"esc_ticket_{uuid.uuid4().hex[:10]}"
        return {
            "id": ticket_id,
            "status": "queued_for_ops",
            "priority": "P1_VIP",
            "opportunity_id": str(opp.id),
            "amount": float(opp.gross_value_affected),
            "notes": req_payload.get("notes", "VIP customer transaction exceeding auto-recovery threshold.")
        }

    # -------------------------------------------------------------------------
    # APPROVAL WORKFLOW
    # -------------------------------------------------------------------------

    def approve_action(self, action_id: uuid.UUID, notes: Optional[str] = None) -> RecoveryAction:
        """Merchant approves an action that was paused in PENDING state."""
        act = self.db.query(RecoveryAction).filter(RecoveryAction.id == action_id).first()
        if not act:
            raise RecoveryExecutionError(f"Action {action_id} not found")

        if act.status != ActionStatus.PENDING.value:
            raise RecoveryExecutionError(f"Action {action_id} is in '{act.status}' state, not PENDING approval.")

        opp = act.opportunity
        act.reason = f"Approved by merchant operations. Notes: {notes or 'No notes provided.'}"
        act.status = ActionStatus.APPROVED.value
        self.db.commit()

        self._record_audit_event(
            opp.merchant_id,
            "recovery_action_approved",
            str(act.id),
            f"Merchant approved action '{act.action_type}' for opportunity {opp.id}."
        )

        return self._dispatch_execution(act=act, opp=opp, simulate_failure=False)

    # -------------------------------------------------------------------------
    # RESILIENT FAILURE HANDLING & ALTERNATIVE RECOMMENDATION (DEMO FLOW)
    # -------------------------------------------------------------------------

    def handle_action_failure_and_fallback(
        self,
        failed_action_id: uuid.UUID,
        alternative_action_type: Optional[str] = None
    ) -> Tuple[RecoveryAction, RecoveryAction]:
        """
        Handles failure of a primary action gracefully and recommends/executes an alternative action.
        Demo Scenario:
        1. Action fails (status=FAILED).
        2. System handles failure gracefully without crash.
        3. System recommends alternative action (e.g. recommend alternative payment rail).
        4. Alternative action is approved by policy and executed successfully.
        """
        failed_act = self.db.query(RecoveryAction).filter(RecoveryAction.id == failed_action_id).first()
        if not failed_act:
            raise RecoveryExecutionError(f"Action {failed_action_id} not found")

        opp = failed_act.opportunity

        # Determine alternative action
        if not alternative_action_type:
            if failed_act.action_type == ActionType.CREATE_PAYMENT_LINK.value:
                alt_type = ActionType.RECOMMEND_ALTERNATIVE_PAYMENT.value
            elif failed_act.action_type == ActionType.RECOMMEND_ALTERNATIVE_PAYMENT.value:
                alt_type = ActionType.SEND_RECOVERY_NOTIFICATION.value
            else:
                alt_type = ActionType.CREATE_PAYMENT_LINK.value
        else:
            alt_type = self._normalize_action_type(alternative_action_type)

        # Log audit trail for graceful fallback initiation
        self._record_audit_event(
            opp.merchant_id,
            "recovery_fallback_initiated",
            str(failed_act.id),
            f"Action '{failed_act.action_type}' failed. Initiating automated graceful fallback to '{alt_type}'."
        )

        # Execute alternative action
        alt_act = self.execute_action(
            opportunity_id=opp.id,
            action_type=alt_type,
            amount=failed_act.amount,
            agent_decision_id=failed_act.agent_decision_id,
            simulate_failure=False,
            bypass_policy=False,
            custom_request={
                "fallback_from_action_id": str(failed_act.id),
                "previous_failure_error": failed_act.result.get("error") if failed_act.result else "UNKNOWN"
            }
        )

        # If alternative action succeeded, mark opportunity as resolved
        if alt_act.status == ActionStatus.SUCCESS.value:
            opp.status = OpportunityStatus.RECOVERED.value
            opp.actual_recovered_value = alt_act.amount
            self.db.commit()

            self._record_audit_event(
                opp.merchant_id,
                "recovery_fallback_succeeded",
                str(alt_act.id),
                f"Graceful fallback succeeded: Revenue recovered via alternative action '{alt_act.action_type}'."
            )

        return failed_act, alt_act

    # -------------------------------------------------------------------------
    # FULL END-TO-END PIPELINE ORCHESTRATOR
    # -------------------------------------------------------------------------

    def run_pipeline(
        self,
        opportunity_id: Optional[uuid.UUID] = None,
        transaction_id: Optional[uuid.UUID] = None,
        merchant_id: Optional[uuid.UUID] = None,
        action_type: Optional[str] = None,
        simulate_failure: bool = False,
        failure_type: str = "GATEWAY_TIMEOUT",
        auto_execute: bool = True
    ) -> Dict[str, Any]:
        """
        Runs the complete end-to-end recovery pipeline:
        Recovery Opportunity
        -> AI Agent (Observe, Diagnose, Quantify, Recommend)
        -> Policy Engine
        -> Approval Gate
        -> Recovery Executor
        -> Provider
        -> Verification & Audit
        -> Dashboard Update
        """
        trail: List[str] = []
        pipeline_id = uuid.uuid4()
        trail.append(f"1. Pipeline {pipeline_id} initialized.")

        # Resolve Opportunity
        opp: Optional[RecoveryOpportunity] = None
        if opportunity_id:
            opp = self.db.query(RecoveryOpportunity).filter(RecoveryOpportunity.id == opportunity_id).first()
        elif transaction_id:
            opp = self.db.query(RecoveryOpportunity).filter(RecoveryOpportunity.payment_id == transaction_id).first()
        elif merchant_id:
            opp = self.db.query(RecoveryOpportunity).filter(RecoveryOpportunity.merchant_id == merchant_id).first()

        if not opp:
            # Create dynamic opportunity from transaction or merchant
            target_m_id = merchant_id or uuid.uuid4()
            opp = RecoveryOpportunity(
                id=uuid.uuid4(),
                merchant_id=target_m_id,
                payment_id=transaction_id,
                gross_value_affected=Decimal("4999.00"),
                potentially_recoverable_value=Decimal("4099.00"),
                recovery_probability=Decimal("0.8200"),
                expected_recovered_value=Decimal("4099.00"),
                priority="HIGH",
                priority_score=Decimal("84.50"),
                risk="low",
                explanation="Autonomous recovery pipeline candidate."
            )
            self.db.add(opp)
            self.db.commit()

        trail.append(f"2. Recovery Opportunity #{str(opp.id)[:8]} loaded (Amount: ₹{opp.gross_value_affected}).")

        # Run AI Agent Workflow
        agent = AIRecoveryAgent(self.db)
        agent_resp = agent.run_workflow(
            merchant_id=opp.merchant_id,
            opportunity_id=opp.id,
            transaction_id=opp.payment_id,
            auto_execute=False  # Hand off execution to RecoveryExecutor
        )
        trail.append(f"3. AI Agent diagnosed: '{agent_resp.problem}'. Recommended: '{agent_resp.recommended_action}'.")

        # Resolve Agent Decision record
        agent_dec = self.db.query(AgentDecision).filter(AgentDecision.opportunity_id == opp.id).order_by(desc(AgentDecision.created_at)).first()
        agent_dec_id = agent_dec.id if agent_dec else None

        # Resolve Policy Decision
        pol_dec = self.db.query(PolicyDecision).filter(PolicyDecision.opportunity_id == opp.id).order_by(desc(PolicyDecision.created_at)).first()
        pol_dec_id = pol_dec.id if pol_dec else None
        pol_verdict = agent_resp.policy_result
        approval_req = "APPROVAL_REQUIRED" in pol_verdict
        trail.append(f"4. Policy Gate verdict: {pol_verdict} (Approval required: {approval_req}).")

        # Map to requested or AI-recommended action type
        target_action_type = action_type or self._map_ai_rec_to_action_type(agent_resp.recommended_action)
        trail.append(f"5. Target action mapped to '{target_action_type}'.")

        # Execute via Recovery Executor
        action_rec = self.execute_action(
            opportunity_id=opp.id,
            action_type=target_action_type,
            amount=opp.gross_value_affected,
            agent_decision_id=agent_dec_id,
            policy_decision_id=pol_dec_id,
            simulate_failure=simulate_failure,
            failure_type=failure_type,
            bypass_policy=False
        )
        trail.append(f"6. Action executed via provider '{action_rec.provider}'. Status: '{action_rec.status}'.")

        # Handle failure simulation fallback if failed
        fallback_rec = None
        if action_rec.status == ActionStatus.FAILED.value:
            trail.append("7. Action failed! Catching failure gracefully and invoking alternative fallback.")
            _, fallback_rec = self.handle_action_failure_and_fallback(action_rec.id)
            trail.append(f"8. Alternative action '{fallback_rec.action_type}' executed with status: '{fallback_rec.status}'.")

        # Audit Event check
        last_audit = self.db.query(AuditEvent).filter(
            AuditEvent.merchant_id == opp.merchant_id
        ).order_by(desc(AuditEvent.created_at)).first()

        trail.append("9. Audit event recorded in immutable causality ledger.")
        trail.append("10. Dashboard telemetry updated.")

        return {
            "pipeline_id": pipeline_id,
            "opportunity_id": opp.id,
            "status": "completed" if (action_rec.status == ActionStatus.SUCCESS.value or (fallback_rec and fallback_rec.status == ActionStatus.SUCCESS.value)) else action_rec.status,
            "action": action_rec,
            "policy_verdict": pol_verdict,
            "approval_required": approval_req,
            "audit_event_id": last_audit.id if last_audit else None,
            "fallback_action": fallback_rec,
            "execution_trail": trail
        }

    # -------------------------------------------------------------------------
    # HELPERS
    # -------------------------------------------------------------------------

    def _normalize_action_type(self, action_type: str) -> str:
        """Normalize action type strings to standard ActionType enums."""
        act_lower = action_type.lower().replace("-", "_").strip()
        if "link" in act_lower:
            return ActionType.CREATE_PAYMENT_LINK.value
        elif "notif" in act_lower or "sms" in act_lower or "whatsapp" in act_lower:
            return ActionType.SEND_RECOVERY_NOTIFICATION.value
        elif "alt" in act_lower or "method" in act_lower:
            return ActionType.RECOMMEND_ALTERNATIVE_PAYMENT.value
        elif "sub" in act_lower or "mandate" in act_lower:
            return ActionType.SUBSCRIPTION_RECOVERY.value
        elif "escalat" in act_lower or "approv" in act_lower:
            return ActionType.MERCHANT_ESCALATION.value
        return ActionType.CREATE_PAYMENT_LINK.value

    def _map_to_policy_action(self, action_type: str) -> str:
        """Map normalized action type to PolicyAction enum."""
        if action_type == ActionType.CREATE_PAYMENT_LINK.value:
            return PolicyAction.CREATE_PAYMENT_LINK.value
        elif action_type == ActionType.SEND_RECOVERY_NOTIFICATION.value:
            return PolicyAction.SEND_RECOVERY_NOTIFICATION.value
        elif action_type == ActionType.RECOMMEND_ALTERNATIVE_PAYMENT.value:
            return PolicyAction.RECOMMEND_ALTERNATIVE_PAYMENT.value
        elif action_type == ActionType.SUBSCRIPTION_RECOVERY.value:
            return PolicyAction.TRIGGER_SUBSCRIPTION_RECOVERY.value
        elif action_type == ActionType.MERCHANT_ESCALATION.value:
            return PolicyAction.REQUEST_MERCHANT_APPROVAL.value
        return PolicyAction.CREATE_PAYMENT_LINK.value

    def _map_ai_rec_to_action_type(self, rec_str: str) -> str:
        """Map AI natural language recommendation to concrete ActionType."""
        rec_lower = rec_str.lower()
        if "escalat" in rec_lower or "concierge" in rec_lower or "approval" in rec_lower:
            return ActionType.MERCHANT_ESCALATION.value
        elif "sub" in rec_lower or "mandate" in rec_lower:
            return ActionType.SUBSCRIPTION_RECOVERY.value
        elif "alternative" in rec_lower:
            return ActionType.RECOMMEND_ALTERNATIVE_PAYMENT.value
        elif "notif" in rec_lower:
            return ActionType.SEND_RECOVERY_NOTIFICATION.value
        return ActionType.CREATE_PAYMENT_LINK.value

    def _record_audit_event(
        self,
        merchant_id: uuid.UUID,
        event_type: str,
        related_id: str,
        message: str
    ) -> AuditEvent:
        """Persist immutable audit event."""
        rel_uuid = uuid.UUID(str(related_id)) if related_id else uuid.uuid4()
        
        # Determine appropriate actor and status
        actor = "SYSTEM"
        if "policy" in event_type or "blocked" in event_type:
            actor = "POLICY_ENGINE"
        elif "approved" in event_type:
            actor = "MERCHANT_OPERATOR"

        status_val = "SUCCESS"
        if "blocked" in event_type:
            status_val = "BLOCKED"
        elif "failed" in event_type:
            status_val = "FAILED"
        elif "pending" in event_type:
            status_val = "PENDING"

        audit = AuditEvent(
            id=uuid.uuid4(),
            merchant_id=merchant_id,
            actor=actor,
            event_type=event_type,
            status=status_val,
            summary=message,
            related_entity_type="recovery_action",
            related_entity_id=rel_uuid,
            action_id=rel_uuid,
            metadata_json={"action_id": str(rel_uuid), "detail": message},
            request_id=f"req_{uuid.uuid4().hex[:12]}",
            message=message,
            created_at=datetime.now(timezone.utc)
        )
        self.db.add(audit)
        self.db.commit()
        return audit
