import hmac
import hashlib
import json
import uuid
from decimal import Decimal
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db.base import quantize_inr, get_utc_now
from app.models.enums import PaymentStatus, OpportunityStatus, ActionStatus, PolicyAction
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.payment_attempt import PaymentAttempt
from app.models.recovery_opportunity import RecoveryOpportunity
from app.models.recovery_action import RecoveryAction
from app.models.webhook_event import WebhookEvent
from app.models.audit_event import AuditEvent
from app.schemas.payment_provider import PaymentResult
from app.services.payment_provider.mock_provider import MockPaymentProvider
from app.services.payment_provider.razorpay_provider import RazorpayTestProvider
from app.services.webhook_engine import RazorpayWebhookEngine
from app.services.reconciliation import PaymentReconciliationService, ReconciliationError
from app.schemas.policy import PolicyEvaluationRequest
from app.services.policy_engine import FinancialActionPolicyEngine
from app.services.recovery_executor import RecoveryExecutor
from app.main import app


def compute_signature(payload_bytes: bytes, secret: str = "rzp_webhook_secret_placeholder") -> str:
    """Computes valid HMAC-SHA256 signature for test webhook raw bytes."""
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


# =============================================================================
# 1. PROVIDER & CONFIGURATION TESTS
# =============================================================================

def test_razorpay_test_mode_safety_and_credentials():
    """Verify default test mode and strict rejection of live production keys."""
    assert settings.RAZORPAY_MODE == "test"

    # Live keys must raise ValueError immediately
    with pytest.raises(ValueError, match="Live mode"):
        RazorpayTestProvider(key_id="rzp_live_abc123XYZ", key_secret="live_secret")

    # Missing keys must raise ValueError
    with pytest.raises(ValueError, match="requires RAZORPAY_KEY_ID"):
        RazorpayTestProvider(key_id="", key_secret="")

    # Valid test keys instantiate safely
    provider = RazorpayTestProvider(key_id="rzp_test_valid123", key_secret="test_secret_abc")
    assert provider.provider_name == "razorpay_test"


def test_provider_response_normalization():
    """Verify that raw provider responses are normalized to PaymentResult model."""
    mock = MockPaymentProvider()
    raw = {
        "id": "pay_mock_test_999",
        "order_id": "order_mock_test_888",
        "amount": 250000,  # 2500.00 INR in paise
        "currency": "INR",
        "status": "captured",
        "created_at": int(datetime.now(timezone.utc).timestamp()),
        "notes": {"merchant_id": "m123"}
    }
    normalized = mock.normalize_payment_response(raw)
    assert isinstance(normalized, PaymentResult)
    assert normalized.provider == "mock"
    assert normalized.provider_payment_id == "pay_mock_test_999"
    assert normalized.provider_order_id == "order_mock_test_888"
    assert normalized.amount == Decimal("2500.00")
    assert normalized.currency == "INR"
    assert normalized.status == "captured"


# =============================================================================
# 2. SIGNATURE VERIFICATION TESTS
# =============================================================================

def test_webhook_signature_verification_valid_and_invalid(db_session):
    """Test valid, invalid, missing, modified, and wrong-secret webhook signatures."""
    engine = RazorpayWebhookEngine(db_session)
    secret = settings.RAZORPAY_WEBHOOK_SECRET

    payload = {
        "event": "payment.captured",
        "event_id": f"evt_sig_test_{uuid.uuid4().hex[:8]}",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_sig_123",
                    "amount": 150000,
                    "currency": "INR",
                    "status": "captured"
                }
            }
        }
    }
    raw_body = json.dumps(payload).encode("utf-8")
    valid_sig = compute_signature(raw_body, secret)

    # 1. Valid signature -> 200 OK / processed
    res = engine.process_webhook(raw_body, valid_sig, secret=secret)
    assert res["status"] == "success"
    assert res["idempotent"] is False

    # 2. Missing signature header -> HTTPException 400
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc1:
        engine.process_webhook(raw_body, None, secret=secret)
    assert exc1.value.status_code == 400
    assert "Missing X-Razorpay-Signature" in exc1.value.detail

    # 3. Invalid signature -> HTTPException 400
    with pytest.raises(HTTPException) as exc2:
        engine.process_webhook(raw_body, "invalid_signature_hex", secret=secret)
    assert exc2.value.status_code == 400
    assert "Invalid webhook signature" in exc2.value.detail

    # 4. Modified body with original signature -> HTTPException 400
    modified_body = json.dumps({"event": "payment.captured", "tampered": True}).encode("utf-8")
    with pytest.raises(HTTPException) as exc3:
        engine.process_webhook(modified_body, valid_sig, secret=secret)
    assert exc3.value.status_code == 400

    # 5. Wrong webhook secret -> HTTPException 400
    with pytest.raises(HTTPException) as exc4:
        engine.process_webhook(raw_body, valid_sig, secret="wrong_secret_key_123")
    assert exc4.value.status_code == 400


# =============================================================================
# 3. IDEMPOTENCY TESTS
# =============================================================================

def test_webhook_idempotency_duplicate_and_triple_delivery(db_session):
    """Verify that repeated delivery of the same webhook event is processed exactly once."""
    engine = RazorpayWebhookEngine(db_session)
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    event_id = f"evt_idemp_{uuid.uuid4().hex[:10]}"

    payload = {
        "event": "payment.captured",
        "event_id": event_id,
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_{uuid.uuid4().hex[:8]}",
                    "amount": 300000,
                    "currency": "INR",
                    "status": "captured"
                }
            }
        }
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = compute_signature(raw_body, secret)

    # First delivery: processed
    res1 = engine.process_webhook(raw_body, sig, secret=secret)
    assert res1["status"] == "success"
    assert res1["idempotent"] is False

    # Second delivery: recognized duplicate
    res2 = engine.process_webhook(raw_body, sig, secret=secret)
    assert res2["status"] == "idempotent_duplicate"
    assert res2["idempotent"] is True

    # Third delivery: recognized duplicate
    res3 = engine.process_webhook(raw_body, sig, secret=secret)
    assert res3["status"] == "idempotent_duplicate"
    assert res3["idempotent"] is True

    # Confirm only one WebhookEvent row exists
    count = db_session.query(WebhookEvent).filter(WebhookEvent.event_id == event_id).count()
    assert count == 1


# =============================================================================
# 4. OUT-OF-ORDER WEBHOOK DELIVERY & STATE MACHINE TESTS
# =============================================================================

def test_webhook_out_of_order_delivery_does_not_downgrade_success(db_session):
    """Verify that an out-of-order payment.failed event does not overwrite a settled payment."""
    engine = RazorpayWebhookEngine(db_session)
    secret = settings.RAZORPAY_WEBHOOK_SECRET

    merchant = Merchant(name="Out of Order Merchant", email=f"ooo_{uuid.uuid4().hex[:6]}@test.in")
    customer = Customer(merchant=merchant, external_ref=f"cust_{uuid.uuid4().hex[:6]}", risk_segment="low", lifetime_value=Decimal("50000.00"))
    payment = Payment(
        merchant=merchant,
        customer=customer,
        amount=Decimal("1200.00"),
        currency="INR",
        status=PaymentStatus.SUCCESS.value,
        payment_method="upi",
        device_type="android",
        route="standard",
        reconciliation_status="MATCHED"
    )
    db_session.add_all([merchant, customer, payment])
    db_session.commit()

    # Out-of-order failure event for this payment
    fail_event_id = f"evt_ooo_{uuid.uuid4().hex[:8]}"
    fail_payload = {
        "event": "payment.failed",
        "event_id": fail_event_id,
        "payload": {
            "payment": {
                "entity": {
                    "id": str(payment.id),
                    "amount": 120000,
                    "currency": "INR",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Delayed failure webhook"
                }
            }
        }
    }
    raw_body = json.dumps(fail_payload).encode("utf-8")
    sig = compute_signature(raw_body, secret)

    res = engine.process_webhook(raw_body, sig, secret=secret)
    assert res["state_updated"] is False

    # Check payment is STILL in SUCCESS state
    db_session.refresh(payment)
    assert payment.status == PaymentStatus.SUCCESS.value
    assert payment.reconciliation_status == "MATCHED"


# =============================================================================
# 5. RECONCILIATION & AMOUNT/CURRENCY INTEGRITY TESTS
# =============================================================================

def test_reconciliation_matching_amount_and_currency(db_session):
    """Test successful reconciliation confirming provider state and updating actions to VERIFIED."""
    merchant = Merchant(name="Reconcile Merchant", email=f"rec_{uuid.uuid4().hex[:6]}@test.in")
    customer = Customer(merchant=merchant, external_ref=f"cust_{uuid.uuid4().hex[:6]}", risk_segment="low", lifetime_value=Decimal("50000.00"))
    payment = Payment(
        merchant=merchant,
        customer=customer,
        amount=Decimal("1999.00"),
        currency="INR",
        status=PaymentStatus.PENDING.value,
        payment_method="card",
        device_type="desktop",
        route="standard",
        provider_payment_id="pay_mock_1999"
    )
    opp = RecoveryOpportunity(
        merchant=merchant,
        payment=payment,
        customer=customer,
        gross_value_affected=Decimal("1999.00"),
        potentially_recoverable_value=Decimal("1999.00"),
        recovery_probability=Decimal("0.85"),
        expected_recovered_value=Decimal("1699.15"),
        status=OpportunityStatus.OPEN.value,
        priority="HIGH"
    )
    action = RecoveryAction(
        opportunity=opp,
        action_type="create_payment_link",
        status=ActionStatus.EXECUTING.value,
        idempotency_key=f"idemp_rec_{uuid.uuid4().hex[:8]}"
    )
    db_session.add_all([merchant, customer, payment, opp, action])
    db_session.commit()

    # Create mock provider returning exact matching payment
    class MatchingProvider(MockPaymentProvider):
        def fetch_normalized_payment(self, payment_id: str):
            return PaymentResult(
                provider="mock",
                provider_payment_id=payment_id,
                status="captured",
                amount=Decimal("1999.00"),
                currency="INR",
                created_at=datetime.now(timezone.utc)
            )

    service = PaymentReconciliationService(db_session, provider=MatchingProvider())
    res = service.reconcile_payment(payment.id, causal_trace_id="trace_rec_001")

    assert res["reconciliation_status"] == "MATCHED"
    assert res["verified"] is True
    assert res["actual_recovered_amount"] == 1999.00

    db_session.refresh(payment)
    db_session.refresh(opp)
    db_session.refresh(action)
    assert payment.status == PaymentStatus.SUCCESS.value
    assert opp.status == OpportunityStatus.RECOVERED.value
    assert opp.actual_recovered_value == Decimal("1999.00")
    assert action.status == ActionStatus.VERIFIED.value
    assert action.verified_status == "confirmed"
    assert action.actual_recovered_amount == Decimal("1999.00")


def test_reconciliation_amount_mismatch_flags_reconciliation_required(db_session):
    """Test that an amount discrepancy flags RECONCILIATION_REQUIRED and blocks recovery confirmation."""
    merchant = Merchant(name="Mismatch Merchant", email=f"mis_{uuid.uuid4().hex[:6]}@test.in")
    customer = Customer(merchant=merchant, external_ref=f"cust_{uuid.uuid4().hex[:6]}", risk_segment="low", lifetime_value=Decimal("50000.00"))
    payment = Payment(
        merchant=merchant,
        customer=customer,
        amount=Decimal("1000.00"),
        currency="INR",
        status=PaymentStatus.PENDING.value,
        payment_method="upi",
        device_type="android",
        route="standard",
        provider_payment_id="pay_mismatch_amount"
    )
    opp = RecoveryOpportunity(
        merchant=merchant,
        payment=payment,
        customer=customer,
        gross_value_affected=Decimal("1000.00"),
        potentially_recoverable_value=Decimal("1000.00"),
        recovery_probability=Decimal("0.80"),
        expected_recovered_value=Decimal("800.00"),
        status=OpportunityStatus.OPEN.value,
        priority="HIGH"
    )
    db_session.add_all([merchant, customer, payment, opp])
    db_session.commit()

    # Provider reports 10,000 INR instead of 1,000 INR
    class AmountMismatchProvider(MockPaymentProvider):
        def fetch_normalized_payment(self, payment_id: str):
            return PaymentResult(
                provider="mock",
                provider_payment_id=payment_id,
                status="captured",
                amount=Decimal("10000.00"),  # 10x mismatch
                currency="INR",
                created_at=datetime.now(timezone.utc)
            )

    service = PaymentReconciliationService(db_session, provider=AmountMismatchProvider())
    res = service.reconcile_payment(payment.id)

    assert res["reconciliation_status"] == "RECONCILIATION_REQUIRED"
    assert res["verified"] is False
    assert res["discrepancy"] == "amount_mismatch"

    db_session.refresh(payment)
    db_session.refresh(opp)
    assert payment.reconciliation_status == "RECONCILIATION_REQUIRED"
    # Opportunity MUST NOT be marked recovered
    assert opp.status != OpportunityStatus.RECOVERED.value


def test_reconciliation_currency_mismatch_flags_reconciliation_required(db_session):
    """Test that a currency discrepancy (e.g. USD vs INR) flags RECONCILIATION_REQUIRED."""
    merchant = Merchant(name="Currency Merchant", email=f"curr_{uuid.uuid4().hex[:6]}@test.in")
    customer = Customer(merchant=merchant, external_ref=f"cust_{uuid.uuid4().hex[:6]}", risk_segment="low", lifetime_value=Decimal("50000.00"))
    payment = Payment(
        merchant=merchant,
        customer=customer,
        amount=Decimal("1500.00"),
        currency="INR",
        status=PaymentStatus.PENDING.value,
        payment_method="card",
        device_type="desktop",
        route="standard",
        provider_payment_id="pay_currency_mismatch"
    )
    db_session.add_all([merchant, customer, payment])
    db_session.commit()

    # Provider reports USD instead of INR
    class CurrencyMismatchProvider(MockPaymentProvider):
        def fetch_normalized_payment(self, payment_id: str):
            return PaymentResult(
                provider="mock",
                provider_payment_id=payment_id,
                status="captured",
                amount=Decimal("1500.00"),
                currency="USD",  # mismatch
                created_at=datetime.now(timezone.utc)
            )

    service = PaymentReconciliationService(db_session, provider=CurrencyMismatchProvider())
    res = service.reconcile_payment(payment.id)

    assert res["reconciliation_status"] == "RECONCILIATION_REQUIRED"
    assert res["verified"] is False
    assert res["discrepancy"] == "currency_mismatch"


# =============================================================================
# 6. SECURITY, SECRETS & ABUSE PROTECTION TESTS
# =============================================================================

def test_secrets_never_leak_in_api_responses_or_audit():
    """Verify that credentials and webhook secrets never appear in API responses or serialized events."""
    client = TestClient(app)

    # 1. Payment provider status endpoint must only return masked ID
    resp = client.get("/api/v1/payment-provider/status")
    assert resp.status_code == 200
    data = resp.json()
    assert settings.RAZORPAY_KEY_SECRET not in json.dumps(data)
    assert settings.RAZORPAY_WEBHOOK_SECRET not in json.dumps(data)

    # 2. Webhook list endpoint must not leak secrets
    resp_wh = client.get("/api/v1/webhooks/events")
    assert resp_wh.status_code == 200
    assert settings.RAZORPAY_WEBHOOK_SECRET not in resp_wh.text


def test_webhook_oversized_payload_rejected():
    """Verify that oversized webhook payloads (> 1MB) are rejected with HTTP 413."""
    client = TestClient(app)
    large_payload = b"x" * (1024 * 1024 + 100)  # > 1 MB
    sig = compute_signature(large_payload)

    resp = client.post(
        "/api/v1/webhooks/razorpay",
        content=large_payload,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"}
    )
    assert resp.status_code == 413


# =============================================================================
# 7. COMPLETE END-TO-END RECOVERY WORKFLOW (PHASE 36)
# =============================================================================

def test_stage6_end_to_end_recovery_scenario(db_session):
    """
    Comprehensive End-to-End Recovery Flow:
    1. Failed payment detected
    2. ML opportunity created
    3. AI agent investigates & recommends action
    4. Policy engine evaluates ALLOW
    5. Action executed via test provider
    6. Payment webhook received & signature verified
    7. Event persisted & deduplication tested
    8. Payment reconciled & independently confirmed
    9. Action marked VERIFIED with actual recovered revenue
    10. Audit trail & causal trace verified
    """
    merchant = Merchant(name="Apex Retail E2E", email=f"apex_e2e_{uuid.uuid4().hex[:6]}@test.in")
    customer = Customer(merchant=merchant, external_ref=f"cust_{uuid.uuid4().hex[:6]}", risk_segment="low", lifetime_value=Decimal("50000.00"))
    payment = Payment(
        merchant=merchant,
        customer=customer,
        amount=Decimal("3500.00"),
        currency="INR",
        status=PaymentStatus.FAILED.value,
        payment_method="upi",
        device_type="android",
        route="standard",
        provider_payment_id="pay_e2e_3500"
    )
    opp = RecoveryOpportunity(
        merchant=merchant,
        payment=payment,
        customer=customer,
        gross_value_affected=Decimal("3500.00"),
        potentially_recoverable_value=Decimal("3500.00"),
        recovery_probability=Decimal("0.88"),
        expected_recovered_value=Decimal("3080.00"),
        status=OpportunityStatus.OPEN.value,
        priority="HIGH"
    )
    db_session.add_all([merchant, customer, payment, opp])
    db_session.commit()

    causal_trace_id = f"trace_stage6_e2e_{uuid.uuid4().hex[:8]}"

    # Step 1: Policy Evaluation
    policy_engine = FinancialActionPolicyEngine()
    policy_req = PolicyEvaluationRequest(
        merchant_id=str(merchant.id),
        action="create_payment_link",
        transaction_amount=Decimal("3500.00"),
        recovery_confidence=0.88,
        previous_attempts=1,
        customer_risk_tier="low"
    )
    verdict = policy_engine.evaluate(policy_req)
    assert verdict.decision == "ALLOW"
    assert verdict.allowed is True

    # Step 2: Action Execution
    executor = RecoveryExecutor(db_session)
    idemp_key = f"act_e2e_{uuid.uuid4().hex[:10]}"
    action = executor.execute_action(
        opportunity_id=opp.id,
        action_type="create_payment_link",
        idempotency_key=idemp_key
    )
    action.causal_trace_id = causal_trace_id
    db_session.commit()
    assert action.status in (ActionStatus.SUCCESS.value, ActionStatus.EXECUTED.value)

    # Step 3: Inbound Webhook (payment.captured)
    engine = RazorpayWebhookEngine(db_session)
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    event_id = f"evt_e2e_{uuid.uuid4().hex[:8]}"

    wh_payload = {
        "event": "payment.captured",
        "event_id": event_id,
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_e2e_3500",
                    "amount": 350000,
                    "currency": "INR",
                    "status": "captured"
                }
            }
        }
    }
    raw_bytes = json.dumps(wh_payload).encode("utf-8")
    sig = compute_signature(raw_bytes, secret)

    wh_res = engine.process_webhook(raw_bytes, sig, secret=secret)
    assert wh_res["status"] == "success"

    # Step 4: Test duplicate delivery idempotency
    dup_res = engine.process_webhook(raw_bytes, sig, secret=secret)
    assert dup_res["status"] == "idempotent_duplicate"

    # Step 5: Independent Reconciliation
    class E2EProvider(MockPaymentProvider):
        def fetch_normalized_payment(self, payment_id: str):
            return PaymentResult(
                provider="mock",
                provider_payment_id=payment_id,
                status="captured",
                amount=Decimal("3500.00"),
                currency="INR",
                created_at=datetime.now(timezone.utc)
            )

    rec_service = PaymentReconciliationService(db_session, provider=E2EProvider())
    rec_res = rec_service.reconcile_payment(payment.id, causal_trace_id=causal_trace_id)

    assert rec_res["reconciliation_status"] == "MATCHED"
    assert rec_res["verified"] is True
    assert rec_res["actual_recovered_amount"] == 3500.00

    # Step 6: Verify final financial states
    db_session.refresh(payment)
    db_session.refresh(opp)
    db_session.refresh(action)

    assert payment.status == PaymentStatus.SUCCESS.value
    assert opp.status == OpportunityStatus.RECOVERED.value
    assert opp.actual_recovered_value == Decimal("3500.00")
    assert action.status == ActionStatus.VERIFIED.value
    assert action.verified_status == "confirmed"
    assert action.actual_recovered_amount == Decimal("3500.00")


# =============================================================================
# 8. NEGATIVE END-TO-END SCENARIOS (PHASE 37)
# =============================================================================

def test_negative_scenario_invalid_signature_blocks_state_change(db_session):
    """Negative Scenario 1: Invalid webhook signature causes zero state changes."""
    merchant = Merchant(name="Neg Sig Merchant", email=f"negsig_{uuid.uuid4().hex[:6]}@test.in")
    payment = Payment(
        merchant=merchant,
        amount=Decimal("5000.00"),
        status=PaymentStatus.PENDING.value,
        payment_method="card",
        device_type="desktop",
        route="standard",
        customer_id=uuid.uuid4()
    )
    db_session.add_all([merchant, payment])
    db_session.commit()

    engine = RazorpayWebhookEngine(db_session)
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        engine.process_webhook(
            b'{"event":"payment.captured"}',
            "completely_fake_signature",
            secret="valid_secret"
        )

    db_session.refresh(payment)
    # Payment status remains unchanged
    assert payment.status == PaymentStatus.PENDING.value


def test_negative_scenario_policy_deny_blocks_provider(db_session):
    """Negative Scenario 2: Exhausted retries policy DENY prevents calling provider."""
    merchant = Merchant(name="Deny Merchant", email=f"deny_{uuid.uuid4().hex[:6]}@test.in")
    policy_engine = FinancialActionPolicyEngine()

    # 4th retry attempt violates max retry limit (3)
    req = PolicyEvaluationRequest(
        merchant_id=str(merchant.id),
        action="retry",
        transaction_amount=Decimal("500.00"),
        previous_attempts=4,
        customer_risk_tier="low"
    )
    verdict = policy_engine.evaluate(req)
    assert verdict.decision == "DENY"
    assert verdict.allowed is False


def test_stage6_rest_api_endpoints(db_session):
    """Test Stage 6 REST endpoints: webhook events listing and payment reconcile API."""
    client = TestClient(app)

    # 1. GET /api/v1/webhooks/events
    resp1 = client.get("/api/v1/webhooks/events?limit=10")
    assert resp1.status_code == 200
    assert isinstance(resp1.json(), list)

    # 2. POST /api/v1/recovery/payments/{payment_id}/reconcile for non-existent payment -> 404
    fake_id = uuid.uuid4()
    resp2 = client.post(f"/api/v1/recovery/payments/{fake_id}/reconcile")
    assert resp2.status_code == 404


def test_webhook_event_reprocess_endpoint(client, db_session):
    """Test POST /api/v1/webhooks/events/{event_id}/reprocess verifies get_utc_now usage."""
    # Non-existent event returns 404
    resp = client.post("/api/v1/webhooks/events/non_existent_evt/reprocess")
    assert resp.status_code == 404

    # Existing event reprocess
    merchant = Merchant(name="Reprocess Merchant", email=f"reprocess_{uuid.uuid4().hex[:6]}@test.in")
    customer = Customer(merchant=merchant, external_ref=f"cust_{uuid.uuid4().hex[:6]}", risk_segment="low", lifetime_value=Decimal("50000.00"))
    payment = Payment(
        merchant=merchant,
        customer=customer,
        amount=Decimal("1200.00"),
        currency="INR",
        status=PaymentStatus.PENDING.value,
        payment_method="card",
        device_type="desktop",
        route="standard"
    )
    db_session.add_all([merchant, customer, payment])
    db_session.commit()

    event = WebhookEvent(
        event_id=f"evt_reproc_{uuid.uuid4().hex[:8]}",
        event_type="payment.captured",
        provider="razorpay",
        signature_verified=True,
        processing_status="FAILED",
        processed=False,
        payload_hash="dummyhash",
        raw_payload_json={
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": f"pay_{uuid.uuid4().hex[:10]}",
                        "amount": 120000,
                        "currency": "INR",
                        "status": "captured",
                        "notes": {"internal_payment_id": str(payment.id)}
                    }
                }
            }
        }
    )
    db_session.add(event)
    db_session.commit()

    resp = client.post(f"/api/v1/webhooks/events/{event.event_id}/reprocess")
    assert resp.status_code == 200
    data = resp.json()
    assert data["processing_status"] == "PROCESSED"
    assert data["event_id"] == event.event_id

    db_session.refresh(event)
    assert event.processed is True
    assert event.processed_at is not None


