"""
Evaluation Framework REST API
GET /api/evaluation/report      - Return cached evaluation report (or 404)
POST /api/evaluation/run        - Run a fresh evaluation (may take ~5s)
GET /api/evaluation/summary     - Return headline business metrics only
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.evaluation_framework import RevenueOSEvaluator

router = APIRouter()
logger = logging.getLogger(__name__)

# Module-level cache for last evaluation status
_eval_status: Dict[str, Any] = {"running": False, "last_error": None}


@router.post(
    "/run",
    summary="Run a full evaluation of the RevenueOS system",
    description=(
        "Generates a held-out test dataset (seed=99), trains Baseline and RevenueOS "
        "models, computes all metrics, and persists the report.  Returns the full report "
        "synchronously (typically 3–8 seconds)."
    ),
)
def run_evaluation(db: Session = Depends(get_db)) -> Dict[str, Any]:
    if _eval_status.get("running"):
        raise HTTPException(status_code=409, detail="Evaluation is already running. Check /api/evaluation/report.")

    _eval_status["running"] = True
    _eval_status["last_error"] = None
    try:
        evaluator = RevenueOSEvaluator(db)
        report = evaluator.run_full_evaluation()
        from dataclasses import asdict
        return {"status": "completed", "report": asdict(report)}
    except Exception as e:
        _eval_status["last_error"] = str(e)
        logger.error(f"Evaluation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {e}")
    finally:
        _eval_status["running"] = False


@router.get(
    "/report",
    summary="Retrieve the most recent evaluation report",
)
def get_evaluation_report() -> Dict[str, Any]:
    """
    Returns the most recently persisted evaluation report.
    Returns 404 if no report has been generated yet — call POST /run first.
    """
    report = RevenueOSEvaluator.load_cached_report()
    if not report:
        raise HTTPException(
            status_code=404,
            detail="No evaluation report found. POST /api/evaluation/run to generate one."
        )
    return {"status": "ok", "report": report}


@router.get(
    "/summary",
    summary="Return headline business metrics for the dashboard",
)
def get_evaluation_summary() -> Dict[str, Any]:
    """
    Returns the key business headline metrics for embedding in the dashboard.
    Includes: total recovered, incremental recovery over baseline, and ROI.
    """
    report = RevenueOSEvaluator.load_cached_report()
    if not report:
        return {
            "status": "no_report",
            "message": "No evaluation report available. Run POST /api/evaluation/run first.",
            "business": None,
            "verdict": None,
        }

    biz = report.get("business", {})
    return {
        "status": "ok",
        "generated_at": report.get("generated_at"),
        "test_dataset_size": report.get("test_dataset_size"),
        "verdict": report.get("summary_verdict"),
        "business": {
            "total_revenue_processed_inr": biz.get("total_revenue_processed_inr"),
            "revenue_at_risk_inr": biz.get("revenue_at_risk_inr"),
            "baseline_recovered_inr": biz.get("baseline_recovered_inr"),
            "baseline_recovery_rate": biz.get("baseline_recovery_rate"),
            "revenueos_recovered_inr": biz.get("revenueos_recovered_inr"),
            "revenueos_recovery_rate": biz.get("revenueos_recovery_rate"),
            "incremental_recovered_inr": biz.get("incremental_recovered_inr"),
            "roi_multiplier": biz.get("roi_multiplier"),
            "false_intervention_rate": biz.get("false_intervention_rate"),
        },
        "detection": report.get("detection"),
        "ml_baseline": report.get("ml_prediction_baseline"),
        "ml_revenueos": report.get("ml_prediction_revenueos"),
        "ranking": report.get("ranking"),
        "policy": report.get("policy"),
        "recovery": report.get("recovery"),
    }


@router.get(
    "/status",
    summary="Check if an evaluation is currently running",
)
def get_evaluation_status() -> Dict[str, Any]:
    return {
        "running": _eval_status.get("running", False),
        "last_error": _eval_status.get("last_error"),
    }

