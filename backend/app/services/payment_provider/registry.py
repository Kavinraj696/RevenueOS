import os
import logging
from typing import Dict, Any, Optional
from app.models.enums import StrEnum
from app.config import settings
from app.services.payment_provider.base import PaymentProvider
from app.services.payment_provider.mock_provider import MockPaymentProvider
from app.services.payment_provider.razorpay_provider import RazorpayTestProvider

logger = logging.getLogger("revenueos.provider")


class ProviderMode(StrEnum):
    MOCK = "MOCK"
    RAZORPAY_TEST = "RAZORPAY_TEST"


class PaymentProviderRegistry:
    """
    Singleton registry managing the active payment provider.
    Enforces automatic fallback to MockPaymentProvider if Razorpay test keys are unavailable.
    Never exposes API secrets.
    """

    _instance: Optional["PaymentProviderRegistry"] = None
    _active_mode: ProviderMode = ProviderMode.MOCK

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PaymentProviderRegistry, cls).__new__(cls)
            # Initialize default mode from environment
            env_mode = os.getenv("PAYMENT_PROVIDER_MODE", "MOCK").strip().upper()
            cls._instance._active_mode = ProviderMode.RAZORPAY_TEST if env_mode == "RAZORPAY_TEST" else ProviderMode.MOCK
            cls._instance._mock_provider = MockPaymentProvider()
        return cls._instance

    @staticmethod
    def is_razorpay_configured() -> bool:
        """Check if genuine Razorpay test credentials are provided."""
        key_id = settings.RAZORPAY_KEY_ID or ""
        key_sec = settings.RAZORPAY_KEY_SECRET or ""
        is_placeholder = "placeholder" in key_id.lower() or "placeholder" in key_sec.lower()
        has_test_prefix = key_id.startswith("rzp_test_")
        return bool(has_test_prefix and key_sec and not is_placeholder)

    def get_provider(self, mode: Optional[ProviderMode] = None) -> PaymentProvider:
        """
        Retrieve active payment provider.
        If RAZORPAY_TEST is active but credentials are unavailable, automatically falls back to MockPaymentProvider.
        """
        target_mode = mode or self._active_mode

        if target_mode == ProviderMode.RAZORPAY_TEST:
            if self.is_razorpay_configured():
                try:
                    return RazorpayTestProvider()
                except Exception as e:
                    logger.warning(f"Failed to initialize RazorpayTestProvider ({e}). Falling back to MockPaymentProvider.")
                    return self._mock_provider
            else:
                logger.info("Razorpay test credentials not configured. Automatically falling back to MockPaymentProvider.")
                return self._mock_provider

        return self._mock_provider

    def set_mode(self, mode: ProviderMode) -> Dict[str, Any]:
        """Switch provider mode at runtime (e.g. during live demonstrations)."""
        self._active_mode = mode
        logger.info(f"Payment provider mode switched to: {mode.value}")
        return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        """
        Return safe status snapshot. Never exposes API secrets or private keys.
        """
        configured = self.is_razorpay_configured()
        masked_key = None
        if settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_ID.startswith("rzp_test_"):
            masked_key = settings.RAZORPAY_KEY_ID[:12] + "****"

        fallback_active = (self._active_mode == ProviderMode.RAZORPAY_TEST and not configured)
        effective_provider = "mock" if (self._active_mode == ProviderMode.MOCK or fallback_active) else "razorpay_test"

        return {
            "requested_mode": self._active_mode.value,
            "effective_provider": effective_provider,
            "is_razorpay_configured": configured,
            "key_id_masked": masked_key,
            "fallback_active": fallback_active,
            "available_modes": [m.value for m in ProviderMode]
        }


# Global registry instance
provider_registry = PaymentProviderRegistry()


def get_payment_provider(mode: Optional[ProviderMode] = None) -> PaymentProvider:
    """Convenience getter for the active payment provider."""
    return provider_registry.get_provider(mode)
