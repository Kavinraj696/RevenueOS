import uuid
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.enums import PolicyAction
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.recovery_opportunity import RecoveryOpportunity
from app.models.policy_decision import PolicyDecision
from app.services.policy_engine import FinancialActionPolicyEngine
from app.schemas.policy import PolicyEvaluationRequest, PolicyLimitsConfig



def test_rule_low_value_high_confidence_low_risk_automatic():
    """
    Test: Low-value (<= ₹15,000) + high-confidence (>= 0.60) + low-risk:
    Must permit automatic execution (allowed=True, approval_required=False).
    """
    engine = FinancialActionPolicyEngine()
    req = PolicyEvaluationRequest(
        action=PolicyAction.CREATE_PAYMENT_LINK.value,
        transaction_amount=Decimal("4999.00"),
        recovery_confidence=0.85,
        risk_level="low",
        previous_attempts=0
    )
    result = engine.evaluate(req)

    assert result.allowed is True
    assert result.approval_required is False
    assert result.risk_level == "low"
    assert result.action == PolicyAction.CREATE_PAYMENT_LINK.value
    assert "approved for autonomous execution" in result.reason.lower()
    assert result.pipeline.stage_3_approval_gate.mode == "automatic"
    assert result.pipeline.stage_4_execution.status == "ready"


def test_adversarial_high_amount_requires_approval():
    """
    Test: High amount (> ₹50,000) must NEVER be automatically executed.
    Must mandate merchant approval (allowed=False, approval_required=True, action=REQUEST_MERCHANT_APPROVAL).
    """
    engine = FinancialActionPolicyEngine()
    req = PolicyEvaluationRequest(
        action=PolicyAction.CREATE_PAYMENT_LINK.value,
        transaction_amount=Decimal("75000.00"),
        recovery_confidence=0.95,
        risk_level="low"
    )
    result = engine.evaluate(req)

    assert result.allowed is False
    assert result.approval_required is True
    assert result.action == PolicyAction.REQUEST_MERCHANT_APPROVAL.value
    assert "exceeds" in result.reason
    assert "approval required" in result.reason.lower()
    assert result.pipeline.stage_3_approval_gate.mode == "approval_required"
    assert result.pipeline.stage_4_execution.status == "pending_approval"


def test_adversarial_low_confidence_blocks_automatic_action():
    """
    Test: Low confidence (< 0.60):
    Must NOT act automatically under any circumstance.
    Passive links downgrade to approval_required; active retries are blocked.
    """
    engine = FinancialActionPolicyEngine()

    # Case A: Passive payment link with low confidence
    req_passive = PolicyEvaluationRequest(
        action=PolicyAction.CREATE_PAYMENT_LINK.value,
        transaction_amount=Decimal("2500.00"),
        recovery_confidence=0.42,
        risk_level="low"
    )
    res_passive = engine.evaluate(req_passive)
    assert res_passive.allowed is False
    assert res_passive.approval_required is True
    assert res_passive.action == PolicyAction.REQUEST_MERCHANT_APPROVAL.value
    assert "low recovery confidence" in res_passive.reason.lower()

    # Case B: Active retry with low confidence -> hard block
    req_retry = PolicyEvaluationRequest(
        action=PolicyAction.RETRY_ALLOWED_PAYMENT.value,
        transaction_amount=Decimal("2500.00"),
        recovery_confidence=0.35,
        risk_level="low"
    )
    res_retry = engine.evaluate(req_retry)
    assert res_retry.allowed is False
    assert res_retry.approval_required is False
    assert res_retry.action == PolicyAction.BLOCK_ACTION.value
    assert "blocked" in res_retry.reason.lower()


def test_adversarial_repeated_attempts_hard_block():
    """
    Test: Repeated recovery attempts (attempts >= 3):
    Must block further active retries after reaching threshold.
    """
    engine = FinancialActionPolicyEngine()
    req = PolicyEvaluationRequest(
        action=PolicyAction.RETRY_ALLOWED_PAYMENT.value,
        transaction_amount=Decimal("3500.00"),
        recovery_confidence=0.88,
        previous_attempts=3,
        risk_level="low"
    )
    result = engine.evaluate(req)

    assert result.allowed is False
    assert result.approval_required is False
    assert result.action == PolicyAction.BLOCK_ACTION.value
    assert "repeated recovery attempts threshold reached" in result.reason.lower()
    assert result.pipeline.stage_3_approval_gate.mode == "blocked"
    assert result.pipeline.stage_4_execution.status == "blocked"


def test_adversarial_expired_opportunity_blocked():
    """
    Test: Expired or already resolved opportunity:
    Must block all automated financial recovery actions.
    """
    engine = FinancialActionPolicyEngine()

    # Explicit flag is_expired
    req1 = PolicyEvaluationRequest(
        action=PolicyAction.CREATE_PAYMENT_LINK.value,
        transaction_amount=Decimal("1200.00"),
        recovery_confidence=0.90,
        is_expired=True
    )
    res1 = engine.evaluate(req1)
    assert res1.allowed is False
    assert res1.action == PolicyAction.BLOCK_ACTION.value
    assert "expired" in res1.reason.lower()

    # Status is recovered or dismissed
    req2 = PolicyEvaluationRequest(
        action=PolicyAction.CREATE_PAYMENT_LINK.value,
        transaction_amount=Decimal("1200.00"),
        recovery_confidence=0.90,
        opportunity_status="recovered"
    )
    res2 = engine.evaluate(req2)
    assert res2.allowed is False
    assert res2.action == PolicyAction.BLOCK_ACTION.value
    assert "already resolved" in res2.reason.lower()


def test_adversarial_duplicate_action_cooldown_violation():
    """
    Test: Duplicate action within cooldown period (< 14,400s):
    Must block duplicate dispatch to protect customer from notification fatigue and double-charging.
    """
    engine = FinancialActionPolicyEngine()
    now = datetime.now(timezone.utc)
    recent_time = now - timedelta(minutes=15)  # 900s ago, well under 14,400s cooldown

    req = PolicyEvaluationRequest(
        action=PolicyAction.SEND_RECOVERY_NOTIFICATION.value,
        transaction_amount=Decimal("2000.00"),
        recovery_confidence=0.80,
        cooldown_seconds=14400,
        last_action_timestamp=recent_time,
        last_action_type=PolicyAction.SEND_RECOVERY_NOTIFICATION.value
    )
    result = engine.evaluate(req)

    assert result.allowed is False
    assert result.approval_required is False
    assert result.action == PolicyAction.BLOCK_ACTION.value
    assert "cooldown active" in result.reason.lower()
    assert result.pipeline.stage_3_approval_gate.mode == "blocked"


def test_adversarial_unsafe_action_rejected():
    """
    Test: Unsafe, malformed, or unauthorized action strings:
    Must be immediately trapped and blocked by policy engine.
    """
    engine = FinancialActionPolicyEngine()
    unsafe_actions = [
        "FORCE_DIRECT_REFUND",
        "BYPASS_POLICY_EXECUTE",
        "ALTER_MERCHANT_LEDGER",
        "SQL_DROP_TABLE",
        "UNREGISTERED_ACTION_123"
    ]
    for bad_act in unsafe_actions:
        req = PolicyEvaluationRequest(
            action=bad_act,
            transaction_amount=Decimal("100.00"),
            recovery_confidence=0.99
        )
        res = engine.evaluate(req)
        assert res.allowed is False
        assert res.approval_required is False
        assert res.action == PolicyAction.BLOCK_ACTION.value
        assert "unrecognized or unsafe action" in res.reason.lower()


def test_medium_value_safe_actions_vs_active_retries():
    """
    Test: Medium-value (₹15,000 to ₹50,000):
    Automatic ONLY for specific safe actions (payment link, alt payment, notification).
    Active retries (gateway charge) require merchant approval.
    """
    engine = FinancialActionPolicyEngine()

    # Safe action: CREATE_PAYMENT_LINK -> Allowed automatically
    req_link = PolicyEvaluationRequest(
        action=PolicyAction.CREATE_PAYMENT_LINK.value,
        transaction_amount=Decimal("35000.00"),
        recovery_confidence=0.85,
        risk_level="low"
    )
    res_link = engine.evaluate(req_link)
    assert res_link.allowed is True
    assert res_link.approval_required is False
    assert res_link.action == PolicyAction.CREATE_PAYMENT_LINK.value
    assert "safe passive action" in res_link.reason.lower()

    # Active retry: RETRY_ALLOWED_PAYMENT -> Requires merchant approval
    req_retry = PolicyEvaluationRequest(
        action=PolicyAction.RETRY_ALLOWED_PAYMENT.value,
        transaction_amount=Decimal("35000.00"),
        recovery_confidence=0.85,
        risk_level="low"
    )
    res_retry = engine.evaluate(req_retry)
    assert res_retry.allowed is False
    assert res_retry.approval_required is True
    assert res_retry.action == PolicyAction.REQUEST_MERCHANT_APPROVAL.value
    assert "active retry" in res_retry.reason.lower()


def test_customer_risk_tier_defense():
    """
    Test: Customer marked with fraud/dispute/blacklisted status:
    Must block all automated financial intervention.
    """
    engine = FinancialActionPolicyEngine()
    req = PolicyEvaluationRequest(
        action=PolicyAction.CREATE_PAYMENT_LINK.value,
        transaction_amount=Decimal("1500.00"),
        recovery_confidence=0.90,
        customer_risk_tier="blacklisted"
    )
    res = engine.evaluate(req)
    assert res.allowed is False
    assert res.action == PolicyAction.BLOCK_ACTION.value
    assert "high-risk customer status" in res.reason.lower()


def test_determinism_and_reproducibility():
    """
    Test: Given identical inputs, engine must produce bit-identical decisions.
    Zero hallucination or non-deterministic stochastic variance.
    """
    engine = FinancialActionPolicyEngine()
    req = PolicyEvaluationRequest(
        action=PolicyAction.CREATE_PAYMENT_LINK.value,
        transaction_amount=Decimal("12500.00"),
        recovery_confidence=0.78,
        previous_attempts=1,
        risk_level="low"
    )

    res1 = engine.evaluate(req)
    res2 = engine.evaluate(req)

    assert res1.allowed == res2.allowed
    assert res1.approval_required == res2.approval_required
    assert res1.action == res2.action
    assert res1.reason == res2.reason
    assert res1.risk_level == res2.risk_level
    assert res1.limits == res2.limits


def test_db_persistence_via_evaluate_and_record(db_session, seeded_db):
    """
    Test: evaluate_and_record stores an immutable PolicyDecision row in the DB.
    """
    merchant = db_session.query(Merchant).first()
    opp = db_session.query(RecoveryOpportunity).filter(RecoveryOpportunity.merchant_id == merchant.id).first()
    assert opp is not None

    engine = FinancialActionPolicyEngine()
    req = PolicyEvaluationRequest(
        action=PolicyAction.CREATE_PAYMENT_LINK.value,
        transaction_amount=opp.gross_value_affected,
        recovery_confidence=0.82,
        opportunity_id=str(opp.id),
        risk_level="low"
    )

    recorded = engine.evaluate_and_record(req, db=db_session, opportunity_id=opp.id)
    assert recorded.policy_decision_id is not None

    # Query DB directly
    db_rec = db_session.query(PolicyDecision).filter(PolicyDecision.id == recorded.policy_decision_id).first()
    assert db_rec is not None
    assert db_rec.opportunity_id == opp.id
    assert db_rec.action_type == recorded.action
    assert db_rec.allowed == recorded.allowed
    assert db_rec.limits_json["max_auto_amount"] == 15000.0


def test_api_policy_endpoints(client, db_session, seeded_db):
    """
    Test: REST API endpoints:
    - POST /api/policy/evaluate
    - GET /api/policy/rules
    - GET /api/policy/decisions/{id}
    """
    # 1. GET /api/policy/rules
    resp_rules = client.get("/api/policy/rules")
    assert resp_rules.status_code == 200
    rules = resp_rules.json()
    assert float(rules["max_auto_amount"]) == 15000.0
    assert float(rules["min_confidence"]) == 0.60
    assert rules["max_attempts"] == 3

    # 2. POST /api/policy/evaluate (dry-run)
    eval_payload = {
        "action": "CREATE_PAYMENT_LINK",
        "transaction_amount": 4500.00,
        "recovery_confidence": 0.84,
        "previous_attempts": 0,
        "risk_level": "low"
    }
    resp_eval = client.post("/api/policy/evaluate", json=eval_payload)
    assert resp_eval.status_code == 200
    eval_data = resp_eval.json()
    assert eval_data["allowed"] is True
    assert eval_data["action"] == "CREATE_PAYMENT_LINK"
    assert "pipeline" in eval_data
    assert eval_data["pipeline"]["stage_1_ai_recommendation"]["title"] == "AI Recommendation"
    assert eval_data["pipeline"]["stage_2_policy_decision"]["title"] == "Policy Decision"
    assert eval_data["pipeline"]["stage_3_approval_gate"]["mode"] == "automatic"
    assert eval_data["pipeline"]["stage_4_execution"]["status"] == "ready"

    # 3. POST /api/policy/evaluate?record=true (persisted)
    resp_rec = client.post("/api/policy/evaluate?record=true", json=eval_payload)
    assert resp_rec.status_code == 200
    rec_data = resp_rec.json()
    dec_id = rec_data["policy_decision_id"]

    # 4. GET /api/policy/decisions/{decision_id}
    resp_get = client.get(f"/api/policy/decisions/{dec_id}")
    assert resp_get.status_code == 200
    get_data = resp_get.json()
    assert get_data["policy_decision_id"] == dec_id
    assert get_data["allowed"] is True
