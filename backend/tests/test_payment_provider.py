import hmac
import hashlib
import json
import uuid
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.models.enums import PaymentStatus, SubscriptionStatus, OpportunityStatus
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.payment_attempt import PaymentAttempt
from app.models.subscription import Subscription
from app.models.recovery_opportunity import RecoveryOpportunity
from app.models.webhook_event import WebhookEvent
from app.models.audit_event import AuditEvent
from app.services.payment_provider.base import PaymentProvider
from app.services.payment_provider.mock_provider import MockPaymentProvider
from app.services.payment_provider.razorpay_provider import RazorpayTestProvider
from app.services.payment_provider.registry import (
    ProviderMode,
    PaymentProviderRegistry,
    provider_registry,
    get_payment_provider,
)
from app.services.webhook_engine import RazorpayWebhookEngine


def compute_test_signature(body_bytes: bytes, secret: str = "test_webhook_secret_123") -> str:
    """Helper to compute valid HMAC-SHA256 signature for test webhooks."""
    return hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()


def test_mock_payment_provider_lifecycle():
    """Test MockPaymentProvider links, payments, subscriptions, and signature verification."""
    provider = MockPaymentProvider()
    assert provider.provider_name == "mock"

    # 1. Create payment link
    link = provider.create_payment_link(
        amount=Decimal("2499.00"),
        description="Demo Recovery Link",
        customer_name="Rohan Sharma",
        customer_phone="+919876543210"
    )
    assert link["id"].startswith("plink_mock_")
    assert link["amount"] == 249900
    assert link["status"] == "created"
    assert "rzp.io/i/mock_" in link["short_url"]

    # 2. Fetch & cancel link
    fetched = provider.fetch_payment_link(link["id"])
    assert fetched["id"] == link["id"]
    cancelled = provider.cancel_payment_link(link["id"])
    assert cancelled["status"] == "cancelled"

    # 3. Capture payment
    payment = provider.fetch_payment("pay_mock_123")
    assert payment["id"] == "pay_mock_123"
    captured = provider.capture_payment("pay_mock_123", Decimal("2499.00"))
    assert captured["status"] == "captured"
    assert captured["captured"] is True

    # 4. Subscription lifecycle
    sub = provider.create_subscription(plan_id="plan_saas_monthly", total_count=12)
    assert sub["id"].startswith("sub_mock_")
    assert sub["status"] == "active"
    canc_sub = provider.cancel_subscription(sub["id"])
    assert canc_sub["status"] == "cancelled"

    # 5. Webhook signature verification
    body = b'{"event":"test"}'
    sig = hmac.new(b"rzp_webhook_secret_placeholder", body, hashlib.sha256).hexdigest()
    assert provider.verify_webhook_signature(body, sig, secret="rzp_webhook_secret_placeholder") is True
    assert provider.verify_webhook_signature(body, "invalid_sig", secret="rzp_webhook_secret_placeholder") is False


def test_razorpay_test_provider_guardrails():
    """Verify RazorpayTestProvider safety guardrails and rejection of live keys."""
    # Rejection of live keys
    with pytest.raises(ValueError, match="Live mode credentials"):
        RazorpayTestProvider(key_id="rzp_live_dangerous_key", key_secret="live_secret")

    # Missing keys
    with pytest.raises(ValueError, match="requires RAZORPAY_KEY_ID"):
        RazorpayTestProvider(key_id="", key_secret="")

    # Valid test initialization
    provider = RazorpayTestProvider(key_id="rzp_test_valid_key", key_secret="test_secret")
    assert provider.provider_name == "razorpay_test"
    assert provider.key_id == "rzp_test_valid_key"

    # Signature verification
    body = b'{"event":"payment.captured"}'
    valid_sig = compute_test_signature(body, secret="secret_xyz")
    assert provider.verify_webhook_signature(body, valid_sig, secret="secret_xyz") is True
    assert provider.verify_webhook_signature(body, "bad_sig", secret="secret_xyz") is False


def test_provider_registry_automatic_fallback():
    """
    Test: If RAZORPAY_TEST mode is requested but credentials are missing or placeholders,
    the registry must automatically fall back to MockPaymentProvider without failing.
    """
    registry = PaymentProviderRegistry()

    # When credentials are placeholder strings
    assert registry.is_razorpay_configured() is False

    # Setting mode to RAZORPAY_TEST should fall back to mock
    status_info = registry.set_mode(ProviderMode.RAZORPAY_TEST)
    assert status_info["requested_mode"] == "RAZORPAY_TEST"
    assert status_info["effective_provider"] == "mock"
    assert status_info["fallback_active"] is True

    # Active provider instance must be MockPaymentProvider
    active_prov = registry.get_provider()
    assert isinstance(active_prov, MockPaymentProvider)

    # Revert to MOCK
    registry.set_mode(ProviderMode.MOCK)
    assert registry.get_status()["effective_provider"] == "mock"


def test_webhook_signature_verification_rejected(db_session):
    """
    Test: Webhook signature verification:
    Missing or tampered signature header must be rejected with HTTP 400.
    """
    engine = RazorpayWebhookEngine(db_session)
    body = b'{"event":"payment.captured","payload":{}}'

    # Case 1: Missing signature
    with pytest.raises(Exception) as exc_info:
        engine.process_webhook(body, signature_header=None)
    assert "Missing X-Razorpay-Signature" in str(exc_info.value.detail)

    # Case 2: Invalid signature
    with pytest.raises(Exception) as exc_info:
        engine.process_webhook(body, signature_header="tampered_hash_signature", secret="test_sec")
    assert "Invalid webhook signature" in str(exc_info.value.detail)


def test_webhook_idempotency_protection(db_session, seeded_db):
    """
    Test: Webhook idempotency protection:
    Duplicate delivery of the exact same event_id must not double-process or duplicate mutations.
    """
    merchant = db_session.query(Merchant).first()
    payment = db_session.query(Payment).filter(Payment.merchant_id == merchant.id).first()

    secret = "test_webhook_secret_idemp"
    event_id = f"evt_test_idemp_{uuid.uuid4().hex[:8]}"

    payload_dict = {
        "event_id": event_id,
        "event": "payment.captured",
        "created_at": 1600000000,
        "payload": {
            "payment": {
                "entity": {
                    "id": str(payment.id),
                    "amount": int(payment.amount * 100),
                    "currency": "INR",
                    "status": "captured"
                }
            }
        }
    }
    body_bytes = json.dumps(payload_dict).encode("utf-8")
    sig = compute_test_signature(body_bytes, secret=secret)

    engine = RazorpayWebhookEngine(db_session)

    # First delivery: processed successfully
    res1 = engine.process_webhook(body_bytes, signature_header=sig, secret=secret)
    assert res1["status"] == "success"
    assert res1["idempotent"] is False
    assert res1["event_id"] == event_id

    # Verify WebhookEvent stored in DB
    stored_evt = db_session.query(WebhookEvent).filter(WebhookEvent.event_id == event_id).first()
    assert stored_evt is not None
    assert stored_evt.processed is True

    # Second delivery with identical event_id: MUST return idempotent duplicate response
    res2 = engine.process_webhook(body_bytes, signature_header=sig, secret=secret)
    assert res2["status"] == "idempotent_duplicate"
    assert res2["idempotent"] is True
    assert res2["event_id"] == event_id

    # Count webhook events with this ID (must remain exactly 1)
    cnt = db_session.query(WebhookEvent).filter(WebhookEvent.event_id == event_id).count()
    assert cnt == 1


def test_webhook_payment_failed_triggers_recovery_opportunity(db_session, seeded_db):
    """
    Test: payment.failed webhook updates payment to FAILED, records attempt,
    generates AuditEvent, and triggers an open RecoveryOpportunity.
    """
    merchant = db_session.query(Merchant).first()
    customer = db_session.query(Customer).filter(Customer.merchant_id == merchant.id).first()

    failed_payment = Payment(
        merchant_id=merchant.id,
        customer_id=customer.id,
        amount=Decimal("12500.00"),
        currency="INR",
        status=PaymentStatus.PENDING.value,
        payment_method="upi",
        bank="SBI",
        device_type="android",
        route="direct"
    )
    db_session.add(failed_payment)
    db_session.commit()

    secret = "test_webhook_sec_fail"
    event_id = f"evt_fail_{uuid.uuid4().hex[:8]}"

    payload_dict = {
        "event_id": event_id,
        "event": "payment.failed",
        "created_at": 1600000000,
        "payload": {
            "payment": {
                "entity": {
                    "id": str(failed_payment.id),
                    "amount": 1250000,
                    "currency": "INR",
                    "status": "failed",
                    "error_code": "BAD_REQUEST_PAYMENT_TIMED_OUT",
                    "error_description": "Payment authorization timed out"
                }
            }
        }
    }
    body_bytes = json.dumps(payload_dict).encode("utf-8")
    sig = compute_test_signature(body_bytes, secret=secret)

    engine = RazorpayWebhookEngine(db_session)
    res = engine.process_webhook(body_bytes, signature_header=sig, secret=secret)

    assert res["status"] == "success"
    assert res["recovery_triggered"] is True
    assert res["audit_event_id"] is not None

    # Verify payment state updated in DB
    db_session.refresh(failed_payment)
    assert failed_payment.status == PaymentStatus.FAILED.value

    # Verify PaymentAttempt created
    attempts = db_session.query(PaymentAttempt).filter(PaymentAttempt.payment_id == failed_payment.id).all()
    assert len(attempts) >= 1
    assert attempts[-1].error_code == "BAD_REQUEST_PAYMENT_TIMED_OUT"

    # Verify RecoveryOpportunity created and triggered
    opp = db_session.query(RecoveryOpportunity).filter(RecoveryOpportunity.payment_id == failed_payment.id).first()
    assert opp is not None
    assert opp.status == OpportunityStatus.OPEN.value
    assert opp.gross_value_affected == Decimal("12500.00")
    assert opp.priority == "HIGH"

    # Verify AuditEvent recorded
    audit = db_session.query(AuditEvent).filter(AuditEvent.request_id == event_id).first()
    assert audit is not None
    assert "webhook_payment_failed" in audit.event_type


def test_webhook_payment_link_paid_resolves_opportunity(db_session, seeded_db):
    """
    Test: payment_link.paid webhook marks an open RecoveryOpportunity as RECOVERED
    and updates actual_recovered_value.
    """
    merchant = db_session.query(Merchant).first()
    opp = db_session.query(RecoveryOpportunity).filter(
        RecoveryOpportunity.merchant_id == merchant.id,
        RecoveryOpportunity.status == OpportunityStatus.OPEN.value
    ).first()
    assert opp is not None

    secret = "test_webhook_sec_link"
    event_id = f"evt_plink_{uuid.uuid4().hex[:8]}"

    payload_dict = {
        "event_id": event_id,
        "event": "payment_link.paid",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": "plink_test_recovered_99",
                    "amount": int(opp.gross_value_affected * 100),
                    "status": "paid"
                }
            },
            "payment": {
                "entity": {
                    "id": "pay_test_link_success",
                    "amount": int(opp.gross_value_affected * 100),
                    "status": "captured"
                }
            }
        }
    }
    body_bytes = json.dumps(payload_dict).encode("utf-8")
    sig = compute_test_signature(body_bytes, secret=secret)

    engine = RazorpayWebhookEngine(db_session)
    res = engine.process_webhook(body_bytes, signature_header=sig, secret=secret)
    assert res["status"] == "success"

    # Verify opportunity is resolved
    db_session.refresh(opp)
    assert opp.status == OpportunityStatus.RECOVERED.value
    assert opp.actual_recovered_value == opp.gross_value_affected


def test_webhook_subscription_halted_triggers_mandate_recovery(db_session, seeded_db):
    """
    Test: subscription.halted updates subscription status to FAILED and creates a recovery opportunity.
    """
    sub = db_session.query(Subscription).first()
    assert sub is not None

    secret = "test_sub_halt_sec"
    event_id = f"evt_sub_halt_{uuid.uuid4().hex[:8]}"

    payload_dict = {
        "event_id": event_id,
        "event": "subscription.halted",
        "payload": {
            "subscription": {
                "entity": {
                    "id": str(sub.id),
                    "status": "halted"
                }
            }
        }
    }
    body_bytes = json.dumps(payload_dict).encode("utf-8")
    sig = compute_test_signature(body_bytes, secret=secret)

    engine = RazorpayWebhookEngine(db_session)
    res = engine.process_webhook(body_bytes, signature_header=sig, secret=secret)
    assert res["status"] == "success"
    assert res["recovery_triggered"] is True

    # Verify subscription status
    db_session.refresh(sub)
    assert sub.status == SubscriptionStatus.FAILED.value


def test_api_payment_provider_endpoints(client):
    """
    Test REST APIs:
    - GET /api/payment-provider/status
    - POST /api/payment-provider/mode
    - POST /api/payment-provider/payment-links
    """
    # 1. Inspect status
    resp_status = client.get("/api/payment-provider/status")
    assert resp_status.status_code == 200
    st_data = resp_status.json()
    assert "requested_mode" in st_data
    assert "effective_provider" in st_data
    assert "available_modes" in st_data
    # Ensure zero secrets leaked
    assert "secret" not in json.dumps(st_data).lower()

    # 2. Switch mode to MOCK
    resp_switch = client.post("/api/payment-provider/mode", json={"mode": "MOCK"})
    assert resp_switch.status_code == 200
    assert resp_switch.json()["requested_mode"] == "MOCK"

    # 3. Switch mode to invalid mode -> 400
    resp_bad = client.post("/api/payment-provider/mode", json={"mode": "INVALID_MODE"})
    assert resp_bad.status_code == 400

    # 4. Generate payment link through active provider
    link_payload = {
        "amount": 3499.00,
        "description": "Test recovery link API",
        "customer_name": "Anita Roy",
        "customer_phone": "+919123456780"
    }
    resp_link = client.post("/api/payment-provider/payment-links", json=link_payload)
    assert resp_link.status_code == 200
    link_res = resp_link.json()
    assert "id" in link_res
    assert "short_url" in link_res
    assert link_res["amount"] == 349900


def test_api_webhook_ingestion_endpoint(client, db_session, seeded_db):
    """
    Test: POST /api/webhooks/razorpay endpoint:
    - Valid signature -> 200 OK
    - Invalid signature -> 400 Bad Request
    """
    secret = settings.RAZORPAY_WEBHOOK_SECRET or "rzp_webhook_secret_placeholder"
    event_id = f"evt_api_test_{uuid.uuid4().hex[:8]}"
    payload = {
        "event_id": event_id,
        "event": "payment.authorized",
        "created_at": 1600000000,
        "payload": {
            "payment": {
                "entity": {
                    "id": f"pay_api_{uuid.uuid4().hex[:8]}",
                    "amount": 250000,
                    "currency": "INR",
                    "status": "authorized"
                }
            }
        }
    }
    body_bytes = json.dumps(payload).encode("utf-8")
    valid_sig = compute_test_signature(body_bytes, secret=secret)

    # 1. Post with valid signature
    resp = client.post(
        "/api/webhooks/razorpay",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": valid_sig}
    )
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["status"] == "success"
    assert res_data["event_id"] == event_id

    # 2. Post with invalid signature
    bad_resp = client.post(
        "/api/webhooks/razorpay",
        content=body_bytes,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": "invalid_signature"}
    )
    assert bad_resp.status_code == 400
