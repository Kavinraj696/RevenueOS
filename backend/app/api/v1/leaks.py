import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.api.deps import get_db
from app.models.revenue_leak import RevenueLeak
from app.schemas.revenue_leak import RevenueLeakResponse
from app.services.leak_detection import RevenueLeakDetector

router = APIRouter()

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
