import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.api.deps import get_db
from app.models.agent_decision import AgentDecision
from app.schemas.agent import (
    AgentInvestigationRequest,
    AgentInvestigationResponse,
    AgentDecisionResponse,
    AgentDecisionsListResponse
)
from app.services.agent.recovery_agent import AIRecoveryAgent

router = APIRouter()


@router.post("/investigate", response_model=AgentInvestigationResponse)
def trigger_investigation(
    req: AgentInvestigationRequest,
    db: Session = Depends(get_db)
):
    """
    Trigger the autonomous 9-stage AI Recovery Agent workflow:
    OBSERVE -> INVESTIGATE -> DIAGNOSE -> QUANTIFY -> RECOMMEND -> POLICY CHECK -> EXECUTE_OR_APPROVE -> VERIFY -> REPORT.
    Grounded in deterministic tool calls without LLM hallucinations.
    """
    agent = AIRecoveryAgent(db)
    response = agent.run_workflow(
        merchant_id=req.merchant_id,
        leak_id=req.leak_id,
        opportunity_id=req.opportunity_id,
        transaction_id=req.transaction_id,
        auto_execute=req.auto_execute
    )
    return response


@router.get("/decisions", response_model=AgentDecisionsListResponse)
def list_agent_decisions(
    merchant_id: Optional[uuid.UUID] = Query(None, description="Filter decisions by merchant ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """List historical decisions made by the AI Recovery Agent."""
    query = db.query(AgentDecision)
    total = query.count()
    decisions = query.order_by(desc(AgentDecision.created_at)).offset(offset).limit(limit).all()

    return AgentDecisionsListResponse(
        total=total,
        items=decisions
    )


@router.get("/decisions/{id}", response_model=AgentDecisionResponse)
def get_agent_decision(
    id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """Retrieve full diagnostic evidence and justification for an agent decision."""
    decision = db.query(AgentDecision).filter(AgentDecision.id == id).first()
    if not decision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent decision {id} not found"
        )
    return decision
