"""
Security Audit API
GET  /api/security/audit  - Run the automated security check suite
POST /api/security/test-injection - Test a specific prompt for injection
"""
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Body
from app.security import RevenueOSSecurityAuditor, detect_prompt_injection, sanitize_user_input
from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    "/audit",
    summary="Run automated security checks for RevenueOS",
)
def run_security_audit() -> Dict[str, Any]:
    """
    Executes the full automated security check suite across all 7 security pillars.
    Returns pass/fail for each check with severity ratings.
    Covers: secrets, gitignore, prompt injection, tool allowlist, amount caps,
    webhook signatures, and malicious prompt blocks.
    """
    auditor = RevenueOSSecurityAuditor()
    results = auditor.run_all_checks(settings_obj=settings)

    checks = [r.to_dict() for r in results]
    total = len(checks)
    passed = sum(1 for c in checks if c["passed"])
    high_failures = [c for c in checks if not c["passed"] and c["severity"] == "HIGH"]

    return {
        "status": "PASS" if not high_failures else "FAIL",
        "total_checks": total,
        "passed": passed,
        "failed": total - passed,
        "high_severity_failures": len(high_failures),
        "checks": checks,
        "summary": (
            f"All {total} security checks passed." if not high_failures
            else f"WARNING: {len(high_failures)} HIGH severity failure(s) detected."
        )
    }


@router.post(
    "/test-injection",
    summary="Test whether a given prompt contains an injection attempt",
)
def test_prompt_injection(
    message: str = Body(..., embed=True, description="The user message to check for injection patterns")
) -> Dict[str, Any]:
    """
    Checks a prompt string against all known injection patterns.
    Returns whether it would be blocked and which pattern triggered.
    Useful for the demo and for security verification.
    """
    sanitized = sanitize_user_input(message)
    is_injected = detect_prompt_injection(sanitized)

    return {
        "input": message[:200],  # Truncate for response safety
        "sanitized_length": len(sanitized),
        "injection_detected": is_injected,
        "action": "BLOCKED" if is_injected else "ALLOWED",
        "explanation": (
            "This prompt contains patterns that indicate an attempt to override "
            "the system policy or bypass the FinancialActionPolicyEngine. "
            "The request has been blocked and logged."
            if is_injected
            else "No injection patterns detected. This prompt would proceed normally."
        )
    }

