import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict

class SubscriptionAttemptResponse(BaseModel):
    id: uuid.UUID
    status: str
    failure_reason: Optional[str] = None
    error_code: Optional[str] = None
    attempted_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SubscriptionResponse(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    customer_id: uuid.UUID
    plan_name: str
    plan_amount: Decimal
    currency: str
    billing_cycle: str
    status: str
    created_at: datetime
    attempts: List[SubscriptionAttemptResponse] = []

    model_config = ConfigDict(from_attributes=True)

class PaginatedSubscriptionsResponse(BaseModel):
    total: int
    items: List[SubscriptionResponse]
    limit: int
    offset: int
