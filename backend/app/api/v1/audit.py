import os
import uuid
from decimal import Decimal
from datetime import datetime
from typing import Optional, List
from pathlib import Path

from fastapi import APIRouter, Depends, Query, HTTPException, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.merchant import Merchant
from app.models.recovery_action import RecoveryAction
from app.services.audit_service import AuditService
from app.schemas.audit import (
    AuditEventResponse,
    AuditEventListResponse,
    ActionCausalityTimelineResponse
)

router = APIRouter()

# Path to the Audit Timeline HTML
STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"
AUDIT_HTML_PATH = STATIC_DIR / "audit.html"


def parse_uuid_safely(val: Optional[str]) -> Optional[uuid.UUID]:
    if not val:
        return None
    try:
        return uuid.UUID(str(val).strip())
    except (ValueError, AttributeError):
        return None


@router.get("", response_model=AuditEventListResponse, summary="Query immutable audit event ledger")
@router.get("/", response_model=AuditEventListResponse, summary="Query immutable audit event ledger")
def get_audit_events(
    merchant: Optional[str] = Query(None, description="Merchant UUID or name filter"),
    transaction: Optional[str] = Query(None, description="Payment transaction UUID filter"),
    opportunity: Optional[str] = Query(None, description="Recovery opportunity UUID filter"),
    action: Optional[str] = Query(None, description="Recovery action UUID filter"),
    date: Optional[str] = Query(None, description="Exact date in YYYY-MM-DD format"),
    event_type: Optional[str] = Query(None, description="Audit event type filter (snake_case)"),
    eventType: Optional[str] = Query(None, description="Alias for event_type"),
    actor: Optional[str] = Query(None, description="Actor filter (SYSTEM, AI_RECOVERY_AGENT, etc.)"),
    status: Optional[str] = Query(None, description="Status filter (SUCCESS, FAILED, PENDING, etc.)"),
    limit: int = Query(50, ge=1, le=200, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    db: Session = Depends(get_db)
):
    """
    Search and filter immutable audit records.
    Supports filtering by merchant, transaction, opportunity, action, date, and event type.
    Never exposes sensitive API keys or credentials in response payloads.
    """
    audit_svc = AuditService(db)

    # Resolve event type from either alias
    ev_type = event_type or eventType

    # Parse UUID filters
    merchant_uuid = parse_uuid_safely(merchant)
    if not merchant_uuid and merchant:
        # Check if merchant query is a name
        m_record = db.query(Merchant).filter(Merchant.name.ilike(f"%{merchant.strip()}%")).first()
        if m_record:
            merchant_uuid = m_record.id

    tx_uuid = parse_uuid_safely(transaction)
    opp_uuid = parse_uuid_safely(opportunity)
    act_uuid = parse_uuid_safely(action)

    events, total = audit_svc.query_events(
        merchant_id=merchant_uuid,
        transaction_id=tx_uuid,
        opportunity_id=opp_uuid,
        action_id=act_uuid,
        event_type=ev_type,
        actor=actor,
        status=status,
        date_str=date,
        limit=limit,
        offset=offset
    )

    # Fallback to system-wide operational audit records if merchant has 0 events and no narrow filters
    if total == 0 and merchant_uuid and not any([tx_uuid, opp_uuid, act_uuid, ev_type, actor, status, date]):
        events, total = audit_svc.query_events(
            limit=limit,
            offset=offset
        )

    items = [AuditEventResponse.model_validate(ev) for ev in events]

    return AuditEventListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=items
    )


@router.get("/timeline/{action_id}", response_model=ActionCausalityTimelineResponse, summary="Get full causality timeline for an action")
def get_action_causality_timeline(
    action_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    Retrieves the complete, chronological causality sequence for a specific recovery action.
    Traces from original transaction failure, leak detection, ML scoring, opportunity ranking,
    AI investigation & recommendation, policy gate decision, approval, provider execution,
    webhook verification, and final recovered amount ledger entry.
    """
    act = db.query(RecoveryAction).filter(RecoveryAction.id == action_id).first()
    if not act:
        raise HTTPException(status_code=404, detail=f"Recovery action {action_id} not found")

    audit_svc = AuditService(db)
    events = audit_svc.get_action_causality_timeline(action_id)

    timeline_items = [AuditEventResponse.model_validate(ev) for ev in events]

    return ActionCausalityTimelineResponse(
        action_id=act.id,
        opportunity_id=act.opportunity_id,
        transaction_id=act.opportunity.payment_id if act.opportunity else None,
        action_type=act.action_type,
        status=act.status,
        amount=act.amount,
        provider=act.provider,
        total_events=len(timeline_items),
        timeline=timeline_items
    )


@router.get("/ui", response_class=HTMLResponse, summary="Serve interactive Audit Timeline UI")
def serve_audit_ui():
    """Serves the standalone interactive Audit Timeline web application for judges and operators."""
    if not AUDIT_HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="Audit UI template not found")
    with open(AUDIT_HTML_PATH, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)


@router.get("/trace/{trace_id}", response_model=List[AuditEventResponse], summary="Get chronological audit events for a causal trace")
@router.get("/{trace_id}", response_model=List[AuditEventResponse], summary="Get chronological audit events for a causal trace")
def get_causal_trace(
    trace_id: str,
    db: Session = Depends(get_db)
):
    """
    Retrieves the complete causal trace sequence of audit events for a specific trace ID,
    action ID, or agent run.
    """
    audit_svc = AuditService(db)
    events = audit_svc.get_causal_trace(trace_id)
    if not events:
        try:
            act_id = uuid.UUID(trace_id.strip())
            events = audit_svc.get_action_causality_timeline(act_id)
        except Exception:
            pass
    return [AuditEventResponse.model_validate(ev) for ev in events]

