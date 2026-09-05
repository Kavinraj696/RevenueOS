from enum import Enum

class StrEnum(str, Enum):
    """String enum for consistent serialization and DB storage."""
    def __str__(self) -> str:
        return str(self.value)

class PaymentStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"
    RECOVERED = "recovered"

class PaymentAttemptStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"

class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    FAILED = "failed"
    CANCELLED = "cancelled"

class CheckoutSessionStatus(StrEnum):
    COMPLETED = "completed"
    ABANDONED = "abandoned"

class PaymentMethod(StrEnum):
    UPI = "upi"
    CARD = "card"
    NETBANKING = "netbanking"
    WALLET = "wallet"
    EMI = "emi"

class BankCode(StrEnum):
    HDFC = "HDFC"
    ICICI = "ICICI"
    SBI = "SBI"
    AXIS = "AXIS"
    KOTAK = "KOTAK"
    YESB = "YESB"

class DeviceType(StrEnum):
    ANDROID = "android"
    IOS = "ios"
    DESKTOP = "desktop"
    MOBILE_WEB = "mobile_web"

class LeakType(StrEnum):
    PAYMENT_FAILURE = "payment_failure"
    CHECKOUT_ABANDONMENT = "checkout_abandonment"
    SUBSCRIPTION_FAILURE = "subscription_failure"
    ANOMALY = "anomaly"

class OpportunityStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    ACTION_SELECTED = "action_selected"
    PENDING_APPROVAL = "pending_approval"
    EXECUTING = "executing"
    RECOVERED = "recovered"
    FAILED = "failed"
    DISMISSED = "dismissed"

class ActionType(StrEnum):
    CREATE_PAYMENT_LINK = "create_payment_link"
    SEND_RECOVERY_NOTIFICATION = "send_recovery_notification"
    RECOMMEND_ALTERNATIVE_PAYMENT = "recommend_alternative_payment"
    SUBSCRIPTION_RECOVERY = "subscription_recovery"
    MERCHANT_ESCALATION = "merchant_escalation"
    RETRY = "retry"
    NO_ACTION = "no_action"

    # Aliases
    PAYMENT_LINK = "payment_link"
    NOTIFICATION = "notification"
    ALT_METHOD = "alt_method"
    SUBSCRIPTION_WORKFLOW = "subscription_workflow"
    ESCALATE = "escalate"

class ActionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    EXPIRED = "expired"

    # Backward-compatible aliases
    PROPOSED = "proposed"
    EXECUTED = "executed"
    SUCCEEDED = "succeeded"

class RiskSegment(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class OpportunityPriority(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class PolicyAction(StrEnum):
    SEND_RECOVERY_NOTIFICATION = "SEND_RECOVERY_NOTIFICATION"
    CREATE_PAYMENT_LINK = "CREATE_PAYMENT_LINK"
    RECOMMEND_ALTERNATIVE_PAYMENT = "RECOMMEND_ALTERNATIVE_PAYMENT"
    RETRY_ALLOWED_PAYMENT = "RETRY_ALLOWED_PAYMENT"
    TRIGGER_SUBSCRIPTION_RECOVERY = "TRIGGER_SUBSCRIPTION_RECOVERY"
    REQUEST_MERCHANT_APPROVAL = "REQUEST_MERCHANT_APPROVAL"
    BLOCK_ACTION = "BLOCK_ACTION"


class AuditEventType(StrEnum):
    TRANSACTION_DETECTED = "transaction_detected"
    REVENUE_LEAK_DETECTED = "revenue_leak_detected"
    ML_PREDICTION = "ml_prediction"
    OPPORTUNITY_CREATED = "opportunity_created"
    AI_INVESTIGATION = "ai_investigation"
    AI_RECOMMENDATION = "ai_recommendation"
    POLICY_DECISION = "policy_decision"
    APPROVAL = "approval"
    RECOVERY_ACTION = "recovery_action"
    PROVIDER_RESPONSE = "provider_response"
    WEBHOOK = "webhook"
    RECOVERY_VERIFICATION = "recovery_verification"
    FINAL_RECOVERED_AMOUNT = "final_recovered_amount"


class AuditActor(StrEnum):
    SYSTEM = "SYSTEM"
    AI_RECOVERY_AGENT = "AI_RECOVERY_AGENT"
    POLICY_ENGINE = "POLICY_ENGINE"
    RAZORPAY_TEST_PROVIDER = "RAZORPAY_TEST_PROVIDER"
    MOCK_PROVIDER = "MOCK_PROVIDER"
    WEBHOOK_ENGINE = "WEBHOOK_ENGINE"
    MERCHANT_OPERATOR = "MERCHANT_OPERATOR"

