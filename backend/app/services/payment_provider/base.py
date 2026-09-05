from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, Any, Optional, List


class PaymentProvider(ABC):
    """
    Abstract Payment Provider interface.
    Enforces standardized contract across Mock and Razorpay Test modes.
    Never implement live mode functionality.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g. 'mock', 'razorpay_test')."""
        pass

    @abstractmethod
    def create_payment_link(
        self,
        amount: Decimal,
        currency: str = "INR",
        description: str = "Payment Link",
        customer_name: Optional[str] = None,
        customer_email: Optional[str] = None,
        customer_phone: Optional[str] = None,
        reference_id: Optional[str] = None,
        expire_by_minutes: int = 60,
        notify_sms: bool = True,
        notify_email: bool = True,
        notes: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Create a payment link for customer checkout."""
        pass

    @abstractmethod
    def fetch_payment_link(self, link_id: str) -> Dict[str, Any]:
        """Retrieve details of a payment link."""
        pass

    @abstractmethod
    def cancel_payment_link(self, link_id: str) -> Dict[str, Any]:
        """Cancel an existing unpaid payment link."""
        pass

    @abstractmethod
    def fetch_payment(self, payment_id: str) -> Dict[str, Any]:
        """Retrieve payment details by ID."""
        pass

    @abstractmethod
    def capture_payment(
        self,
        payment_id: str,
        amount: Decimal,
        currency: str = "INR"
    ) -> Dict[str, Any]:
        """Capture an authorized payment."""
        pass

    @abstractmethod
    def create_subscription(
        self,
        plan_id: str,
        total_count: int,
        customer_notify: int = 1,
        start_at: Optional[int] = None,
        notes: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """Create a recurring subscription mandate."""
        pass

    @abstractmethod
    def fetch_subscription(self, subscription_id: str) -> Dict[str, Any]:
        """Fetch subscription details by ID."""
        pass

    @abstractmethod
    def cancel_subscription(
        self,
        subscription_id: str,
        cancel_at_cycle_end: bool = False
    ) -> Dict[str, Any]:
        """Cancel an active subscription."""
        pass

    @abstractmethod
    def verify_webhook_signature(
        self,
        payload_body: bytes,
        signature: str,
        secret: Optional[str] = None
    ) -> bool:
        """Verify HMAC-SHA256 signature of incoming webhook."""
        pass
