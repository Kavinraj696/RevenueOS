import json
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Request, Header, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.base import get_utc_now
from app.models.webhook_event import WebhookEvent
from app.services.webhook_engine import RazorpayWebhookEngine

router = APIRouter()

MAX_WEBHOOK_PAYLOAD_BYTES = 1024 * 1024  # 1 MB rate/abuse protection


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
    if len(body) > MAX_WEBHOOK_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Webhook payload exceeds limit ({len(body)} > {MAX_WEBHOOK_PAYLOAD_BYTES} bytes)."
        )

    engine = RazorpayWebhookEngine(db)
    return engine.process_webhook(
        payload_body=body,
        signature_header=x_razorpay_signature
    )


@router.get(
    "/events",
    summary="List Webhook Events",
    description="Query persisted webhook events by event_type, processing_status, or provider."
)
def list_webhook_events(
    event_type: Optional[str] = Query(None),
    processing_status: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    query = db.query(WebhookEvent)
    if event_type:
        query = query.filter(WebhookEvent.event_type == event_type)
    if processing_status:
        query = query.filter(WebhookEvent.processing_status == processing_status)
    if provider:
        query = query.filter(WebhookEvent.provider == provider)

    events = query.order_by(WebhookEvent.received_at.desc()).limit(limit).all()
    return [
        {
            "id": str(e.id),
            "event_id": e.event_id,
            "event_type": e.event_type,
            "provider": e.provider,
            "signature_verified": e.signature_verified,
            "processing_status": e.processing_status,
            "processed": e.processed,
            "payload_hash": e.payload_hash,
            "received_at": e.received_at.isoformat() if e.received_at else None,
            "processed_at": e.processed_at.isoformat() if e.processed_at else None,
            "processing_error": e.processing_error
        }
        for e in events
    ]


@router.get(
    "/events/{event_id}",
    summary="Get Webhook Event Details",
    description="Retrieve a single webhook event by event_id."
)
def get_webhook_event(
    event_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    event = db.query(WebhookEvent).filter(WebhookEvent.event_id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail=f"Webhook event {event_id} not found.")

    return {
        "id": str(event.id),
        "event_id": event.event_id,
        "event_type": event.event_type,
        "provider": event.provider,
        "signature_verified": event.signature_verified,
        "processing_status": event.processing_status,
        "processed": event.processed,
        "payload_hash": event.payload_hash,
        "raw_payload_json": event.raw_payload_json,
        "received_at": event.received_at.isoformat() if event.received_at else None,
        "processed_at": event.processed_at.isoformat() if event.processed_at else None,
        "processing_error": event.processing_error
    }


@router.post(
    "/events/{event_id}/reprocess",
    summary="Reprocess Webhook Event",
    description="Safely reprocesses an event that failed during previous mutation."
)
def reprocess_webhook_event(
    event_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    event = db.query(WebhookEvent).filter(WebhookEvent.event_id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail=f"Webhook event {event_id} not found.")

    engine = RazorpayWebhookEngine(db)
    raw_bytes = json.dumps(event.raw_payload_json).encode("utf-8")
    # For safe reprocessing, pass verified event directly to handler
    state_updated, related_entity_type, related_entity_id, recovery_triggered, merchant_id, audit_msg = (
        engine._handle_event_mutation(event.event_type, event.raw_payload_json)
    )
    event.processing_status = "PROCESSED"
    event.processed = True
    event.processing_error = None
    event.processed_at = get_utc_now()
    db.commit()

    return {
        "event_id": event.event_id,
        "processing_status": "PROCESSED",
        "state_updated": state_updated,
        "message": "Webhook event reprocessed successfully."
    }

