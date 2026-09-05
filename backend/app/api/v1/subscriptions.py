from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.api.deps import get_db, get_merchant_or_404
from app.models import Merchant, Subscription
from app.schemas.subscription import (
    SubscriptionResponse,
    PaginatedSubscriptionsResponse,
)

router = APIRouter()

@router.get("/{merchant_id}/subscriptions", response_model=PaginatedSubscriptionsResponse)
def list_subscriptions(
    merchant: Merchant = Depends(get_merchant_or_404),
    status: Optional[str] = Query(None, description="Filter by status (active/failed/cancelled)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """Retrieve subscriptions for a merchant with recurring attempts history."""
    query = db.query(Subscription).filter(Subscription.merchant_id == merchant.id)

    if status:
        query = query.filter(Subscription.status == status)

    total = query.count()
    items = query.order_by(desc(Subscription.created_at)).offset(offset).limit(limit).all()

    return PaginatedSubscriptionsResponse(
        total=total,
        items=items,
        limit=limit,
        offset=offset
    )
