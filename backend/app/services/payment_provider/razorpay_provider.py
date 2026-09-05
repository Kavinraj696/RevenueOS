import hmac
import hashlib
from decimal import Decimal
from typing import Dict, Any, Optional
import httpx

from app.db.base import quantize_inr
from app.config import settings
from app.services.payment_provider.base import PaymentProvider


class RazorpayTestProvider(PaymentProvider):
    """
    Razorpay Test Mode Integration.
    Connects to official Razorpay API endpoints (https://api.razorpay.com/v1/) using test credentials.
    CRITICAL: Live mode keys ('rzp_live_...') are strictly rejected.
    """

    BASE_URL = "https://api.razorpay.com/v1"

    def __init__(
        self,
        key_id: Optional[str] = None,
        key_secret: Optional[str] = None,
        timeout: float = 10.0
    ):
        self.key_id = settings.RAZORPAY_KEY_ID if key_id is None else key_id
        self.key_secret = settings.RAZORPAY_KEY_SECRET if key_secret is None else key_secret
        self.timeout = timeout

        if not self.key_id or not self.key_secret:
            raise ValueError("Razorpay Test Provider requires RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET.")

        # Safety constraint: Live credentials prohibited
        if self.key_id.startswith("rzp_live_"):
            raise ValueError("Live mode credentials ('rzp_live_...') are prohibited. Only test mode is allowed.")

    @property
    def provider_name(self) -> str:
        return "razorpay_test"

    def _get_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.BASE_URL,
            auth=(self.key_id, self.key_secret),
            timeout=self.timeout,
            headers={"Content-Type": "application/json"}
        )

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

        payload: Dict[str, Any] = {
            "amount": amt_paise,
            "currency": currency.upper(),
            "description": description,
            "notify": {
                "sms": notify_sms,
                "email": notify_email
            }
        }
        if reference_id:
            payload["reference_id"] = reference_id
        if customer_name or customer_email or customer_phone:
            payload["customer"] = {
                "name": customer_name or "",
                "email": customer_email or "",
                "contact": customer_phone or ""
            }
        if notes:
            payload["notes"] = notes

        with self._get_client() as client:
            resp = client.post("/payment_links", json=payload)
            if resp.status_code >= 400:
                return {
                    "error": True,
                    "status_code": resp.status_code,
                    "detail": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text
                }
            return resp.json()

    def fetch_payment_link(self, link_id: str) -> Dict[str, Any]:
        with self._get_client() as client:
            resp = client.get(f"/payment_links/{link_id}")
            if resp.status_code >= 400:
                return {"error": True, "status_code": resp.status_code, "detail": resp.text}
            return resp.json()

    def cancel_payment_link(self, link_id: str) -> Dict[str, Any]:
        with self._get_client() as client:
            resp = client.post(f"/payment_links/{link_id}/cancel")
            if resp.status_code >= 400:
                return {"error": True, "status_code": resp.status_code, "detail": resp.text}
            return resp.json()

    def fetch_payment(self, payment_id: str) -> Dict[str, Any]:
        with self._get_client() as client:
            resp = client.get(f"/payments/{payment_id}")
            if resp.status_code >= 400:
                return {"error": True, "status_code": resp.status_code, "detail": resp.text}
            return resp.json()

    def capture_payment(
        self,
        payment_id: str,
        amount: Decimal,
        currency: str = "INR"
    ) -> Dict[str, Any]:
        amt = quantize_inr(amount)
        amt_paise = int(amt * 100)
        payload = {"amount": amt_paise, "currency": currency.upper()}

        with self._get_client() as client:
            resp = client.post(f"/payments/{payment_id}/capture", json=payload)
            if resp.status_code >= 400:
                return {"error": True, "status_code": resp.status_code, "detail": resp.text}
            return resp.json()

    def create_subscription(
        self,
        plan_id: str,
        total_count: int,
        customer_notify: int = 1,
        start_at: Optional[int] = None,
        notes: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "plan_id": plan_id,
            "total_count": total_count,
            "customer_notify": customer_notify
        }
        if start_at:
            payload["start_at"] = start_at
        if notes:
            payload["notes"] = notes

        with self._get_client() as client:
            resp = client.post("/subscriptions", json=payload)
            if resp.status_code >= 400:
                return {"error": True, "status_code": resp.status_code, "detail": resp.text}
            return resp.json()

    def fetch_subscription(self, subscription_id: str) -> Dict[str, Any]:
        with self._get_client() as client:
            resp = client.get(f"/subscriptions/{subscription_id}")
            if resp.status_code >= 400:
                return {"error": True, "status_code": resp.status_code, "detail": resp.text}
            return resp.json()

    def cancel_subscription(
        self,
        subscription_id: str,
        cancel_at_cycle_end: bool = False
    ) -> Dict[str, Any]:
        payload = {"cancel_at_cycle_end": 1 if cancel_at_cycle_end else 0}
        with self._get_client() as client:
            resp = client.post(f"/subscriptions/{subscription_id}/cancel", json=payload)
            if resp.status_code >= 400:
                return {"error": True, "status_code": resp.status_code, "detail": resp.text}
            return resp.json()

    def verify_webhook_signature(
        self,
        payload_body: bytes,
        signature: str,
        secret: Optional[str] = None
    ) -> bool:
        sec = secret or settings.RAZORPAY_WEBHOOK_SECRET
        if not sec:
            return False
        expected = hmac.new(
            sec.encode("utf-8"),
            payload_body,
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
