import hmac
import hashlib
import uuid
from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

from app.db.base import quantize_inr
from app.config import settings
from app.services.payment_provider.base import PaymentProvider


class MockPaymentProvider(PaymentProvider):
    """
    Deterministic In-Memory Mock Payment Provider.
    Simulates Razorpay Test Mode APIs with zero network requests and zero credentials required.
    """

    def __init__(self):
        self._links: Dict[str, Dict[str, Any]] = {}
        self._payments: Dict[str, Dict[str, Any]] = {}
        self._subscriptions: Dict[str, Dict[str, Any]] = {}

    @property
    def provider_name(self) -> str:
        return "mock"

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
        amt = quantize_inr(amount)
        amt_paise = int(amt * 100)
        link_id = f"plink_mock_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=expire_by_minutes)

        payload = {
            "id": link_id,
            "provider": "mock",
            "amount": amt_paise,
            "amount_paid": 0,
            "currency": currency.upper(),
            "status": "created",
            "description": description,
            "reference_id": reference_id or f"ref_{uuid.uuid4().hex[:8]}",
            "short_url": f"https://rzp.io/i/mock_{uuid.uuid4().hex[:8]}",
            "customer": {
                "name": customer_name or "Test Customer",
                "email": customer_email or "customer@example.com",
                "contact": customer_phone or "+919876543210"
            },
            "notify": {
                "sms": notify_sms,
                "email": notify_email
            },
            "expire_by": int(expires_at.timestamp()),
            "expired_at": None,
            "notes": notes or {},
            "created_at": int(now.timestamp())
        }

        self._links[link_id] = payload
        return payload

    def fetch_payment_link(self, link_id: str) -> Dict[str, Any]:
        if link_id in self._links:
            return self._links[link_id]
        # Return synthetic structure if not in memory
        return {
            "id": link_id,
            "provider": "mock",
            "amount": 499900,
            "currency": "INR",
            "status": "created",
            "short_url": f"https://rzp.io/i/mock_{link_id[:8]}",
            "created_at": int(datetime.now(timezone.utc).timestamp())
        }

    def cancel_payment_link(self, link_id: str) -> Dict[str, Any]:
        link = self.fetch_payment_link(link_id)
        link["status"] = "cancelled"
        self._links[link_id] = link
        return link

    def fetch_payment(self, payment_id: str) -> Dict[str, Any]:
        if payment_id in self._payments:
            return self._payments[payment_id]
        return {
            "id": payment_id,
            "provider": "mock",
            "entity": "payment",
            "amount": 499900,
            "currency": "INR",
            "status": "authorized",
            "method": "upi",
            "bank": "HDFC",
            "captured": False,
            "description": "Mock payment record",
            "created_at": int(datetime.now(timezone.utc).timestamp())
        }

    def capture_payment(
        self,
        payment_id: str,
        amount: Decimal,
        currency: str = "INR"
    ) -> Dict[str, Any]:
        amt = quantize_inr(amount)
        amt_paise = int(amt * 100)
        payment = self.fetch_payment(payment_id)
        payment["status"] = "captured"
        payment["captured"] = True
        payment["amount"] = amt_paise
        payment["currency"] = currency.upper()
        self._payments[payment_id] = payment
        return payment

    def create_subscription(
        self,
        plan_id: str,
        total_count: int,
        customer_notify: int = 1,
        start_at: Optional[int] = None,
        notes: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        sub_id = f"sub_mock_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        payload = {
            "id": sub_id,
            "provider": "mock",
            "plan_id": plan_id,
            "status": "active",
            "current_start": int(now.timestamp()),
            "current_end": int((now + timedelta(days=30)).timestamp()),
            "total_count": total_count,
            "paid_count": 0,
            "customer_notify": customer_notify,
            "short_url": f"https://rzp.io/s/mock_{uuid.uuid4().hex[:8]}",
            "notes": notes or {},
            "created_at": int(now.timestamp())
        }
        self._subscriptions[sub_id] = payload
        return payload

    def fetch_subscription(self, subscription_id: str) -> Dict[str, Any]:
        if subscription_id in self._subscriptions:
            return self._subscriptions[subscription_id]
        return {
            "id": subscription_id,
            "provider": "mock",
            "plan_id": "plan_mock_monthly",
            "status": "active",
            "created_at": int(datetime.now(timezone.utc).timestamp())
        }

    def cancel_subscription(
        self,
        subscription_id: str,
        cancel_at_cycle_end: bool = False
    ) -> Dict[str, Any]:
        sub = self.fetch_subscription(subscription_id)
        sub["status"] = "cancelled"
        sub["cancel_at_cycle_end"] = cancel_at_cycle_end
        self._subscriptions[subscription_id] = sub
        return sub

    def verify_webhook_signature(
        self,
        payload_body: bytes,
        signature: str,
        secret: Optional[str] = None
    ) -> bool:
        sec = secret or settings.RAZORPAY_WEBHOOK_SECRET or "rzp_webhook_secret_placeholder"
        expected = hmac.new(
            sec.encode("utf-8"),
            payload_body,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
