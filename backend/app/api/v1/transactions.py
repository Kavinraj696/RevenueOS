from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.api.deps import get_db, get_merchant_or_404
from app.models import Merchant, Payment, PaymentAttempt, PaymentStatus
from app.schemas.payment import (
    PaymentResponse,
    PaymentFailureResponse,
    PaginatedPaymentsResponse,
)

router = APIRouter()

@router.get("/{merchant_id}/transactions", response_model=PaginatedPaymentsResponse)
def list_transactions(
    merchant: Merchant = Depends(get_merchant_or_404),
    status: Optional[str] = Query(None, description="Filter by status (success/failed/recovered/pending)"),
    payment_method: Optional[str] = Query(None, description="Filter by payment method (upi/card/netbanking)"),
    bank: Optional[str] = Query(None, description="Filter by bank code (HDFC/ICICI/SBI/etc.)"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """Retrieve paginated transactions for a merchant with optional filtering."""
    query = db.query(Payment).filter(Payment.merchant_id == merchant.id)

    if status:
        query = query.filter(Payment.status == status)
    if payment_method:
        query = query.filter(Payment.payment_method == payment_method)
    if bank:
        query = query.filter(Payment.bank == bank)

    total = query.count()
    items = query.order_by(desc(Payment.created_at)).offset(offset).limit(limit).all()

    return PaginatedPaymentsResponse(
        total=total,
        items=items,
        limit=limit,
        offset=offset
    )

@router.get("/{merchant_id}/failures", response_model=List[PaymentFailureResponse])
def list_failures(
    merchant: Merchant = Depends(get_merchant_or_404),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """Retrieve failed transactions with error codes, failure reasons, and attempt counts."""
    failed_payments = db.query(Payment).filter(
        Payment.merchant_id == merchant.id,
        Payment.status == PaymentStatus.FAILED.value
    ).order_by(desc(Payment.created_at)).offset(offset).limit(limit).all()

    failures = []
    for p in failed_payments:
        last_attempt = (
            db.query(PaymentAttempt)
            .filter(PaymentAttempt.payment_id == p.id)
            .order_by(desc(PaymentAttempt.attempt_number))
            .first()
        )
        attempt_count = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == p.id).count()
        
        failures.append(
            PaymentFailureResponse(
                payment_id=p.id,
                customer_id=p.customer_id,
                amount=p.amount,
                currency=p.currency,
                payment_method=p.payment_method,
                bank=p.bank,
                device_type=p.device_type,
                route=p.route,
                created_at=p.created_at,
                attempt_count=attempt_count,
                last_error_code=last_attempt.error_code if last_attempt else None,
                last_failure_reason=last_attempt.failure_reason if last_attempt else None,
                is_recoverable=True
            )
        )

    return failures
