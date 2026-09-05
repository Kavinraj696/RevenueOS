"""
RevenueOS ML Feature Contract
Defines formal specifications, types, sources, availability boundaries,
and missing-value strategies for all recovery intelligence features.
"""

from dataclasses import dataclass
from typing import Dict, List, Any


@dataclass(frozen=True)
class FeatureDefinition:
    name: str
    data_type: str  # "float", "int", "str", "bool"
    source: str  # Entity/Table source
    calculation: str  # Mathematical or procedural definition
    availability_time: str  # Point-in-time boundary: "<= prediction_time"
    missing_value_behavior: str  # Strategy for NULL or cold-start


FEATURE_CONTRACT: Dict[str, FeatureDefinition] = {
    # -------------------------------------------------------------------------
    # 1. Transaction Features
    # -------------------------------------------------------------------------
    "transaction_amount": FeatureDefinition(
        name="transaction_amount",
        data_type="float",
        source="payments.amount",
        calculation="Nominal rupee amount of failed transaction.",
        availability_time="<= prediction_time",
        missing_value_behavior="0.0",
    ),
    "log_amount": FeatureDefinition(
        name="log_amount",
        data_type="float",
        source="payments.amount",
        calculation="ln(1 + transaction_amount).",
        availability_time="<= prediction_time",
        missing_value_behavior="0.0",
    ),
    "amount_percentile_for_merchant": FeatureDefinition(
        name="amount_percentile_for_merchant",
        data_type="float",
        source="payments (merchant history)",
        calculation="Ratio of transaction_amount to merchant historical average transaction value at T_pred.",
        availability_time="<= prediction_time",
        missing_value_behavior="1.0",
    ),
    "payment_method": FeatureDefinition(
        name="payment_method",
        data_type="str",
        source="payments.payment_method",
        calculation="Normalized payment method rail (upi, card, netbanking, wallet, other).",
        availability_time="<= prediction_time",
        missing_value_behavior="'unknown'",
    ),
    "transaction_hour": FeatureDefinition(
        name="transaction_hour",
        data_type="int",
        source="payments.created_at",
        calculation="Hour of day in UTC (0-23) when transaction was initiated.",
        availability_time="<= prediction_time",
        missing_value_behavior="12",
    ),
    "transaction_day_of_week": FeatureDefinition(
        name="transaction_day_of_week",
        data_type="int",
        source="payments.created_at",
        calculation="Day of week (0=Monday, 6=Sunday) in UTC.",
        availability_time="<= prediction_time",
        missing_value_behavior="0",
    ),
    "days_since_transaction": FeatureDefinition(
        name="days_since_transaction",
        data_type="float",
        source="payments.created_at",
        calculation="(prediction_time - payment.created_at).total_seconds() / 86400.0.",
        availability_time="<= prediction_time",
        missing_value_behavior="0.0",
    ),
    "attempt_number": FeatureDefinition(
        name="attempt_number",
        data_type="int",
        source="payment_attempts",
        calculation="Number of payment attempts recorded at or before prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="1",
    ),
    "time_since_previous_attempt": FeatureDefinition(
        name="time_since_previous_attempt",
        data_type="float",
        source="payment_attempts.attempted_at",
        calculation="Seconds between latest and previous attempt before prediction_time (0 if single attempt).",
        availability_time="<= prediction_time",
        missing_value_behavior="0.0",
    ),

    # -------------------------------------------------------------------------
    # 2. Customer Features
    # -------------------------------------------------------------------------
    "customer_transaction_count_before_prediction": FeatureDefinition(
        name="customer_transaction_count_before_prediction",
        data_type="int",
        source="payments (customer history)",
        calculation="Total payment attempts by customer strictly before prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="0 with is_cold_start=1",
    ),
    "customer_success_count": FeatureDefinition(
        name="customer_success_count",
        data_type="int",
        source="payments (customer history)",
        calculation="Total successful payments by customer strictly before prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="0",
    ),
    "customer_failure_count": FeatureDefinition(
        name="customer_failure_count",
        data_type="int",
        source="payments (customer history)",
        calculation="Total failed payments by customer strictly before prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="0",
    ),
    "customer_historical_success_rate": FeatureDefinition(
        name="customer_historical_success_rate",
        data_type="float",
        source="payments (customer history)",
        calculation="customer_success_count / customer_transaction_count (0.0 if cold start).",
        availability_time="<= prediction_time",
        missing_value_behavior="0.5 (neutral fallback with is_cold_start=1)",
    ),
    "customer_historical_failure_rate": FeatureDefinition(
        name="customer_historical_failure_rate",
        data_type="float",
        source="payments (customer history)",
        calculation="customer_failure_count / customer_transaction_count (0.0 if cold start).",
        availability_time="<= prediction_time",
        missing_value_behavior="0.5 (neutral fallback with is_cold_start=1)",
    ),
    "customer_lifetime_value_before_prediction": FeatureDefinition(
        name="customer_lifetime_value_before_prediction",
        data_type="float",
        source="payments.amount (customer history)",
        calculation="Sum of settled payments for customer strictly before prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="0.0",
    ),
    "days_since_last_success": FeatureDefinition(
        name="days_since_last_success",
        data_type="float",
        source="payments.created_at (customer history)",
        calculation="Days elapsed since customer's most recent success before prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="-1.0 (indicating no prior success)",
    ),
    "days_since_last_transaction": FeatureDefinition(
        name="days_since_last_transaction",
        data_type="float",
        source="payments.created_at (customer history)",
        calculation="Days elapsed since customer's most recent transaction attempt before prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="-1.0 (indicating no prior transaction)",
    ),
    "is_cold_start": FeatureDefinition(
        name="is_cold_start",
        data_type="int",
        source="customers",
        calculation="1 if customer has zero prior transactions before prediction_time, else 0.",
        availability_time="<= prediction_time",
        missing_value_behavior="1",
    ),

    # -------------------------------------------------------------------------
    # 3. Payment & Gateway Features
    # -------------------------------------------------------------------------
    "failure_reason": FeatureDefinition(
        name="failure_reason",
        data_type="str",
        source="payment_attempts.error_code / failure_reason",
        calculation="Categorized failure code (TIMEOUT, INSUFFICIENT_FUNDS, LIMIT_EXCEEDED, AUTH_FAILURE, OTHER, UNKNOWN).",
        availability_time="<= prediction_time",
        missing_value_behavior="'UNKNOWN'",
    ),
    "bank": FeatureDefinition(
        name="bank",
        data_type="str",
        source="payments.bank",
        calculation="Issuing / acquiring bank identifier (HDFC, ICICI, SBI, AXIS, KOTAK, OTHER).",
        availability_time="<= prediction_time",
        missing_value_behavior="'UNKNOWN'",
    ),
    "device_type": FeatureDefinition(
        name="device_type",
        data_type="str",
        source="payments.device_type",
        calculation="Client device environment (android, ios, desktop, mobile_web, unknown).",
        availability_time="<= prediction_time",
        missing_value_behavior="'unknown'",
    ),
    "previous_payment_method_success_rate": FeatureDefinition(
        name="previous_payment_method_success_rate",
        data_type="float",
        source="payments (customer + method)",
        calculation="Historical success rate for this customer on this specific payment method before prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="0.5 (neutral prior)",
    ),
    "previous_attempt_count": FeatureDefinition(
        name="previous_attempt_count",
        data_type="int",
        source="payment_attempts",
        calculation="Count of failed attempts on this transaction before prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="1",
    ),
    "time_since_failure": FeatureDefinition(
        name="time_since_failure",
        data_type="float",
        source="payment_attempts.attempted_at",
        calculation="Seconds elapsed between latest failure attempt and prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="0.0",
    ),

    # -------------------------------------------------------------------------
    # 4. Subscription Features
    # -------------------------------------------------------------------------
    "is_subscription": FeatureDefinition(
        name="is_subscription",
        data_type="int",
        source="subscriptions",
        calculation="1 if payment is linked to a recurring subscription, else 0.",
        availability_time="<= prediction_time",
        missing_value_behavior="0",
    ),
    "subscription_age_days": FeatureDefinition(
        name="subscription_age_days",
        data_type="float",
        source="subscriptions.created_at",
        calculation="Days elapsed since subscription created_at up to prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="0.0",
    ),
    "renewal_number": FeatureDefinition(
        name="renewal_number",
        data_type="int",
        source="subscription_attempts",
        calculation="Ordinal cycle number of subscription renewal.",
        availability_time="<= prediction_time",
        missing_value_behavior="0",
    ),
    "previous_renewal_count": FeatureDefinition(
        name="previous_renewal_count",
        data_type="int",
        source="subscription_attempts",
        calculation="Count of previous subscription auto-debit attempts before prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="0",
    ),
    "previous_renewal_success_rate": FeatureDefinition(
        name="previous_renewal_success_rate",
        data_type="float",
        source="subscription_attempts",
        calculation="Success rate of prior renewals before prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="0.5",
    ),
    "plan_value": FeatureDefinition(
        name="plan_value",
        data_type="float",
        source="subscriptions.plan_amount",
        calculation="Nominal recurring plan amount in INR.",
        availability_time="<= prediction_time",
        missing_value_behavior="0.0",
    ),
    "subscription_status": FeatureDefinition(
        name="subscription_status",
        data_type="str",
        source="subscriptions.status",
        calculation="Status of subscription at prediction_time (active, paused, past_due, none).",
        availability_time="<= prediction_time",
        missing_value_behavior="'none'",
    ),

    # -------------------------------------------------------------------------
    # 5. Merchant Baseline Features
    # -------------------------------------------------------------------------
    "merchant_payment_success_rate": FeatureDefinition(
        name="merchant_payment_success_rate",
        data_type="float",
        source="payments (merchant history)",
        calculation="Merchant's overall payment success rate before prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="0.80",
    ),
    "merchant_failure_rate": FeatureDefinition(
        name="merchant_failure_rate",
        data_type="float",
        source="payments (merchant history)",
        calculation="Merchant's overall payment failure rate before prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="0.20",
    ),
    "merchant_average_transaction_value": FeatureDefinition(
        name="merchant_average_transaction_value",
        data_type="float",
        source="payments (merchant history)",
        calculation="Merchant's historical average transaction value in INR before prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="2500.0",
    ),
    "merchant_payment_method_success_rate": FeatureDefinition(
        name="merchant_payment_method_success_rate",
        data_type="float",
        source="payments (merchant history)",
        calculation="Merchant's historical success rate for this payment method before prediction_time.",
        availability_time="<= prediction_time",
        missing_value_behavior="0.80",
    ),
}

FEATURE_NAMES: List[str] = list(FEATURE_CONTRACT.keys())
