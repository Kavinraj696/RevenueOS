import pytest
from decimal import Decimal

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "RevenueOS"

def test_list_merchants(client, seeded_db):
    response = client.get("/api/v1/merchants")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 5
    merchant_names = {m["name"] for m in data}
    assert "Apex Electronics" in merchant_names
    assert "TrendStyle Apparel" in merchant_names

def test_merchant_summary(client, seeded_db):
    # Get first merchant
    merchants = client.get("/api/v1/merchants").json()
    merchant = merchants[0]
    m_id = merchant["id"]

    response = client.get(f"/api/v1/merchants/{m_id}/summary")
    assert response.status_code == 200
    summary = response.json()

    assert summary["merchant_id"] == m_id
    assert "total_processed_volume" in summary
    assert "gross_revenue_at_risk" in summary
    assert "success_rate_percentage" in summary
    assert summary["total_transactions_count"] > 0
    assert summary["currency"] == "INR"

def test_transactions_endpoint_and_filtering(client, seeded_db):
    merchants = client.get("/api/v1/merchants").json()
    m_id = merchants[0]["id"]

    # Basic pagination
    res = client.get(f"/api/v1/merchants/{m_id}/transactions?limit=10&offset=0")
    assert res.status_code == 200
    data = res.json()
    assert data["limit"] == 10
    assert data["offset"] == 0
    assert len(data["items"]) <= 10
    assert data["total"] > 0

    # Filter by payment method
    res_upi = client.get(f"/api/v1/merchants/{m_id}/transactions?payment_method=upi")
    assert res_upi.status_code == 200
    upi_data = res_upi.json()
    for item in upi_data["items"]:
        assert item["payment_method"] == "upi"

def test_failures_endpoint(client, seeded_db):
    merchants = client.get("/api/v1/merchants").json()
    # Find merchant with failures (e.g. TrendStyle or Titan)
    degradation_merchant = next(m for m in merchants if m["name"] == "TrendStyle Apparel")
    m_id = degradation_merchant["id"]

    res = client.get(f"/api/v1/merchants/{m_id}/failures")
    assert res.status_code == 200
    failures = res.json()
    assert len(failures) > 0

    failure = failures[0]
    assert "payment_id" in failure
    assert "amount" in failure
    assert "last_error_code" in failure
    assert failure["attempt_count"] >= 1

def test_subscriptions_endpoint(client, seeded_db):
    merchants = client.get("/api/v1/merchants").json()
    saas_merchant = next(m for m in merchants if m["name"] == "CloudFlow SaaS")
    m_id = saas_merchant["id"]

    res = client.get(f"/api/v1/merchants/{m_id}/subscriptions")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] > 0
    for sub in data["items"]:
        assert "plan_name" in sub
        assert "plan_amount" in sub
        assert "status" in sub

def test_checkout_sessions_endpoint(client, seeded_db):
    merchants = client.get("/api/v1/merchants").json()
    luxe_merchant = next(m for m in merchants if m["name"] == "LuxeLiving Home")
    m_id = luxe_merchant["id"]

    res = client.get(f"/api/v1/merchants/{m_id}/checkout-sessions")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] > 0
    for cs in data["items"]:
        assert "cart_value" in cs
        assert "status" in cs

def test_demo_scenarios_and_reset(client):
    # List scenarios
    res = client.get("/api/v1/demo/scenarios")
    assert res.status_code == 200
    scenarios = res.json()
    assert len(scenarios) == 5

    # Reset with custom seed
    reset_res = client.post("/api/v1/demo/reset", json={"seed": 999})
    assert reset_res.status_code == 200
    reset_data = reset_res.json()
    assert reset_data["status"] == "success"
    assert "scenarios" in reset_data
