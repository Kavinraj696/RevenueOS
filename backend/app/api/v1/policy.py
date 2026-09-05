import uuid
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.policy_decision import PolicyDecision
from app.services.policy_engine import FinancialActionPolicyEngine
from app.schemas.policy import (
    PolicyEvaluationRequest,
    PolicyDecisionResponse,
    PolicyLimitsConfig,
    PolicyPipelineUI,
    PipelineStageAIRecommendation,
    PipelineStagePolicyDecision,
    PipelineStageApprovalGate,
    PipelineStageExecution,
)

router = APIRouter()


@router.post(
    "/evaluate",
    response_model=PolicyDecisionResponse,
    summary="Evaluate an action against deterministic financial policies",
    description="Evaluates whether an action is allowed, requires merchant approval, or is blocked."
)
def evaluate_policy(
    request: PolicyEvaluationRequest,
    record: bool = Query(False, description="Whether to persist the decision to the policy audit ledger"),
    db: Session = Depends(get_db),
) -> PolicyDecisionResponse:
    """
    Evaluate proposed action against deterministic financial governance rules.
    Zero LLM execution authority: strict, mathematically bounded evaluation.
    """
    engine = FinancialActionPolicyEngine()
    if record:
        res = engine.evaluate_and_record(request, db=db)
        db.commit()
        return res
    return engine.evaluate(request, db=db)


@router.get(
    "/rules",
    response_model=PolicyLimitsConfig,
    summary="Retrieve active policy governance rules and thresholds"
)
def get_policy_rules() -> PolicyLimitsConfig:
    """
    Returns the current active financial governance limits, thresholds, and allowed safe actions.
    """
    engine = FinancialActionPolicyEngine()
    return engine.config


@router.get(
    "/decisions/{decision_id}",
    response_model=PolicyDecisionResponse,
    summary="Get a recorded policy decision by ID"
)
def get_policy_decision(
    decision_id: uuid.UUID,
    db: Session = Depends(get_db)
) -> PolicyDecisionResponse:
    """
    Retrieve an immutable policy decision from the database audit log.
    """
    dec = db.query(PolicyDecision).filter(PolicyDecision.id == decision_id).first()
    if not dec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy decision {decision_id} not found."
        )

    # Reconstruct 4-stage UI pipeline
    stage_1 = PipelineStageAIRecommendation(
        recommended_action=dec.action_type,
        recovery_probability=float(dec.confidence_threshold),
        estimated_impact=dec.max_amount_allowed,
        reason="AI recommended action evaluated by deterministic policy engine.",
        risk_level=dec.risk_level
    )
    stage_2 = PipelineStagePolicyDecision(
        policy_decision_id=dec.id,
        action=dec.action_type,
        allowed=dec.allowed,
        risk_level=dec.risk_level,
        reason=dec.decision_reason
    )
    if dec.allowed and not dec.approval_required:
        mode = "automatic"
        expl = "Autonomous execution permitted: Meets value, confidence, and low-risk policy criteria."
    elif dec.approval_required:
        mode = "approval_required"
        expl = "Human merchant approval required: Exceeds automated limits, high-value, VIP, or elevated risk."
    else:
        mode = "blocked"
        expl = "Action blocked by policy guardrails: Cooldown violation, repeated attempts, or unsafe action."

    stage_3 = PipelineStageApprovalGate(
        mode=mode,
        approval_required=dec.approval_required,
        explanation=expl
    )
    stage_4 = PipelineStageExecution(
        status="executed" if (dec.allowed and not dec.approval_required) else ("pending_approval" if dec.approval_required else "blocked"),
        action_id=None,
        details={"persisted": True, "created_at": dec.created_at.isoformat()}
    )

    pipeline = PolicyPipelineUI(
        stage_1_ai_recommendation=stage_1,
        stage_2_policy_decision=stage_2,
        stage_3_approval_gate=stage_3,
        stage_4_execution=stage_4
    )

    return PolicyDecisionResponse(
        policy_decision_id=dec.id,
        action=dec.action_type,
        allowed=dec.allowed,
        reason=dec.decision_reason,
        risk_level=dec.risk_level,
        approval_required=dec.approval_required,
        limits=dec.limits_json or {},
        timestamp=dec.created_at,
        pipeline=pipeline
    )
