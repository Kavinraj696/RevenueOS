import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict

class CheckoutSessionResponse(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    customer_id: Optional[uuid.UUID] = None
    cart_value: Decimal
    currency: str
    status: str
    stage_dropped: Optional[str] = None
    device_type: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class PaginatedCheckoutSessionsResponse(BaseModel):
    total: int
    items: List[CheckoutSessionResponse]
    limit: int
    offset: int
