from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class PaymentResult(BaseModel):
    """Normalized provider-agnostic payment representation."""
    provider: str
    provider_payment_id: str
    provider_order_id: Optional[str] = None
    status: str  # captured, authorized, failed, refunded, pending
    amount: Decimal  # in INR currency units (e.g. 1590.00)
    currency: str = "INR"
    created_at: datetime
    error_code: Optional[str] = None
    error_description: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    raw_response: Dict[str, Any] = Field(default_factory=dict)


class PaymentLinkResult(BaseModel):
    """Normalized provider-agnostic payment link representation."""
    provider: str
    link_id: str
    short_url: str
    status: str  # created, paid, cancelled, expired
    amount: Decimal
    currency: str = "INR"
    created_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    raw_response: Dict[str, Any] = Field(default_factory=dict)


class SubscriptionResult(BaseModel):
    """Normalized provider-agnostic subscription representation."""
    provider: str
    subscription_id: str
    status: str  # active, authenticated, pending, halted, cancelled, completed
    plan_id: str
    total_count: Optional[int] = None
    paid_count: Optional[int] = None
    current_start: Optional[datetime] = None
    current_end: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    raw_response: Dict[str, Any] = Field(default_factory=dict)


class WebhookPayloadNormalized(BaseModel):
    """Normalized webhook event representation."""
    provider: str
    event_id: str
    event_type: str
    provider_payment_id: Optional[str] = None
    provider_order_id: Optional[str] = None
    status: Optional[str] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = "INR"
    raw_event: Dict[str, Any] = Field(default_factory=dict)
