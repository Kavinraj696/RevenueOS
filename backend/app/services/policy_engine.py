import uuid
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Union
from sqlalchemy.orm import Session

from app.db.base import quantize_inr, get_utc_now
from app.models.enums import PolicyAction, RiskSegment, ActionStatus, ActionType
from app.models.policy_decision import PolicyDecision
from app.models.recovery_action import RecoveryAction
from app.schemas.policy import (
    PolicyLimitsConfig,
    PolicyEvaluationRequest,
    PolicyDecisionResponse,
    PolicyPipelineUI,
    PipelineStageAIRecommendation,
    PipelineStagePolicyDecision,
    PipelineStageApprovalGate,
    PipelineStageExecution,
)


class FinancialActionPolicyEngine:
    """
    Deterministic Financial Action Policy Engine.
    The LLM must NEVER bypass this engine or directly execute financial actions.
    All evaluations are strictly rule-based, reproducible, and mathematically bounded.
    """

    def __init__(self, config: Optional[PolicyLimitsConfig] = None):
        self.config = config or PolicyLimitsConfig()

    def evaluate(
        self,
        request: PolicyEvaluationRequest,
        db: Optional[Session] = None,
        agent_decision_id: Optional[uuid.UUID] = None,
    ) -> PolicyDecisionResponse:
        """
        Deterministically evaluate a requested action against financial policy guardrails.
        Evaluates in strict priority order:
        1. Action validity & safety check
        2. Opportunity status & expiration check
        3. Duplicate action & cooldown check
        4. Repeated attempts threshold check
        5. Customer risk tier & dispute check
        6. Recovery confidence threshold check
        7. Transaction value tiering & action safety rules
        """
        now = get_utc_now()
        decision_id = uuid.uuid4()
        raw_action = str(request.action or "").strip().upper()
        amount = quantize_inr(request.transaction_amount)
        conf = max(0.0, min(1.0, float(request.recovery_confidence)))
        attempts = request.previous_attempts
        is_vip = request.is_vip
        cust_risk = (request.customer_risk_tier or "low").lower()
        cooldown_secs = request.cooldown_seconds if request.cooldown_seconds is not None else self.config.cooldown_seconds
        assessed_risk = (request.risk_level or "low").lower()

        allowed_actions_set = {a.value for a in PolicyAction}

        # Snapshot of active governance limits
        limits_dict: Dict[str, Any] = {
            "max_auto_amount": float(self.config.max_auto_amount),
            "medium_auto_amount": float(self.config.medium_auto_amount),
            "min_confidence": float(self.config.min_confidence),
            "max_attempts": self.config.max_attempts,
            "cooldown_seconds": cooldown_secs,
            "allowed_passive_actions": self.config.allowed_passive_actions,
        }

        # ---------------------------------------------------------------------
        # RULE 1: UNSAFE / UNKNOWN ACTION TYPE CHECK
        # ---------------------------------------------------------------------
        if raw_action not in allowed_actions_set:
            return self._build_response(
                decision_id=decision_id,
                action=PolicyAction.BLOCK_ACTION.value,
                allowed=False,
                reason=f"Unrecognized or unsafe action '{raw_action}' rejected by financial policy gate.",
                risk_level="high",
                approval_required=False,
                limits=limits_dict,
                timestamp=now,
                request=request,
                execution_status="blocked"
            )

        if raw_action == PolicyAction.BLOCK_ACTION.value:
            return self._build_response(
                decision_id=decision_id,
                action=PolicyAction.BLOCK_ACTION.value,
                allowed=False,
                reason="Explicit block action enforced by upstream policy recommendation.",
                risk_level="high",
                approval_required=False,
                limits=limits_dict,
                timestamp=now,
                request=request,
                execution_status="blocked"
            )

        # ---------------------------------------------------------------------
        # RULE 2: EXPIRED / RESOLVED OPPORTUNITY CHECK
        # ---------------------------------------------------------------------
        resolved_statuses = {"dismissed", "recovered", "expired", "failed", "cancelled"}
        opp_status = (request.opportunity_status or "").lower()
        if request.is_expired or opp_status in resolved_statuses:
            return self._build_response(
                decision_id=decision_id,
                action=PolicyAction.BLOCK_ACTION.value,
                allowed=False,
                reason=f"Recovery opportunity is expired or already resolved (status: '{opp_status or 'expired'}'). Action blocked.",
                risk_level="high",
                approval_required=False,
                limits=limits_dict,
                timestamp=now,
                request=request,
                execution_status="blocked"
            )

        # ---------------------------------------------------------------------
        # RULE 3: DUPLICATE ACTION & COOLDOWN CHECK
        # ---------------------------------------------------------------------
        # Check explicit caller timestamp
        if request.last_action_timestamp:
            elapsed_sec = (now - request.last_action_timestamp).total_seconds()
            if elapsed_sec < cooldown_secs:
                # If it's a duplicate of the same action or an active intervention within cooldown
                return self._build_response(
                    decision_id=decision_id,
                    action=PolicyAction.BLOCK_ACTION.value,
                    allowed=False,
                    reason=f"Cooldown active: Last action occurred {int(elapsed_sec)}s ago (required cooldown: {cooldown_secs}s). Duplicate action blocked.",
                    risk_level="medium",
                    approval_required=False,
                    limits=limits_dict,
                    timestamp=now,
                    request=request,
                    execution_status="blocked"
                )

        # Check DB history if session and opportunity_id provided
        if db and request.opportunity_id:
            try:
                opp_uuid = uuid.UUID(str(request.opportunity_id))
                recent_action = (
                    db.query(RecoveryAction)
                    .filter(
                        RecoveryAction.opportunity_id == opp_uuid,
                        RecoveryAction.status.in_([ActionStatus.EXECUTED.value, ActionStatus.SUCCEEDED.value])
                    )
                    .order_by(RecoveryAction.executed_at.desc())
                    .first()
                )
                if recent_action and recent_action.executed_at:
                    elapsed = (now - recent_action.executed_at).total_seconds()
                    if elapsed < cooldown_secs:
                        return self._build_response(
                            decision_id=decision_id,
                            action=PolicyAction.BLOCK_ACTION.value,
                            allowed=False,
                            reason=f"Database cooldown active: Action '{recent_action.action_type}' executed {int(elapsed)}s ago. Cooldown period is {cooldown_secs}s. Action blocked.",
                            risk_level="medium",
                            approval_required=False,
                            limits=limits_dict,
                            timestamp=now,
                            request=request,
                            execution_status="blocked"
                        )
            except Exception:
                pass

        # ---------------------------------------------------------------------
        # RULE 4: REPEATED ATTEMPTS THRESHOLD (GATEWAY RETRY CAP)
        # ---------------------------------------------------------------------
        if attempts >= self.config.max_attempts and raw_action in {
            PolicyAction.RETRY_ALLOWED_PAYMENT.value,
            PolicyAction.TRIGGER_SUBSCRIPTION_RECOVERY.value
        }:
            return self._build_response(
                decision_id=decision_id,
                action=PolicyAction.BLOCK_ACTION.value,
                allowed=False,
                reason=f"Repeated recovery attempts threshold reached ({attempts}/{self.config.max_attempts}). Gateway retries blocked. Recommend alternative payment method.",
                risk_level="high",
                approval_required=False,
                limits=limits_dict,
                timestamp=now,
                request=request,
                execution_status="blocked"
            )

        # ---------------------------------------------------------------------
        # RULE 5: CUSTOMER RISK TIER & FRAUD / DISPUTE CHECK
        # ---------------------------------------------------------------------
        if cust_risk in {"blacklisted", "fraud", "dispute", "high_chargeback"}:
            return self._build_response(
                decision_id=decision_id,
                action=PolicyAction.BLOCK_ACTION.value,
                allowed=False,
                reason=f"High-risk customer status ('{cust_risk}') flagged. Automated financial intervention blocked.",
                risk_level="high",
                approval_required=False,
                limits=limits_dict,
                timestamp=now,
                request=request,
                execution_status="blocked"
            )

        # ---------------------------------------------------------------------
        # RULE 6: LOW RECOVERY CONFIDENCE CHECK
        # ---------------------------------------------------------------------
        min_conf = float(self.config.min_confidence)
        if conf < min_conf:
            # Low confidence: DO NOT act automatically under any circumstance
            if raw_action in self.config.allowed_passive_actions or raw_action == PolicyAction.REQUEST_MERCHANT_APPROVAL.value:
                return self._build_response(
                    decision_id=decision_id,
                    action=PolicyAction.REQUEST_MERCHANT_APPROVAL.value,
                    allowed=False,
                    reason=f"Low recovery confidence ({conf:.1%} < {min_conf:.1%} threshold). Automated execution forbidden; merchant approval required.",
                    risk_level="medium",
                    approval_required=True,
                    limits=limits_dict,
                    timestamp=now,
                    request=request,
                    execution_status="pending_approval"
                )
            else:
                # Active retry with low confidence -> hard block
                return self._build_response(
                    decision_id=decision_id,
                    action=PolicyAction.BLOCK_ACTION.value,
                    allowed=False,
                    reason=f"Low recovery confidence ({conf:.1%} < {min_conf:.1%} threshold) for active payment retry ('{raw_action}'). Action blocked.",
                    risk_level="high",
                    approval_required=False,
                    limits=limits_dict,
                    timestamp=now,
                    request=request,
                    execution_status="blocked"
                )

        # Explicit merchant approval request
        if raw_action == PolicyAction.REQUEST_MERCHANT_APPROVAL.value:
            return self._build_response(
                decision_id=decision_id,
                action=PolicyAction.REQUEST_MERCHANT_APPROVAL.value,
                allowed=False,
                reason="Merchant approval requested before executing financial intervention.",
                risk_level="high" if amount > self.config.medium_auto_amount else "medium",
                approval_required=True,
                limits=limits_dict,
                timestamp=now,
                request=request,
                execution_status="pending_approval"
            )

        # ---------------------------------------------------------------------
        # RULE 7: TRANSACTION VALUE TIERING & ACTION SAFETY RULES
        # ---------------------------------------------------------------------
        max_auto = self.config.max_auto_amount
        medium_auto = self.config.medium_auto_amount

        # Case 7A: HIGH VALUE (> ₹50,000) OR VIP CUSTOMER
        if amount > medium_auto or is_vip:
            vip_note = " (VIP Customer white-glove treatment)" if is_vip else ""
            return self._build_response(
                decision_id=decision_id,
                action=PolicyAction.REQUEST_MERCHANT_APPROVAL.value,
                allowed=False,
                reason=f"High-value transaction ₹{amount:,.2f} exceeds ₹{medium_auto:,.2f} threshold{vip_note}. Merchant approval required before dispatch.",
                risk_level="high" if amount > medium_auto else "medium",
                approval_required=True,
                limits=limits_dict,
                timestamp=now,
                request=request,
                execution_status="pending_approval"
            )

        # Case 7B: MEDIUM VALUE (₹15,000 - ₹50,000)
        if amount > max_auto:
            # Automatic only for specific safe actions (payment link, alt payment, notification)
            if raw_action in self.config.allowed_passive_actions:
                if assessed_risk == "high":
                    return self._build_response(
                        decision_id=decision_id,
                        action=PolicyAction.REQUEST_MERCHANT_APPROVAL.value,
                        allowed=False,
                        reason=f"Medium-value transaction (₹{amount:,.2f}) with high operational risk requires merchant approval.",
                        risk_level="high",
                        approval_required=True,
                        limits=limits_dict,
                        timestamp=now,
                        request=request,
                        execution_status="pending_approval"
                    )
                return self._build_response(
                    decision_id=decision_id,
                    action=raw_action,
                    allowed=True,
                    reason=f"Medium-value transaction (₹{amount:,.2f}) approved for safe passive action '{raw_action}'. Autonomous execution allowed.",
                    risk_level="medium",
                    approval_required=False,
                    limits=limits_dict,
                    timestamp=now,
                    request=request,
                    execution_status="ready"
                )
            else:
                # Active retry on medium-value -> requires merchant approval
                return self._build_response(
                    decision_id=decision_id,
                    action=PolicyAction.REQUEST_MERCHANT_APPROVAL.value,
                    allowed=False,
                    reason=f"Medium-value transaction (₹{amount:,.2f}) active retry ('{raw_action}') requires merchant approval.",
                    risk_level="medium",
                    approval_required=True,
                    limits=limits_dict,
                    timestamp=now,
                    request=request,
                    execution_status="pending_approval"
                )

        # Case 7C: LOW VALUE (<= ₹15,000)
        # Low-value + high-confidence + low-risk -> automatic
        if assessed_risk == "low" and conf >= min_conf:
            return self._build_response(
                decision_id=decision_id,
                action=raw_action,
                allowed=True,
                reason=f"Low-value transaction (₹{amount:,.2f}) with high confidence ({conf:.1%}) and low risk approved for autonomous execution.",
                risk_level="low",
                approval_required=False,
                limits=limits_dict,
                timestamp=now,
                request=request,
                execution_status="ready"
            )

        if assessed_risk == "medium":
            if raw_action in self.config.allowed_passive_actions:
                return self._build_response(
                    decision_id=decision_id,
                    action=raw_action,
                    allowed=True,
                    reason=f"Low-value transaction with medium risk approved for safe passive action '{raw_action}'.",
                    risk_level="medium",
                    approval_required=False,
                    limits=limits_dict,
                    timestamp=now,
                    request=request,
                    execution_status="ready"
                )
            else:
                return self._build_response(
                    decision_id=decision_id,
                    action=PolicyAction.REQUEST_MERCHANT_APPROVAL.value,
                    allowed=False,
                    reason=f"Low-value transaction active retry ('{raw_action}') under medium risk requires merchant confirmation.",
                    risk_level="medium",
                    approval_required=True,
                    limits=limits_dict,
                    timestamp=now,
                    request=request,
                    execution_status="pending_approval"
                )

        # High risk on low-value
        return self._build_response(
            decision_id=decision_id,
            action=PolicyAction.REQUEST_MERCHANT_APPROVAL.value,
            allowed=False,
            reason=f"Transaction flagged with high risk. Autonomous action prohibited; merchant approval required.",
            risk_level="high",
            approval_required=True,
            limits=limits_dict,
            timestamp=now,
            request=request,
            execution_status="pending_approval"
        )

    def evaluate_and_record(
        self,
        request: PolicyEvaluationRequest,
        db: Session,
        agent_decision_id: Optional[uuid.UUID] = None,
        opportunity_id: Optional[uuid.UUID] = None,
    ) -> PolicyDecisionResponse:
        """
        Evaluate proposed action and persist the PolicyDecision record in the database.
        """
        response = self.evaluate(request, db=db, agent_decision_id=agent_decision_id)

        # Persist into DB
        opp_uuid = opportunity_id
        if not opp_uuid and request.opportunity_id:
            try:
                opp_uuid = uuid.UUID(str(request.opportunity_id))
            except Exception:
                opp_uuid = None

        db_decision = PolicyDecision(
            id=response.policy_decision_id,
            agent_decision_id=agent_decision_id,
            opportunity_id=opp_uuid,
            action_type=response.action,
            allowed=response.allowed,
            approval_required=response.approval_required,
            risk_level=response.risk_level,
            max_amount_allowed=self.config.max_auto_amount,
            retry_limit=self.config.max_attempts,
            cooldown_seconds=request.cooldown_seconds or self.config.cooldown_seconds,
            confidence_threshold=self.config.min_confidence,
            limits_json=response.limits,
            decision_reason=response.reason,
        )
        db.add(db_decision)
        db.flush()

        return response

    def _build_response(
        self,
        decision_id: uuid.UUID,
        action: str,
        allowed: bool,
        reason: str,
        risk_level: str,
        approval_required: bool,
        limits: Dict[str, Any],
        timestamp: datetime,
        request: PolicyEvaluationRequest,
        execution_status: str
    ) -> PolicyDecisionResponse:
        """
        Construct structured response with the clear 4-step UI pipeline:
        AI recommendation -> Policy decision -> Approval required or automatic -> Execution
        """
        ai_rec = request.ai_recommendation or {}
        rec_action = ai_rec.get("recommended_action") or request.action
        rec_prob = float(ai_rec.get("recovery_probability", request.recovery_confidence))
        rec_impact = quantize_inr(ai_rec.get("estimated_impact", request.transaction_amount))
        rec_reason = ai_rec.get("reason") or "AI recommended recovery action based on diagnostic telemetry."
        rec_risk = ai_rec.get("risk_level") or risk_level

        # Stage 1: AI Recommendation
        stage_1 = PipelineStageAIRecommendation(
            recommended_action=rec_action,
            recovery_probability=rec_prob,
            estimated_impact=rec_impact,
            reason=rec_reason,
            risk_level=rec_risk
        )

        # Stage 2: Policy Decision
        stage_2 = PipelineStagePolicyDecision(
            policy_decision_id=decision_id,
            action=action,
            allowed=allowed,
            risk_level=risk_level,
            reason=reason
        )

        # Stage 3: Approval Required or Automatic Gate
        if allowed and not approval_required:
            mode = "automatic"
            expl = "Autonomous execution permitted: Meets value, confidence, and low-risk policy criteria."
        elif approval_required:
            mode = "approval_required"
            expl = "Human merchant approval required: Exceeds automated limits, high-value, VIP, or elevated risk."
        else:
            mode = "blocked"
            expl = "Action blocked by policy guardrails: Cooldown violation, repeated attempts, or unsafe action."

        stage_3 = PipelineStageApprovalGate(
            mode=mode,
            approval_required=approval_required,
            explanation=expl
        )

        # Stage 4: Execution
        stage_4 = PipelineStageExecution(
            status=execution_status,
            action_id=None,
            details={
                "action": action,
                "allowed": allowed,
                "approval_required": approval_required,
                "timestamp": timestamp.isoformat()
            }
        )

        pipeline = PolicyPipelineUI(
            stage_1_ai_recommendation=stage_1,
            stage_2_policy_decision=stage_2,
            stage_3_approval_gate=stage_3,
            stage_4_execution=stage_4
        )

        return PolicyDecisionResponse(
            policy_decision_id=decision_id,
            action=action,
            allowed=allowed,
            reason=reason,
            risk_level=risk_level,
            approval_required=approval_required,
            limits=limits,
            timestamp=timestamp,
            pipeline=pipeline
        )
