import uuid
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, ConfigDict

class PaymentAttemptResponse(BaseModel):
    id: uuid.UUID
    attempt_number: int
    status: str
    failure_reason: Optional[str] = None
    error_code: Optional[str] = None
    attempted_at: datetime

    model_config = ConfigDict(from_attributes=True)

class PaymentResponse(BaseModel):
    id: uuid.UUID
    merchant_id: uuid.UUID
    customer_id: uuid.UUID
    amount: Decimal
    currency: str
    status: str
    payment_method: str
    bank: Optional[str] = None
    device_type: str
    route: str
    created_at: datetime
    attempts: List[PaymentAttemptResponse] = []

    model_config = ConfigDict(from_attributes=True)

class PaymentFailureResponse(BaseModel):
    payment_id: uuid.UUID
    customer_id: uuid.UUID
    amount: Decimal
    currency: str
    payment_method: str
    bank: Optional[str] = None
    device_type: str
    route: str
    created_at: datetime
    attempt_count: int
    last_error_code: Optional[str] = None
    last_failure_reason: Optional[str] = None
    is_recoverable: bool = True

    model_config = ConfigDict(from_attributes=True)

class PaginatedPaymentsResponse(BaseModel):
    total: int
    items: List[PaymentResponse]
    limit: int
    offset: int
