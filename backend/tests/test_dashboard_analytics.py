"""
Tests for the RevenueOS Merchant Operations Dashboard Analytics and AI Agent Chat APIs.
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_dashboard_html_served():
    """Verify that the dashboard HTML is served at / and /dashboard."""
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "RevenueOS" in res_root.text
    assert "Razorpay Enterprise" in res_root.text

    res_dash = client.get("/dashboard")
    assert res_dash.status_code == 200
    assert "Overview" in res_dash.text
    assert "chart-revenue-trend" in res_dash.text

def test_overview_analytics_endpoint():
    """Verify GET /api/v1/analytics/overview returns deterministic KPIs and chart datasets."""
    # Reset database and get merchant_id
    seed_res = client.post("/api/v1/demo/reset", json={"seed": 42})
    assert seed_res.status_code == 200
    scenarios = seed_res.json()["scenarios"]
    merchant_id = scenarios["payment_degradation"]["merchant_id"]

    res = client.get(f"/api/v1/analytics/overview?merchant_id={merchant_id}")
    assert res.status_code == 200
    data = res.json()

    # Verify 5 mandatory summary KPIs
    assert "revenue_processed" in data
    assert "revenue_at_risk" in data
    assert "potentially_recoverable" in data
    assert "recovered_revenue" in data
    assert "recovery_rate" in data

    assert float(data["revenue_processed"]) >= 0
    assert float(data["revenue_at_risk"]) >= 0
    assert 0.0 <= float(data["recovery_rate"]) <= 100.0

    # Verify 4 charts datasets
    assert "revenue_trend" in data
    assert isinstance(data["revenue_trend"], list)
    assert len(data["revenue_trend"]) > 0
    assert "date" in data["revenue_trend"][0]
    assert "processed" in data["revenue_trend"][0]
    assert "failed" in data["revenue_trend"][0]

    assert "success_rate_trend" in data
    assert isinstance(data["success_rate_trend"], list)
    assert len(data["success_rate_trend"]) > 0
    assert "success_rate" in data["success_rate_trend"][0]

    assert "leakage_breakdown" in data
    assert isinstance(data["leakage_breakdown"], list)

    assert "recovery_performance" in data
    assert isinstance(data["recovery_performance"], list)

def test_roi_analytics_endpoint():
    """Verify GET /api/v1/analytics/roi returns Before vs After comparison and automation metrics."""
    seed_res = client.post("/api/v1/demo/reset", json={"seed": 42})
    assert seed_res.status_code == 200
    scenarios = seed_res.json()["scenarios"]
    merchant_id = scenarios["payment_degradation"]["merchant_id"]

    res = client.get(f"/api/v1/analytics/roi?merchant_id={merchant_id}")
    assert res.status_code == 200
    data = res.json()

    assert "before" in data
    assert "after" in data
    assert "net_financial_gain" in data
    assert "hours_saved" in data
    assert "roi_multiplier" in data

    before = data["before"]
    after = data["after"]

    assert "revenue_lost" in before
    assert "revenue_recovered" in after
    assert after["recovery_rate"] >= before["recovery_rate"]
    assert float(data["net_financial_gain"]) >= 0

def test_ai_agent_chat_endpoint():
    """Verify POST /api/v1/agent/chat provides grounded natural language answers and evidence cards."""
    seed_res = client.post("/api/v1/demo/reset", json={"seed": 42})
    assert seed_res.status_code == 200
    scenarios = seed_res.json()["scenarios"]
    merchant_id = scenarios["payment_degradation"]["merchant_id"]

    # Ask the canonical question: "Why did revenue drop yesterday?"
    chat_payload = {
        "message": "Why did revenue drop yesterday?",
        "merchant_id": merchant_id
    }
    res = client.post("/api/v1/agent/chat", json=chat_payload)
    assert res.status_code == 200
    data = res.json()

    assert "response_text" in data
    assert "evidence_cards" in data
    assert "decision_explanation" in data
    assert len(data["evidence_cards"]) > 0

    # Ensure evidence cards have required structure
    for card in data["evidence_cards"]:
        assert "title" in card
        assert "metric" in card
        assert "badge" in card
        assert "badge_type" in card

    # Test another question: "What are our top recovery opportunities?"
    chat_payload_opp = {
        "message": "What are our top recovery opportunities?",
        "merchant_id": merchant_id
    }
    res_opp = client.post("/api/v1/agent/chat", json=chat_payload_opp)
    assert res_opp.status_code == 200
    data_opp = res_opp.json()
    assert "opportunities" in data_opp["response_text"].lower() or "recovery" in data_opp["response_text"].lower()
