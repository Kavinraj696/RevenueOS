import uuid
from decimal import Decimal
import pytest
from app.models.merchant import Merchant
from app.models.customer import Customer
from app.models.payment import Payment
from app.models.payment_attempt import PaymentAttempt
from app.models.subscription import Subscription
from app.models.enums import PaymentStatus, OpportunityStatus
from app.services.agent.tools import AgentTools
from app.synthetic.generator import SyntheticDataGenerator


@pytest.fixture
def agent_tools(db_session, seeded_db):
    """Fixture providing AgentTools initialized with a populated DB."""
    return AgentTools(db_session)


def test_tool_1_and_2_revenue_leaks(agent_tools, db_session):
    # Tool 1: get_revenue_leaks
    leaks = agent_tools.get_revenue_leaks(limit=5)
    assert isinstance(leaks, list)
    assert len(leaks) > 0
    first_leak = leaks[0]
    assert "id" in first_leak
    assert "gross_value_affected" in first_leak
    assert "revenue_at_risk" in first_leak

    # Tool 2: get_revenue_leak
    leak_detail = agent_tools.get_revenue_leak(first_leak["id"])
    assert leak_detail["id"] == first_leak["id"]
    assert "severity_score" in leak_detail
    assert "root_cause_candidates" in leak_detail

    # Non-existent leak
    not_found = agent_tools.get_revenue_leak(uuid.uuid4())
    assert "error" in not_found


def test_tool_3_and_4_transactions(agent_tools, db_session):
    # Tool 3: search_transactions
    failed_txs = agent_tools.search_transactions(status="failed", limit=5)
    assert isinstance(failed_txs, list)
    assert len(failed_txs) > 0
    sample_tx = failed_txs[0]
    assert sample_tx["status"] == "failed"
    assert "attempt_count" in sample_tx

    # Tool 4: get_transaction
    tx_detail = agent_tools.get_transaction(sample_tx["id"])
    assert tx_detail["id"] == sample_tx["id"]
    assert "attempts" in tx_detail
    assert "amount" in tx_detail


def test_tool_5_customer_history(agent_tools, db_session):
    # Tool 5: get_customer_history
    customer = db_session.query(Customer).first()
    assert customer is not None

    cust_history = agent_tools.get_customer_history(customer.id)
    assert cust_history["customer_id"] == str(customer.id)
    assert "lifetime_value" in cust_history
    assert "total_transactions" in cust_history
    assert "is_vip" in cust_history


def test_tool_6_failure_analysis(agent_tools, db_session):
    # Tool 6: get_failure_analysis
    merchant = db_session.query(Merchant).first()
    assert merchant is not None

    analysis = agent_tools.get_failure_analysis(merchant_id=merchant.id)
    assert "overall_failure_rate" in analysis
    assert "baseline_failure_rate" in analysis
    assert "by_payment_method" in analysis
    assert "by_bank" in analysis
    assert "peak_window" in analysis


def test_tool_7_recovery_opportunities(agent_tools, db_session):
    # Tool 7: get_recovery_opportunities
    opps = agent_tools.get_recovery_opportunities(limit=5)
    assert isinstance(opps, list)
    assert len(opps) > 0
    first_opp = opps[0]
    assert "transaction_amount" in first_opp
    assert "recovery_probability" in first_opp
    assert "expected_recoverable_amount" in first_opp
    assert "priority" in first_opp
    assert "priority_score" in first_opp


def test_tool_8_calculate_recovery_probability(agent_tools, db_session):
    # Tool 8: calculate_recovery_probability
    payment = db_session.query(Payment).filter(Payment.status == PaymentStatus.FAILED.value).first()
    assert payment is not None

    res = agent_tools.calculate_recovery_probability(payment.id)
    assert "recovery_probability" in res
    assert 0.0 <= res["recovery_probability"] <= 1.0
    assert "confidence" in res
    assert res["model_name"] == "payment_recovery_probability"


def test_tool_9_estimate_recoverable_revenue(agent_tools):
    # Tool 9: estimate_recoverable_revenue
    # ₹4,999 with 82% recovery probability = ₹4,099.18
    res = agent_tools.estimate_recoverable_revenue(4999.0, 0.82)
    assert res["transaction_value"] == 4999.0
    assert res["recovery_probability"] == 0.82
    assert res["expected_recoverable_amount"] == 4099.18
    assert res["potentially_recoverable_amount"] > 0
    assert res["conservative_estimate"] <= res["expected_recoverable_amount"]


def test_tool_10_available_payment_methods(agent_tools):
    # Tool 10: get_available_payment_methods
    methods = agent_tools.get_available_payment_methods()
    assert "methods" in methods
    assert len(methods["methods"]) > 0
    assert "recommended_recovery_action" in methods


def test_tool_11_and_14_payment_link_and_recovery_result(agent_tools, db_session):
    payment = db_session.query(Payment).filter(Payment.status == PaymentStatus.FAILED.value).first()
    assert payment is not None

    # Tool 11: create_test_payment_link
    link_res = agent_tools.create_test_payment_link(payment.id, amount=4999.0)
    assert link_res["status"] == "created"
    assert "short_url" in link_res
    assert "link_id" in link_res

    # Tool 14: get_recovery_result
    action_id = link_res.get("action_id")
    if action_id:
        act_res = agent_tools.get_recovery_result(action_id)
        assert act_res["status"] == "executed"
        assert "execution_result" in act_res


def test_tool_12_subscription_link(agent_tools, db_session):
    sub = db_session.query(Subscription).first()
    assert sub is not None

    # Tool 12: create_test_subscription_link
    sub_res = agent_tools.create_test_subscription_link(sub.id)
    assert sub_res["status"] == "created"
    assert "short_url" in sub_res
    assert "sublink_" in sub_res["link_id"]


def test_tool_13_send_recovery_notification(agent_tools, db_session):
    customer = db_session.query(Customer).first()
    assert customer is not None

    # Tool 13: send_recovery_notification
    notif_res = agent_tools.send_recovery_notification(customer.id, channel="sms_whatsapp")
    assert notif_res["status"] == "delivered"
    assert "notification_id" in notif_res
    assert notif_res["customer_id"] == str(customer.id)


def test_tool_15_get_policy(agent_tools):
    # Tool 15: get_policy
    max_policy = agent_tools.get_policy("max_auto_amount")
    assert max_policy["threshold"] == 15000.00

    retry_policy = agent_tools.get_policy("retry_limits")
    assert retry_policy["max_attempts"] == 3

    all_policies = agent_tools.get_policy("all")
    assert "active_rules" in all_policies


def test_tool_16_write_audit_event(agent_tools, db_session):
    merchant = db_session.query(Merchant).first()
    assert merchant is not None

    # Tool 16: write_audit_event
    dummy_entity_id = uuid.uuid4()
    audit = agent_tools.write_audit_event(
        merchant_id=merchant.id,
        related_entity_type="payment",
        related_entity_id=dummy_entity_id,
        event_type="test_agent_event",
        message="Agent test audit event logged"
    )
    assert "audit_id" in audit
    assert audit["event_type"] == "test_agent_event"
    assert audit["merchant_id"] == str(merchant.id)
