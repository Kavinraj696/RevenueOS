from typing import Dict, Any, Optional
from fastapi import APIRouter, Request, Header, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.webhook_engine import RazorpayWebhookEngine

router = APIRouter()


@router.post(
    "/razorpay",
    status_code=status.HTTP_200_OK,
    summary="Ingest Razorpay webhook",
    description="Idempotent webhook endpoint with HMAC-SHA256 signature verification and recovery triggering."
)
async def ingest_razorpay_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None, alias="X-Razorpay-Signature"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Handle incoming webhooks from Razorpay or test harnesses.
    Enforces signature verification, event idempotency, state updates, and audit logging.
    """
    body = await request.body()
    engine = RazorpayWebhookEngine(db)
    return engine.process_webhook(
        payload_body=body,
        signature_header=x_razorpay_signature
    )
