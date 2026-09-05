import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.api.deps import get_db, get_merchant_or_404
from app.models import (
    Merchant,
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionStatus,
    CheckoutSession,
    CheckoutSessionStatus,
    RevenueLeak,
    RecoveryOpportunity,
)
from app.schemas.merchant import MerchantResponse, MerchantSummaryResponse

router = APIRouter()

@router.get("", response_model=List[MerchantResponse])
def list_merchants(db: Session = Depends(get_db)):
    """List all seeded demo merchants."""
    return db.query(Merchant).order_by(Merchant.created_at.desc()).all()

@router.get("/{merchant_id}", response_model=MerchantResponse)
def get_merchant(merchant: Merchant = Depends(get_merchant_or_404)):
    """Get single merchant details."""
    return merchant

@router.get("/{merchant_id}/summary", response_model=MerchantSummaryResponse)
def get_merchant_summary(
    merchant: Merchant = Depends(get_merchant_or_404),
    db: Session = Depends(get_db)
):
    """Get aggregated financial summary and revenue-at-risk KPIs for merchant."""
    m_id = merchant.id

    # 1. Payments metrics
    total_tx_count = db.query(Payment).filter(Payment.merchant_id == m_id).count()
    
    successful_tx = db.query(func.coalesce(func.sum(Payment.amount), Decimal("0.00"))).filter(
        Payment.merchant_id == m_id,
        Payment.status.in_([PaymentStatus.SUCCESS.value, PaymentStatus.RECOVERED.value])
    ).scalar() or Decimal("0.00")

    success_tx_count = db.query(Payment).filter(
        Payment.merchant_id == m_id,
        Payment.status.in_([PaymentStatus.SUCCESS.value, PaymentStatus.RECOVERED.value])
    ).count()

    failed_tx_count = db.query(Payment).filter(
        Payment.merchant_id == m_id,
        Payment.status == PaymentStatus.FAILED.value
    ).count()

    rar_amount = db.query(func.coalesce(func.sum(Payment.amount), Decimal("0.00"))).filter(
        Payment.merchant_id == m_id,
        Payment.status == PaymentStatus.FAILED.value
    ).scalar() or Decimal("0.00")

    if total_tx_count > 0:
        success_rate = (Decimal(str(success_tx_count)) / Decimal(str(total_tx_count)) * Decimal("100.00")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    else:
        success_rate = Decimal("0.00")

    # 2. Leaks & Opportunities
    active_leaks = db.query(RevenueLeak).filter(RevenueLeak.merchant_id == m_id).count()
    rec_opps = db.query(RecoveryOpportunity).filter(RecoveryOpportunity.merchant_id == m_id).count()

    # 3. Subscriptions
    active_subs = db.query(Subscription).filter(
        Subscription.merchant_id == m_id,
        Subscription.status == SubscriptionStatus.ACTIVE.value
    ).count()
    failed_subs = db.query(Subscription).filter(
        Subscription.merchant_id == m_id,
        Subscription.status == SubscriptionStatus.FAILED.value
    ).count()

    # 4. Checkout Sessions
    abandoned_cs_count = db.query(CheckoutSession).filter(
        CheckoutSession.merchant_id == m_id,
        CheckoutSession.status == CheckoutSessionStatus.ABANDONED.value
    ).count()
    abandoned_cart_vol = db.query(func.coalesce(func.sum(CheckoutSession.cart_value), Decimal("0.00"))).filter(
        CheckoutSession.merchant_id == m_id,
        CheckoutSession.status == CheckoutSessionStatus.ABANDONED.value
    ).scalar() or Decimal("0.00")

    return MerchantSummaryResponse(
        merchant_id=merchant.id,
        merchant_name=merchant.name,
        total_processed_volume=successful_tx,
        currency="INR",
        total_transactions_count=total_tx_count,
        successful_transactions_count=success_tx_count,
        failed_transactions_count=failed_tx_count,
        success_rate_percentage=success_rate,
        gross_revenue_at_risk=rar_amount,
        active_leaks_count=active_leaks,
        recovery_opportunities_count=rec_opps,
        active_subscriptions_count=active_subs,
        failed_subscriptions_count=failed_subs,
        abandoned_checkout_sessions_count=abandoned_cs_count,
        abandoned_cart_volume=abandoned_cart_vol
    )
