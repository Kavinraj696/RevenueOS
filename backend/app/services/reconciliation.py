import uuid
import logging
from decimal import Decimal
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.db.base import quantize_inr, get_utc_now
from app.models.enums import PaymentStatus, OpportunityStatus, ActionStatus
from app.models.payment import Payment
from app.models.recovery_opportunity import RecoveryOpportunity
from app.models.recovery_action import RecoveryAction
from app.models.audit_event import AuditEvent
from app.services.payment_provider.registry import get_payment_provider

logger = logging.getLogger("revenueos.reconciliation")


class ReconciliationError(Exception):
    """Base exception for payment reconciliation failures."""
    pass


class PaymentReconciliationService:
    """
    Authoritative Payment Reconciliation Service.
    Compares internal transaction records against independent provider state,
    enforcing amount integrity, currency integrity, and verified recovery attribution.
    """

    def __init__(self, db: Session, provider=None):
        self.db = db
        self.provider = provider or get_payment_provider()

    def reconcile_payment(
        self,
        payment_id: uuid.UUID,
        provider_payment_id: Optional[str] = None,
        causal_trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Independently queries provider state and reconciles internal transaction ledger.
        Enforces amount and currency integrity before confirming recovery.
        """
        payment = self.db.query(Payment).filter(Payment.id == payment_id).first()
        if not payment:
            raise ReconciliationError(f"Payment {payment_id} not found.")

        target_provider_id = provider_payment_id or payment.provider_payment_id
        if not target_provider_id:
            payment.reconciliation_status = "MISSING_PROVIDER_REFERENCE"
            self.db.commit()
            return {
                "payment_id": str(payment.id),
                "reconciliation_status": "MISSING_PROVIDER_REFERENCE",
                "verified": False,
                "reason": "No provider payment ID linked to internal transaction."
            }

        # 1. Query normalized provider state
        try:
            norm_result = self.provider.fetch_normalized_payment(target_provider_id)
        except Exception as e:
            logger.error(f"Failed to query provider for {target_provider_id}: {e}")
            payment.reconciliation_status = "PROVIDER_UNAVAILABLE"
            self.db.commit()
            return {
                "payment_id": str(payment.id),
                "provider_payment_id": target_provider_id,
                "reconciliation_status": "PROVIDER_UNAVAILABLE",
                "verified": False,
                "reason": f"Provider state check failed: {e}"
            }

        # 2. Currency Integrity Check
        expected_currency = (payment.currency or "INR").upper()
        provider_currency = (norm_result.currency or "INR").upper()
        if provider_currency != expected_currency:
            payment.reconciliation_status = "RECONCILIATION_REQUIRED"
            self._record_reconciliation_audit(
                merchant_id=payment.merchant_id,
                payment_id=payment.id,
                status="MISMATCH_CURRENCY",
                summary=f"Currency mismatch detected: Expected {expected_currency}, got {provider_currency}.",
                causal_trace_id=causal_trace_id
            )
            self.db.commit()
            return {
                "payment_id": str(payment.id),
                "provider_payment_id": target_provider_id,
                "reconciliation_status": "RECONCILIATION_REQUIRED",
                "discrepancy": "currency_mismatch",
                "expected_currency": expected_currency,
                "provider_currency": provider_currency,
                "verified": False
            }

        # 3. Amount Integrity Check
        expected_amount = quantize_inr(payment.amount)
        provider_amount = quantize_inr(norm_result.amount)
        if expected_amount != provider_amount:
            payment.reconciliation_status = "RECONCILIATION_REQUIRED"
            self._record_reconciliation_audit(
                merchant_id=payment.merchant_id,
                payment_id=payment.id,
                status="MISMATCH_AMOUNT",
                summary=f"Amount mismatch detected: Expected ₹{expected_amount}, provider reports ₹{provider_amount}.",
                causal_trace_id=causal_trace_id
            )
            self.db.commit()
            return {
                "payment_id": str(payment.id),
                "provider_payment_id": target_provider_id,
                "reconciliation_status": "RECONCILIATION_REQUIRED",
                "discrepancy": "amount_mismatch",
                "expected_amount": float(expected_amount),
                "provider_amount": float(provider_amount),
                "verified": False
            }

        # 4. Status Integrity & Verification Confirmation
        payment.provider_payment_id = target_provider_id
        if norm_result.status in ("captured", "authorized", "success", "paid"):
            payment.status = PaymentStatus.SUCCESS.value
            payment.reconciliation_status = "MATCHED"

            # Reconcile Opportunity & Actions
            opp = (
                self.db.query(RecoveryOpportunity)
                .filter(RecoveryOpportunity.payment_id == payment.id)
                .first()
            )
            if opp:
                opp.status = OpportunityStatus.RECOVERED.value
                opp.actual_recovered_value = payment.amount

                opp_actions = (
                    self.db.query(RecoveryAction)
                    .filter(RecoveryAction.opportunity_id == opp.id)
                    .all()
                )
                for act in opp_actions:
                    act.status = ActionStatus.VERIFIED.value
                    act.verified_status = "confirmed"
                    act.verified_at = get_utc_now()
                    act.actual_recovered_amount = payment.amount
                    if causal_trace_id and not act.causal_trace_id:
                        act.causal_trace_id = causal_trace_id

            self._record_reconciliation_audit(
                merchant_id=payment.merchant_id,
                payment_id=payment.id,
                status="SUCCESS",
                summary=f"Payment {payment.id} verified and settled. Amount ₹{payment.amount}.",
                causal_trace_id=causal_trace_id
            )
            self.db.commit()
            return {
                "payment_id": str(payment.id),
                "provider_payment_id": target_provider_id,
                "reconciliation_status": "MATCHED",
                "verified": True,
                "settled_status": payment.status,
                "actual_recovered_amount": float(payment.amount)
            }
        elif norm_result.status in ("failed", "cancelled"):
            # If internal state is not already settled, record failure
            if payment.status not in (PaymentStatus.SUCCESS.value, PaymentStatus.RECOVERED.value):
                payment.status = PaymentStatus.FAILED.value
                payment.reconciliation_status = "MATCHED_FAILED"

            self.db.commit()
            return {
                "payment_id": str(payment.id),
                "provider_payment_id": target_provider_id,
                "reconciliation_status": "MATCHED_FAILED",
                "verified": False,
                "settled_status": payment.status
            }

        payment.reconciliation_status = "PENDING_CONFIRMATION"
        self.db.commit()
        return {
            "payment_id": str(payment.id),
            "provider_payment_id": target_provider_id,
            "reconciliation_status": "PENDING_CONFIRMATION",
            "verified": False,
            "settled_status": payment.status
        }

    def _record_reconciliation_audit(
        self,
        merchant_id: uuid.UUID,
        payment_id: uuid.UUID,
        status: str,
        summary: str,
        causal_trace_id: Optional[str] = None
    ) -> None:
        audit = AuditEvent(
            id=uuid.uuid4(),
            merchant_id=merchant_id,
            actor="RECONCILIATION_SERVICE",
            related_entity_type="payment",
            related_entity_id=payment_id,
            transaction_id=payment_id,
            event_type="payment_reconciliation",
            status=status,
            summary=summary,
            message=summary,
            metadata_json={
                "reconciliation_check": True,
                "causal_trace_id": causal_trace_id
            },
            request_id=causal_trace_id or str(uuid.uuid4())
        )
        self.db.add(audit)
