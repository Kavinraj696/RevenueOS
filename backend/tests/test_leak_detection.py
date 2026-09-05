import uuid
from decimal import Decimal
import pytest

from app.models import (
    Merchant,
    Payment,
    PaymentAttempt,
    RevenueLeak,
    PaymentStatus,
    BankCode,
    PaymentMethod,
    DeviceType,
)
from app.services.leak_detection import RevenueLeakDetector
from app.synthetic.generator import SyntheticDataGenerator
from app.synthetic.scenarios import SCENARIO_CONFIGS

def test_detect_payment_degradation_anomaly(db_session):
    """
    Test Vector 1-5 + Multi-dimensional degradation:
    Verifies that the detector catches the injected HDFC + UPI + Android + Evening cluster
    with real calculated numbers matching user specification.
    """
    gen = SyntheticDataGenerator(seed=42)
    scenario_cfg = next(c for c in SCENARIO_CONFIGS if c["id"] == "payment_degradation")
    gen.generate_scenario(db_session, scenario_cfg)

    merchant = db_session.query(Merchant).filter(Merchant.email == scenario_cfg["email"]).one()

    detector = RevenueLeakDetector(db_session)
    leaks = detector.run_detection_for_merchant(merchant.id)

    assert len(leaks) > 0

    # Locate the multidimensional anomaly leak
    anomaly_leak = next((l for l in leaks if l.leak_type == "anomaly"), None)
    assert anomaly_leak is not None, "Anomaly leak must be detected for Scenario 2"

    assert anomaly_leak.severity in ("critical", "high")
    assert anomaly_leak.affected_transactions >= 5
    assert anomaly_leak.affected_amount > Decimal("0.00")
    assert anomaly_leak.revenue_at_risk > Decimal("0.00")
    assert anomaly_leak.confidence >= Decimal("0.7500")
    assert len(anomaly_leak.root_cause_candidates) > 0

    # Verify structured evidence matches required format
    ev = anomaly_leak.evidence
    assert "baseline_failure_rate" in ev
    assert "current_failure_rate" in ev
    assert "increase_percentage" in ev
    assert ev["affected_payment_method"] == "UPI"
    assert ev["affected_bank"] == "HDFC"
    assert ev["affected_device"] == "Android"
    assert ev["peak_window"] == "18:00–22:00"
    assert "potential_revenue" in ev

    # Real calculated values verification
    assert float(ev["current_failure_rate"]) >= 60.0
    assert float(ev["increase_percentage"]) > 100.0

def test_detect_checkout_abandonment(db_session):
    """Test Vector 6: Checkout abandonment detection."""
    gen = SyntheticDataGenerator(seed=42)
    scenario_cfg = next(c for c in SCENARIO_CONFIGS if c["id"] == "checkout_abandonment")
    gen.generate_scenario(db_session, scenario_cfg)

    merchant = db_session.query(Merchant).filter(Merchant.email == scenario_cfg["email"]).one()

    detector = RevenueLeakDetector(db_session)
    leaks = detector.run_detection_for_merchant(merchant.id)

    checkout_leak = next((l for l in leaks if l.leak_type == "checkout_abandonment"), None)
    assert checkout_leak is not None

    assert checkout_leak.affected_transactions > 0
    assert checkout_leak.revenue_at_risk > Decimal("0.00")
    assert "primary_stage_dropped" in checkout_leak.evidence
    assert checkout_leak.evidence["primary_stage_dropped"] in ("otp_entry", "payment_method_select")

def test_detect_subscription_failure_spike(db_session):
    """Test Vector 7: Subscription recurring mandate failure spike."""
    gen = SyntheticDataGenerator(seed=42)
    scenario_cfg = next(c for c in SCENARIO_CONFIGS if c["id"] == "subscription_spike")
    gen.generate_scenario(db_session, scenario_cfg)

    merchant = db_session.query(Merchant).filter(Merchant.email == scenario_cfg["email"]).one()

    detector = RevenueLeakDetector(db_session)
    leaks = detector.run_detection_for_merchant(merchant.id)

    sub_leak = next((l for l in leaks if l.leak_type == "subscription_failure"), None)
    assert sub_leak is not None

    assert sub_leak.affected_transactions > 0
    assert sub_leak.revenue_at_risk > Decimal("0.00")
    assert "error_code_breakdown" in sub_leak.evidence
    assert float(sub_leak.evidence["current_failure_rate"]) >= 30.0

def test_detect_high_value_failures(db_session):
    """Test Vector 8: High-value failed transactions detection."""
    gen = SyntheticDataGenerator(seed=42)
    scenario_cfg = next(c for c in SCENARIO_CONFIGS if c["id"] == "high_value_recoverable")
    gen.generate_scenario(db_session, scenario_cfg)

    merchant = db_session.query(Merchant).filter(Merchant.email == scenario_cfg["email"]).one()

    detector = RevenueLeakDetector(db_session)
    leaks = detector.run_detection_for_merchant(merchant.id)

    hv_leak = next((l for l in leaks if "High-Value" in l.pattern_description), None)
    assert hv_leak is not None

    assert hv_leak.affected_transactions >= 2
    assert hv_leak.affected_amount >= Decimal("50000.00")
    assert hv_leak.evidence["average_transaction_value"] >= Decimal("25000.00")

def test_detect_repeated_customer_failures(db_session):
    """Test Vector 9: Repeated customer drop-off failures."""
    merchant = Merchant(name="Repeat Test Merchant", email="repeat@test.com")
    db_session.add(merchant)
    db_session.flush()

    # Create 3 customers with 2 failed payments each
    from app.models import Customer
    for i in range(3):
        cust = Customer(merchant_id=merchant.id, external_ref=f"cust_rep_{i}", lifetime_value=Decimal("5000.00"))
        db_session.add(cust)
        db_session.flush()

        for j in range(2):
            p = Payment(
                merchant_id=merchant.id,
                customer_id=cust.id,
                amount=Decimal("1500.00"),
                currency="INR",
                status=PaymentStatus.FAILED.value,
                payment_method="upi",
                device_type="android",
                route="direct"
            )
            db_session.add(p)
    db_session.commit()

    detector = RevenueLeakDetector(db_session)
    leaks = detector.run_detection_for_merchant(merchant.id)

    rep_leak = next((l for l in leaks if "Repeated Customer" in l.pattern_description), None)
    assert rep_leak is not None
    assert rep_leak.affected_transactions == 6
    assert rep_leak.evidence["affected_customers_count"] == 3

def test_api_revenue_leaks_endpoints(client, seeded_db):
    """Test GET /api/revenue-leaks and GET /api/revenue-leaks/{id} endpoints."""
    # 1. GET /api/revenue-leaks
    response = client.get("/api/revenue-leaks")
    assert response.status_code == 200
    leaks = response.json()
    assert len(leaks) > 0

    first_leak = leaks[0]
    assert "id" in first_leak
    assert "type" in first_leak
    assert "severity" in first_leak
    assert "affected_transactions" in first_leak
    assert "affected_amount" in first_leak
    assert "revenue_at_risk" in first_leak
    assert "confidence" in first_leak
    assert "root_cause_candidates" in first_leak
    assert "evidence" in first_leak
    assert "status" in first_leak
    assert "created_at" in first_leak

    leak_id = first_leak["id"]

    # 2. GET /api/revenue-leaks/{id}
    detail_res = client.get(f"/api/revenue-leaks/{leak_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["id"] == leak_id
    assert detail["evidence"] is not None

    # 3. Test filtering by leak_type
    filter_res = client.get(f"/api/revenue-leaks?leak_type={first_leak['type']}")
    assert filter_res.status_code == 200
    filtered_list = filter_res.json()
    for item in filtered_list:
        assert item["type"] == first_leak["type"]

    # 4. Test 404 for nonexistent leak
    non_existent_id = str(uuid.uuid4())
    not_found_res = client.get(f"/api/revenue-leaks/{non_existent_id}")
    assert not_found_res.status_code == 404
