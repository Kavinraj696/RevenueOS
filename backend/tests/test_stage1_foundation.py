import os
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app
from app.api.deps import get_db
from app.config import settings
from app.services.payment_provider.razorpay_provider import RazorpayTestProvider


def test_health_check_healthy_with_database(client):
    """Verify /health returns 200 with database: connected when healthy."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "RevenueOS"
    assert data["database"] == "connected"


def test_health_check_returns_503_on_database_failure(client):
    """Verify /health accurately reflects database connectivity failure with 503."""
    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise OperationalError("Connection refused to database", {}, None)

    def broken_get_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_get_db
    try:
        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["database"] == "disconnected"
        assert "error" in data
    finally:
        app.dependency_overrides.clear()


def test_configuration_and_environment_safety():
    """Verify that configuration loads safely, secrets are not exposed, and .env is protected."""
    # 1. Verify settings object
    assert settings.PROJECT_NAME == "RevenueOS"
    assert settings.API_V1_STR == "/api/v1"
    assert settings.DATABASE_URL is not None

    # 2. Verify git ignore for .env and database files
    gitignore_path = os.path.join(os.path.dirname(__file__), "..", "..", ".gitignore")
    if os.path.exists(gitignore_path):
        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert ".env" in content
            assert "*.db" in content

    # 3. Verify .env.example contains only placeholders and no real secrets
    example_path = os.path.join(os.path.dirname(__file__), "..", ".env.example")
    if os.path.exists(example_path):
        with open(example_path, "r", encoding="utf-8") as f:
            example_content = f.read()
            assert "your_key_secret_here" in example_content or "placeholder" in example_content
            # Confirm no live keys
            assert "rzp_live_" not in example_content


def test_live_mode_credentials_prohibited():
    """Verify that RazorpayTestProvider strictly rejects live credentials."""
    with pytest.raises(ValueError, match="Live mode credentials"):
        RazorpayTestProvider(
            key_id="rzp_live_abc123456789",
            key_secret="live_secret_sample"
        )


def test_api_validation_and_error_handling(client, seeded_db):
    """
    Verify error handling behavior:
    - 404 for nonexistent routes
    - 404 for nonexistent resources
    - 422 for missing required fields
    - 400 for missing/invalid webhook signatures
    - No raw python stack traces exposed
    """
    # 1. Nonexistent route -> 404
    res_404 = client.get("/api/v1/this-route-does-not-exist")
    assert res_404.status_code == 404
    assert "detail" in res_404.json()

    # 2. Nonexistent merchant ID -> 404
    fake_merchant_id = str(uuid.uuid4())
    res_no_merchant = client.get(f"/api/v1/merchants/{fake_merchant_id}")
    assert res_no_merchant.status_code == 404
    assert "detail" in res_no_merchant.json()

    # 3. Nonexistent leak ID -> 404
    fake_leak_id = str(uuid.uuid4())
    res_no_leak = client.get(f"/api/v1/revenue-leaks/{fake_leak_id}")
    assert res_no_leak.status_code == 404

    # 4. Nonexistent recovery opportunity -> 404
    fake_opp_id = str(uuid.uuid4())
    res_no_opp = client.get(f"/api/v1/recovery-opportunities/{fake_opp_id}")
    assert res_no_opp.status_code == 404

    # 5. Missing required body in POST /api/v1/policy/evaluate -> 422 Unprocessable Entity
    res_422 = client.post("/api/v1/policy/evaluate", json={})
    assert res_422.status_code == 422
    err_json = res_422.json()
    assert "detail" in err_json
    # Ensure no internal file paths or stack traces leaked
    assert "Traceback" not in res_422.text

    # 6. Webhook missing X-Razorpay-Signature -> 400 Bad Request
    res_no_sig = client.post("/api/v1/webhooks/razorpay", content=b'{"event":"payment.captured"}')
    assert res_no_sig.status_code == 400
    assert "detail" in res_no_sig.json()
    assert "Missing X-Razorpay-Signature" in res_no_sig.json()["detail"]

    # 7. Webhook with invalid signature -> 400 Bad Request
    res_bad_sig = client.post(
        "/api/v1/webhooks/razorpay",
        content=b'{"event":"payment.captured"}',
        headers={"X-Razorpay-Signature": "invalid_hex_digest"}
    )
    assert res_bad_sig.status_code == 400
    assert "Invalid webhook signature" in res_bad_sig.json()["detail"]


def test_error_response_format_sanitized(client):
    """Verify that error responses do not leak stack traces or system internals."""
    response = client.post(
        "/api/v1/policy/evaluate",
        json={"action": "INVALID_ACTION", "transaction_amount": -500}
    )
    assert response.status_code in (200, 422)  # Either validation error or policy block
    # Check that response does not leak internal traceback or server file paths
    text_content = response.text
    assert "Traceback (most recent call last)" not in text_content
    assert "File \"" not in text_content
    assert "k:\\Documents" not in text_content.lower()
