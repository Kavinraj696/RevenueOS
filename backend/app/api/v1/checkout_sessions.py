from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.api.deps import get_db, get_merchant_or_404
from app.models import Merchant, CheckoutSession
from app.schemas.checkout_session import (
    CheckoutSessionResponse,
    PaginatedCheckoutSessionsResponse,
)

router = APIRouter()

@router.get("/{merchant_id}/checkout-sessions", response_model=PaginatedCheckoutSessionsResponse)
def list_checkout_sessions(
    merchant: Merchant = Depends(get_merchant_or_404),
    status: Optional[str] = Query(None, description="Filter by status (completed/abandoned)"),
    stage_dropped: Optional[str] = Query(None, description="Filter by drop-off stage (otp_entry, etc.)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """Retrieve checkout sessions for a merchant with cart drop-off analysis."""
    query = db.query(CheckoutSession).filter(CheckoutSession.merchant_id == merchant.id)

    if status:
        query = query.filter(CheckoutSession.status == status)
    if stage_dropped:
        query = query.filter(CheckoutSession.stage_dropped == stage_dropped)

    total = query.count()
    items = query.order_by(desc(CheckoutSession.created_at)).offset(offset).limit(limit).all()

    return PaginatedCheckoutSessionsResponse(
        total=total,
        items=items,
        limit=limit,
        offset=offset
    )
