import uuid
from decimal import Decimal
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.api.deps import get_db
from app.models.recovery_opportunity import RecoveryOpportunity
from app.schemas.recovery_opportunity import (
    RecoveryOpportunityResponse,
    RecoveryOpportunitiesListResponse,
)
from app.services.recovery_engine import RecoveryOpportunityEngine

router = APIRouter()

@router.get("", response_model=RecoveryOpportunitiesListResponse)
def list_recovery_opportunities(
    merchant_id: Optional[uuid.UUID] = Query(None, description="Filter opportunities by merchant ID"),
    status: Optional[str] = Query(None, description="Filter by status (open/investigating/action_selected/etc.)"),
    priority: Optional[str] = Query(None, description="Filter by priority (CRITICAL/HIGH/MEDIUM/LOW)"),
    min_expected_recovery: Optional[Decimal] = Query(None, description="Filter by minimum expected recoverable amount"),
    run_engine: bool = Query(True, description="Run opportunity evaluation engine to refresh candidates"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Retrieve ranked recovery opportunities scored by the deterministic Recovery Opportunity Engine.
    Combines Revenue Leaks, ML Recovery Probability, Transaction Value, Customer History,
    Available Recovery Actions, and Policy Constraints.
    """
    if run_engine:
        engine = RecoveryOpportunityEngine(db)
        engine.evaluate_and_sync(merchant_id=merchant_id)

    query = db.query(RecoveryOpportunity)
    if merchant_id:
        query = query.filter(RecoveryOpportunity.merchant_id == merchant_id)
    if status:
        query = query.filter(RecoveryOpportunity.status == status)
    if priority:
        query = query.filter(RecoveryOpportunity.priority == priority.upper())
    if min_expected_recovery is not None:
        query = query.filter(RecoveryOpportunity.expected_recovered_value >= min_expected_recovery)

    total_count = query.count()

    # Aggregate Portfolio Revenue Figures
    all_opps = query.all()
    total_gross = sum((o.gross_value_affected for o in all_opps), Decimal("0.00"))
    total_rar = sum((o.potentially_recoverable_value for o in all_opps), Decimal("0.00"))
    total_pot = sum((o.potentially_recoverable_value for o in all_opps), Decimal("0.00"))
    total_exp = sum((o.expected_recovered_value for o in all_opps), Decimal("0.00"))
    total_act = sum((o.actual_recovered_value or Decimal("0.00") for o in all_opps), Decimal("0.00"))

    # Monotonically order by priority score descending
    opps = query.order_by(
        desc(RecoveryOpportunity.priority_score),
        desc(RecoveryOpportunity.expected_recovered_value)
    ).offset(offset).limit(limit).all()

    items = []
    for idx, opp in enumerate(opps):
        resp_item = RecoveryOpportunityResponse.model_validate(opp)
        resp_item.priority_rank = offset + idx + 1
        items.append(resp_item)

    return RecoveryOpportunitiesListResponse(
        total=total_count,
        total_gross_affected=total_gross,
        total_revenue_at_risk=total_rar,
        total_potentially_recoverable=total_pot,
        total_expected_recovery=total_exp,
        total_actual_recovery=total_act,
        items=items
    )

@router.get("/{id}", response_model=RecoveryOpportunityResponse)
def get_recovery_opportunity(
    id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    Get detailed diagnostics for a specific recovery opportunity,
    including the deterministic explanation of why it is high priority,
    recommended action candidates, and policy constraint validation results.
    """
    opp = db.query(RecoveryOpportunity).filter(RecoveryOpportunity.id == id).first()
    if not opp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recovery opportunity with id {id} not found"
        )
    return opp
