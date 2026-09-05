from typing import Dict, Any, List
from decimal import Decimal

SCENARIO_CONFIGS: List[Dict[str, Any]] = [
    {
        "id": "healthy_merchant",
        "name": "Apex Electronics",
        "email": "finance@apexelectronics.in",
        "seed_offset": 101,
        "description": "Healthy merchant with stable baseline performance and low failure rate (< 3%).",
        "customer_count": 80,
        "payment_count": 250,
        "subscription_count": 40,
        "checkout_count": 50,
        "min_amount": Decimal("499.00"),
        "max_amount": Decimal("14999.00"),
        "baseline_failure_rate": 0.03,
        "special_rules": []
    },
    {
        "id": "payment_degradation",
        "name": "TrendStyle Apparel",
        "email": "ops@trendstyle.in",
        "seed_offset": 202,
        "description": "Severe payment route degradation: HDFC + UPI + Android + Evening failure spike (~75%).",
        "customer_count": 90,
        "payment_count": 300,
        "subscription_count": 30,
        "checkout_count": 60,
        "min_amount": Decimal("799.00"),
        "max_amount": Decimal("8999.00"),
        "baseline_failure_rate": 0.04,
        "special_rules": [
            {
                "type": "degradation_cluster",
                "bank": "HDFC",
                "method": "upi",
                "device": "android",
                "hours": [18, 19, 20, 21, 22],
                "failure_rate": 0.78,
                "error_code": "BAD_REQUEST_GATEWAY_TIMEOUT",
                "failure_reason": "Issuer bank UPI gateway timed out after 30s",
                "route": "hdfc_upi_direct"
            }
        ]
    },
    {
        "id": "checkout_abandonment",
        "name": "LuxeLiving Home",
        "email": "payments@luxeliving.co.in",
        "seed_offset": 303,
        "description": "High-value cart drop-offs at OTP entry and payment method selection stages.",
        "customer_count": 70,
        "payment_count": 150,
        "subscription_count": 15,
        "checkout_count": 100,
        "min_amount": Decimal("15000.00"),
        "max_amount": Decimal("85000.00"),
        "baseline_failure_rate": 0.05,
        "abandonment_rate": 0.58,
        "special_rules": [
            {
                "type": "abandonment_stages",
                "stages": ["otp_entry", "payment_method_select"],
                "stage_weights": [0.65, 0.35]
            }
        ]
    },
    {
        "id": "subscription_spike",
        "name": "CloudFlow SaaS",
        "email": "billing@cloudflow.tech",
        "seed_offset": 404,
        "description": "Recurring auto-debit renewal spike: month-end card expiry and mandate limit drops (~45%).",
        "customer_count": 100,
        "payment_count": 180,
        "subscription_count": 80,
        "checkout_count": 30,
        "min_amount": Decimal("1999.00"),
        "max_amount": Decimal("12999.00"),
        "baseline_failure_rate": 0.04,
        "subscription_failure_rate": 0.46,
        "special_rules": [
            {
                "type": "subscription_mandate_failures",
                "error_codes": ["MANDATE_LIMIT_EXCEEDED", "CARD_EXPIRED", "INSUFFICIENT_FUNDS"],
                "weights": [0.50, 0.30, 0.20]
            }
        ]
    },
    {
        "id": "high_value_recoverable",
        "name": "Titan B2B Industrial",
        "email": "accounts@titanb2b.in",
        "seed_offset": 505,
        "description": "High-ticket transactions with repeated failures successfully recovered via payment links.",
        "customer_count": 60,
        "payment_count": 160,
        "subscription_count": 25,
        "checkout_count": 40,
        "min_amount": Decimal("35000.00"),
        "max_amount": Decimal("175000.00"),
        "baseline_failure_rate": 0.18,
        "recovery_rate": 0.65,
        "special_rules": [
            {
                "type": "high_ticket_recoveries",
                "target_methods": ["netbanking", "card"],
                "recovery_actions": ["payment_link", "alt_method"]
            }
        ]
    }
]
