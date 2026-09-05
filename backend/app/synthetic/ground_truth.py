"""
RevenueOS Ground Truth System (Stage 2)
=======================================
Isolated ground-truth data models and registry.
Ground truth represents what was injected into synthetic scenarios:
- What revenue was actually lost
- What revenue was potentially recoverable vs non-recoverable
- Which transactions, customers, subscriptions, and checkout sessions were affected
- Root cause dimensions and incident windows

CRITICAL ARCHITECTURAL RULE:
Ground truth is strictly isolated for evaluation, benchmarking, and unit testing.
It is NEVER accessed or used by production detection, ML inference, or AI agents.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class NonRecoveryReason(str, Enum):
    """Ground-truth reasons why a transaction should NOT be recovered."""
    FRAUD_RISK = "FRAUD_RISK"
    EXCESSIVE_RETRIES = "EXCESSIVE_RETRIES"
    EXPIRED_WINDOW = "EXPIRED_WINDOW"
    INVALID_DETAILS = "INVALID_DETAILS"
    USER_CANCELLED = "USER_CANCELLED"
    POLICY_PROHIBITED = "POLICY_PROHIBITED"
    HEALTHY_UNINVOLVED = "HEALTHY_UNINVOLVED"


@dataclass
class TransactionGroundTruth:
    """Ground truth for a single transaction/payment."""
    transaction_id: uuid.UUID
    customer_id: uuid.UUID
    scenario_id: str
    is_injected_failure: bool
    is_recoverable: bool
    loss_amount: Decimal
    recovery_reason: Optional[str] = None
    non_recovery_reason: Optional[str] = None
    expected_recovery_action: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transaction_id": str(self.transaction_id),
            "customer_id": str(self.customer_id),
            "scenario_id": self.scenario_id,
            "is_injected_failure": self.is_injected_failure,
            "is_recoverable": self.is_recoverable,
            "loss_amount": float(self.loss_amount),
            "recovery_reason": self.recovery_reason,
            "non_recovery_reason": self.non_recovery_reason,
            "expected_recovery_action": self.expected_recovery_action,
        }


@dataclass
class SubscriptionGroundTruth:
    """Ground truth for a recurring subscription renewal attempt."""
    subscription_id: uuid.UUID
    customer_id: uuid.UUID
    is_injected_failure: bool
    is_recoverable: bool
    loss_amount: Decimal
    failure_reason: str
    non_recovery_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subscription_id": str(self.subscription_id),
            "customer_id": str(self.customer_id),
            "is_injected_failure": self.is_injected_failure,
            "is_recoverable": self.is_recoverable,
            "loss_amount": float(self.loss_amount),
            "failure_reason": self.failure_reason,
            "non_recovery_reason": self.non_recovery_reason,
        }


@dataclass
class CheckoutGroundTruth:
    """Ground truth for a checkout session abandonment."""
    checkout_session_id: uuid.UUID
    customer_id: Optional[uuid.UUID]
    is_injected_abandonment: bool
    stage_dropped: str
    cart_value: Decimal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkout_session_id": str(self.checkout_session_id),
            "customer_id": str(self.customer_id) if self.customer_id else None,
            "is_injected_abandonment": self.is_injected_abandonment,
            "stage_dropped": self.stage_dropped,
            "cart_value": float(self.cart_value),
        }


@dataclass
class ScenarioGroundTruth:
    """
    Scenario-level ground truth metadata.
    Completely describes the injected incident, baseline rates, affected cohorts,
    and exact transaction-level annotations.
    """
    scenario_id: str
    merchant_id: uuid.UUID
    merchant_name: str
    baseline_failure_rate: float
    incident_failure_rate: float
    affected_dimension: str
    affected_segment: Dict[str, Any]
    incident_start: datetime
    incident_end: datetime
    total_revenue_at_risk: Decimal = Decimal("0.00")
    potentially_recoverable_revenue: Decimal = Decimal("0.00")
    non_recoverable_revenue: Decimal = Decimal("0.00")
    affected_transaction_ids: List[uuid.UUID] = field(default_factory=list)
    affected_customer_ids: List[uuid.UUID] = field(default_factory=list)
    transactions: Dict[uuid.UUID, TransactionGroundTruth] = field(default_factory=dict)
    subscriptions: Dict[uuid.UUID, SubscriptionGroundTruth] = field(default_factory=dict)
    checkouts: Dict[uuid.UUID, CheckoutGroundTruth] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "merchant_id": str(self.merchant_id),
            "merchant_name": self.merchant_name,
            "baseline_failure_rate": self.baseline_failure_rate,
            "incident_failure_rate": self.incident_failure_rate,
            "affected_dimension": self.affected_dimension,
            "affected_segment": self.affected_segment,
            "incident_start": self.incident_start.isoformat(),
            "incident_end": self.incident_end.isoformat(),
            "total_revenue_at_risk": float(self.total_revenue_at_risk),
            "potentially_recoverable_revenue": float(self.potentially_recoverable_revenue),
            "non_recoverable_revenue": float(self.non_recoverable_revenue),
            "affected_transactions_count": len(self.affected_transaction_ids),
            "affected_customers_count": len(self.affected_customer_ids),
            "transactions": {str(k): v.to_dict() for k, v in self.transactions.items()},
            "subscriptions": {str(k): v.to_dict() for k, v in self.subscriptions.items()},
            "checkouts": {str(k): v.to_dict() for k, v in self.checkouts.items()},
        }


class GroundTruthRegistry:
    """
    Thread-safe registry for ground-truth datasets generated during test/demo runs.
    """
    _registry: Dict[str, ScenarioGroundTruth] = {}

    @classmethod
    def register(cls, ground_truth: ScenarioGroundTruth) -> None:
        cls._registry[ground_truth.scenario_id] = ground_truth

    @classmethod
    def get(cls, scenario_id: str) -> Optional[ScenarioGroundTruth]:
        return cls._registry.get(scenario_id)

    @classmethod
    def clear(cls) -> None:
        cls._registry.clear()

    @classmethod
    def all(cls) -> Dict[str, ScenarioGroundTruth]:
        return dict(cls._registry)
