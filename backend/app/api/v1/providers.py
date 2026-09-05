from decimal import Decimal
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, status

from app.services.payment_provider.registry import (
    ProviderMode,
    provider_registry,
    get_payment_provider
)

router = APIRouter()


class SwitchProviderModeRequest(BaseModel):
    mode: str = Field(..., description="Target mode: 'MOCK' or 'RAZORPAY_TEST'")


class CreatePaymentLinkRequest(BaseModel):
    amount: Decimal = Field(..., gt=0, description="Amount in INR")
    description: str = Field(default="Recovery payment link")
    customer_name: Optional[str] = Field(default="Test Customer")
    customer_email: Optional[str] = Field(default="customer@example.com")
    customer_phone: Optional[str] = Field(default="+919876543210")
    reference_id: Optional[str] = None
    expire_by_minutes: int = Field(default=60, ge=5, le=43200)


@router.get(
    "/status",
    summary="Get active payment provider status",
    description="Inspect provider mode and configuration status. Never exposes API secrets."
)
def get_provider_status() -> Dict[str, Any]:
    """
    Returns current provider mode, configured status, masked key ID, and fallback details.
    """
    return provider_registry.get_status()


@router.post(
    "/mode",
    summary="Switch demo provider mode (MOCK / RAZORPAY_TEST)",
    description="Runtime toggle between MOCK mode and official RAZORPAY_TEST mode."
)
def switch_provider_mode(request: SwitchProviderModeRequest) -> Dict[str, Any]:
    """
    Toggle between MOCK mode and RAZORPAY_TEST mode.
    If RAZORPAY_TEST credentials are not configured, automatically falls back to Mock.
    """
    raw_mode = request.mode.strip().upper()
    if raw_mode not in {ProviderMode.MOCK.value, ProviderMode.RAZORPAY_TEST.value}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid mode '{request.mode}'. Allowed modes: {[m.value for m in ProviderMode]}"
        )

    mode = ProviderMode(raw_mode)
    return provider_registry.set_mode(mode)


@router.post(
    "/payment-links",
    summary="Generate payment link through active provider",
    description="Creates a test-mode payment link using Mock or Razorpay Test API."
)
def create_payment_link(request: CreatePaymentLinkRequest) -> Dict[str, Any]:
    """
    Generate payment link via active provider.
    """
    provider = get_payment_provider()
    return provider.create_payment_link(
        amount=request.amount,
        description=request.description,
        customer_name=request.customer_name,
        customer_email=request.customer_email,
        customer_phone=request.customer_phone,
        reference_id=request.reference_id,
        expire_by_minutes=request.expire_by_minutes
    )
