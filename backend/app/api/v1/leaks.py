import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from decimal import Decimal
from datetime import datetime, timezone, timedelta
from app.api.deps import get_db
from app.models.revenue_leak import RevenueLeak
from app.models.merchant import Merchant
from app.schemas.revenue_leak import (
    RevenueLeakResponse,
    LeakDetectionRequest,
    LeakDetectionSummaryResponse,
)
from app.services.leak_detection import RevenueLeakDetector

router = APIRouter()

@router.post("/detect", response_model=LeakDetectionSummaryResponse)
def trigger_leak_detection(
    payload: LeakDetectionRequest,
    db: Session = Depends(get_db)
):
    """
    Trigger deterministic revenue leak detection on-demand for a merchant or all merchants.
    Allows specifying explicit analysis and baseline time windows.
    """
    if payload.merchant_id:
        merchant = db.query(Merchant).filter(Merchant.id == payload.merchant_id).first()
        if not merchant:
            raise HTTPException(status_code=404, detail=f"Merchant {payload.merchant_id} not found")

    detector = RevenueLeakDetector(db)
    detected = detector.detect_leaks(
        merchant_id=payload.merchant_id,
        analysis_window_start=payload.analysis_window_start,
        analysis_window_end=payload.analysis_window_end,
        baseline_window_start=payload.baseline_window_start,
        baseline_window_end=payload.baseline_window_end,
        window_days=payload.window_days or 7,
    )

    total_gross = sum((l.gross_value_affected for l in detected), Decimal("0.00"))
    total_rar = sum((l.revenue_at_risk for l in detected), Decimal("0.00"))

    now_utc = datetime.now(timezone.utc)
    a_start = payload.analysis_window_start or (detected[0].detection_window_start if detected else now_utc - timedelta(days=payload.window_days or 7))
    a_end = payload.analysis_window_end or (detected[0].detection_window_end if detected else now_utc)

    return LeakDetectionSummaryResponse(
        merchant_id=payload.merchant_id,
        detected_leaks_count=len(detected),
        total_gross_affected_revenue=total_gross,
        total_revenue_at_risk=total_rar,
        analysis_window_start=a_start,
        analysis_window_end=a_end,
        leaks=detected,
    )


@router.get("", response_model=List[RevenueLeakResponse])
def list_revenue_leaks(
    merchant_id: Optional[uuid.UUID] = Query(None, description="Filter leaks by merchant ID"),
    status: Optional[str] = Query(None, description="Filter by status (open/investigating/resolved/dismissed)"),
    leak_type: Optional[str] = Query(None, description="Filter by leak type (payment_failure/checkout_abandonment/etc.)"),
    severity: Optional[str] = Query(None, description="Filter by severity (critical/high/medium/low)"),
    run_detection: bool = Query(True, description="Run detection engine to refresh leaks before returning"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """
    Retrieve all detected revenue leaks with comprehensive diagnostic evidence.
    Optionally runs the deterministic detection engine before returning.
    """
    detector = RevenueLeakDetector(db)
    if run_detection:
        if merchant_id:
            detector.run_detection_for_merchant(merchant_id)
        else:
            detector.run_detection_for_all_merchants()

    query = db.query(RevenueLeak)
    if merchant_id:
        query = query.filter(RevenueLeak.merchant_id == merchant_id)
    if status:
        query = query.filter(RevenueLeak.status == status)
    if leak_type:
        query = query.filter(RevenueLeak.leak_type == leak_type)
    if severity:
        query = query.filter(RevenueLeak.severity == severity)

    leaks = query.order_by(desc(RevenueLeak.severity_score), desc(RevenueLeak.created_at)).offset(offset).limit(limit).all()
    return leaks

@router.get("/{leak_id}", response_model=RevenueLeakResponse)
def get_revenue_leak(
    leak_id: uuid.UUID,
    db: Session = Depends(get_db)
):
    """
    Get deep-dive evidence, metrics, and root cause candidates for a specific revenue leak.
    """
    leak = db.query(RevenueLeak).filter(RevenueLeak.id == leak_id).first()
    if not leak:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Revenue leak with id {leak_id} not found"
        )
    return leak
