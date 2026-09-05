import uuid
from decimal import Decimal
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.api.deps import get_db
from app.models.recovery_action import RecoveryAction
from app.models.recovery_opportunity import RecoveryOpportunity
from app.models.audit_event import AuditEvent
from app.schemas.recovery_action import (
    RecoveryActionResponse,
    RecoveryActionListResponse,
    RecoveryPipelineExecutionRequest,
    RecoveryPipelineExecutionResponse,
    RecoveryActionApprovalRequest,
    RecoveryFallbackDemoResponse,
)
from app.services.recovery_executor import (
    RecoveryExecutor,
    RecoveryExecutionError,
    DuplicateActionError,
)

router = APIRouter()


@router.post("/execute", response_model=RecoveryPipelineExecutionResponse)
def execute_recovery_pipeline(
    req: RecoveryPipelineExecutionRequest,
    db: Session = Depends(get_db)
):
    """
    Execute the complete end-to-end recovery pipeline:
    Recovery Opportunity -> AI Agent -> Recommended Action -> Policy Engine
    -> Approval if required -> Recovery Executor -> Provider -> Webhook/Event
    -> Verification -> Audit -> Dashboard Update.
    """
    executor = RecoveryExecutor(db)
    try:
        res = executor.run_pipeline(
            opportunity_id=req.opportunity_id,
            transaction_id=req.transaction_id,
            merchant_id=req.merchant_id,
            action_type=req.action_type,
            simulate_failure=req.simulate_failure,
            failure_type=req.failure_type or "GATEWAY_TIMEOUT",
            auto_execute=req.auto_execute
        )

        return RecoveryPipelineExecutionResponse(
            pipeline_id=res["pipeline_id"],
            opportunity_id=res["opportunity_id"],
            status=res["status"],
            action=RecoveryActionResponse.model_validate(res["action"]),
            policy_verdict=res["policy_verdict"],
            approval_required=res["approval_required"],
            audit_event_id=res["audit_event_id"],
            fallback_action=RecoveryActionResponse.model_validate(res["fallback_action"]) if res.get("fallback_action") else None,
            execution_trail=res["execution_trail"]
        )
    except DuplicateActionError as dup_err:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(dup_err))
    except RecoveryExecutionError as rec_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(rec_err))


@router.post("/opportunities/{id}/execute", response_model=RecoveryPipelineExecutionResponse)
def execute_opportunity_recovery(
    id: uuid.UUID,
    action_type: Optional[str] = Query(None, description="Optional action type override"),
    simulate_failure: bool = Query(False, description="Simulate provider failure"),
    db: Session = Depends(get_db)
):
    """Execute recovery pipeline for a specific opportunity ID."""
    req = RecoveryPipelineExecutionRequest(
        opportunity_id=id,
        action_type=action_type,
        simulate_failure=simulate_failure
    )
    return execute_recovery_pipeline(req=req, db=db)


@router.post("/actions/{id}/approve", response_model=RecoveryActionResponse)
def approve_recovery_action(
    id: uuid.UUID,
    req: RecoveryActionApprovalRequest,
    db: Session = Depends(get_db)
):
    """Merchant approval gate: approves a pending recovery action and dispatches execution."""
    executor = RecoveryExecutor(db)
    try:
        act = executor.approve_action(action_id=id, notes=req.notes)
        return act
    except RecoveryExecutionError as ex:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ex))


@router.post("/actions/{id}/retry", response_model=RecoveryActionResponse)
def retry_recovery_action(
    id: uuid.UUID,
    alternative_action_type: Optional[str] = Query(None, description="Optional alternative action type"),
    db: Session = Depends(get_db)
):
    """Handles an action failure gracefully and executes an alternative recovery action."""
    executor = RecoveryExecutor(db)
    try:
        _, alt_act = executor.handle_action_failure_and_fallback(
            failed_action_id=id,
            alternative_action_type=alternative_action_type
        )
        return alt_act
    except RecoveryExecutionError as ex:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ex))


@router.get("/actions", response_model=RecoveryActionListResponse)
def list_recovery_actions(
    opportunity_id: Optional[uuid.UUID] = Query(None, description="Filter by opportunity ID"),
    status: Optional[str] = Query(None, description="Filter by status (pending/approved/executing/success/failed/blocked/expired)"),
    action_type: Optional[str] = Query(None, description="Filter by action type"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """List recovery actions with all 11 required fields and causal references."""
    query = db.query(RecoveryAction)
    if opportunity_id:
        query = query.filter(RecoveryAction.opportunity_id == opportunity_id)
    if status:
        query = query.filter(RecoveryAction.status == status.lower())
    if action_type:
        query = query.filter(RecoveryAction.action_type == action_type.lower())

    total = query.count()
    actions = query.order_by(desc(RecoveryAction.created_at)).offset(offset).limit(limit).all()

    return RecoveryActionListResponse(
        total=total,
        items=[RecoveryActionResponse.model_validate(a) for a in actions]
    )


@router.get("/actions/{id}", response_model=RecoveryActionResponse)
def get_recovery_action(
    id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Get single recovery action details by ID."""
    act = db.query(RecoveryAction).filter(RecoveryAction.id == id).first()
    if not act:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Action {id} not found")
    return act


@router.post("/demo/failure-fallback", response_model=RecoveryFallbackDemoResponse)
def demo_failure_and_graceful_fallback(
    opportunity_id: Optional[uuid.UUID] = Query(None, description="Optional opportunity ID"),
    db: Session = Depends(get_db)
):
    """
    Dedicated demo scenario showing:
    AI recommends action -> action fails -> system handles failure gracefully -> alternative action is recommended and succeeds!
    Required for final demo.
    """
    opp = None
    if opportunity_id:
        opp = db.query(RecoveryOpportunity).filter(RecoveryOpportunity.id == opportunity_id).first()
    if not opp:
        opp = db.query(RecoveryOpportunity).order_by(desc(RecoveryOpportunity.created_at)).first()
    if not opp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No recovery opportunity available for demo.")

    # Ensure demo opportunity does not conflict with existing active actions
    existing_link = db.query(RecoveryAction).filter(
        RecoveryAction.opportunity_id == opp.id,
        RecoveryAction.action_type == "create_payment_link",
        RecoveryAction.status.in_(["pending", "approved", "executing", "success"])
    ).first()
    if existing_link:
        opp = RecoveryOpportunity(
            id=uuid.uuid4(),
            merchant_id=opp.merchant_id,
            gross_value_affected=Decimal("4999.00"),
            potentially_recoverable_value=Decimal("4099.00"),
            recovery_probability=Decimal("0.8200"),
            expected_recovered_value=Decimal("4099.00"),
            priority="HIGH",
            priority_score=Decimal("85.00"),
            risk="low",
            explanation="Dedicated opportunity for resilient failure and fallback demo."
        )
        db.add(opp)
        db.commit()

    executor = RecoveryExecutor(db)

    # 1. AI recommends action -> executes with simulated failure
    act1 = executor.execute_action(
        opportunity_id=opp.id,
        action_type="create_payment_link",
        simulate_failure=True,
        failure_type="GATEWAY_TIMEOUT"
    )

    # 2. Catch failure gracefully and execute alternative action
    failed_act, alt_act = executor.handle_action_failure_and_fallback(
        failed_action_id=act1.id,
        alternative_action_type="recommend_alternative_payment"
    )

    # Count audit events for causality proof
    audit_count = db.query(AuditEvent).filter(
        AuditEvent.merchant_id == opp.merchant_id
    ).count()

    return RecoveryFallbackDemoResponse(
        demo_name="Resilient Recovery Fallback & Alternative Route Execution",
        opportunity_id=opp.id,
        stage_1_initial_action=RecoveryActionResponse.model_validate(failed_act),
        stage_2_failure_simulation=failed_act.result or {"error": "GATEWAY_TIMEOUT"},
        stage_3_graceful_handling=(
            "Primary action 'create_payment_link' failed due to Razorpay gateway timeout. "
            "RevenueOS caught the failure gracefully without user interruption, logged the audit event, "
            "and dynamically routed to alternative payment recommendation."
        ),
        stage_4_alternative_action=RecoveryActionResponse.model_validate(alt_act),
        overall_recovery_status="recovered" if alt_act.status == "success" else alt_act.status,
        audit_events_recorded=audit_count
    )


@router.post("/payments/{payment_id}/reconcile", summary="Reconcile Payment")
def reconcile_payment_endpoint(
    payment_id: uuid.UUID,
    provider_payment_id: Optional[str] = Query(None, description="Optional provider payment ID"),
    causal_trace_id: Optional[str] = Query(None, description="Optional causal trace ID"),
    db: Session = Depends(get_db)
):
    """
    Independently reconciles payment status against Razorpay test provider.
    Verifies amount and currency integrity before confirming recovered revenue.
    """
    from app.services.reconciliation import PaymentReconciliationService, ReconciliationError
    service = PaymentReconciliationService(db)
    try:
        res = service.reconcile_payment(
            payment_id=payment_id,
            provider_payment_id=provider_payment_id,
            causal_trace_id=causal_trace_id
        )
        return res
    except ReconciliationError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

