import uuid
from datetime import datetime
from decimal import Decimal
from typing import Dict, Any, Optional
from pydantic import BaseModel, ConfigDict, EmailStr

class MerchantBase(BaseModel):
    name: str
    email: str
    settings_json: Dict[str, Any] = {}

class MerchantCreate(MerchantBase):
    pass

class MerchantResponse(MerchantBase):
    id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class MerchantSummaryResponse(BaseModel):
    merchant_id: uuid.UUID
    merchant_name: str
    total_processed_volume: Decimal
    currency: str
    total_transactions_count: int
    successful_transactions_count: int
    failed_transactions_count: int
    success_rate_percentage: Decimal
    gross_revenue_at_risk: Decimal
    active_leaks_count: int
    recovery_opportunities_count: int
    active_subscriptions_count: int
    failed_subscriptions_count: int
    abandoned_checkout_sessions_count: int
    abandoned_cart_volume: Decimal

    model_config = ConfigDict(from_attributes=True)
