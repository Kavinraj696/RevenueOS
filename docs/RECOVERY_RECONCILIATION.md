# Recovery Reconciliation & Financial Verification

## 1. Reconciliation Architecture

In RevenueOS, **an initial API response or raw webhook is NEVER treated as final financial truth**.
Only independent verification via the **Payment Reconciliation Engine** confirms actual recovered revenue.

```mermaid
flowchart TD
    WH[Incoming Webhook\npayment.captured / payment_link.paid] --> NORM[Normalized Event Schema]
    NORM --> REC[PaymentReconciliationService\nIndependent Fetch & Compare]
    REC --> FETCH[Fetch Current State from Provider\nGET /v1/payments/{id}]
    FETCH --> COMP{Integrity Validation}
    COMP -- Currency Mismatch\n(e.g. USD != INR) --> FLAG[reconciliation_status = RECONCILIATION_REQUIRED\nverified = False]
    COMP -- Amount Mismatch\n(e.g. ₹100 != ₹1000) --> FLAG
    COMP -- Provider Status != captured --> FLAG
    COMP -- Match Confirmed --> VERIFIED[reconciliation_status = MATCHED\nverified = True]
    VERIFIED --> ACT[RecoveryAction: VERIFIED\nactual_recovered_amount = amount]
    VERIFIED --> OPP[RecoveryOpportunity: RECOVERED\nactual_recovered_value = amount]
    VERIFIED --> AUDIT[AuditEvent Emitted\nwith causal_trace_id]
```

---

## 2. Why Webhook $\neq$ Recovery Confirmation

Treating a webhook as final financial authority introduces critical risks:
1. **Network Spoofing / Replay:** Malicious or malformed payloads claiming payment completion.
2. **Partial Gateway Authorizations:** An authorization might never be captured, or might be voided immediately.
3. **Currency Conversion Ambiguity:** A customer may have paid in USD or EUR while the ledger expects INR, causing subtle balance sheet discrepancies.
4. **Amount Discrepancy (e.g. Surcharges / Partial Payments):** An invoice for ₹5,000 might only have ₹500 paid.

Therefore, RevenueOS enforces an explicit two-step financial reconciliation before marking revenue as **RECOVERED**.

---

## 3. Normalized Data Matching

When `PaymentReconciliationService.reconcile_payment()` is invoked:
1. **Provider Query:** The service calls `provider.fetch_normalized_payment(provider_payment_id)`.
2. **Deterministic Comparisons:**
   - **Payment ID Matching:** Ensures the returned ID strictly matches `payment.provider_payment_id`.
   - **Amount Integrity:** Verifies `abs(provider_result.amount - payment.amount) < Decimal("0.01")`.
   - **Currency Integrity:** Verifies ISO `provider_result.currency == payment.currency` (`INR`).
   - **Provider Terminal State:** Verifies `provider_result.status in ("captured", "authorized", "paid")`.

---

## 4. Discrepancy Detection & Anomaly Resolution

When a mismatch is identified:
- **`payment.reconciliation_status`** is set to `"RECONCILIATION_REQUIRED"`.
- **`RecoveryOpportunity`** is **NOT** marked recovered; remains in its previous state.
- **`RecoveryAction`** is **NOT** marked verified.
- An **`AuditEvent`** with status `"FAILURE"` or `"WARNING"` is appended with detailed difference vectors (`expected_amount`, `provider_amount`, `expected_currency`, `provider_currency`).
- An incident alert is queued for merchant ops review.

---

## 5. Audit Trail & Causal Tracing

Every reconciled recovery action records end-to-end causal provenance:
- **`causal_trace_id`:** Connects the initial revenue leak detection $\rightarrow$ ML scoring $\rightarrow$ agent decision $\rightarrow$ policy approval $\rightarrow$ provider execution $\rightarrow$ webhook ingestion $\rightarrow$ reconciliation event.
- **Immutable Ledger:** All state transitions generate immutable `AuditEvent` rows with UTC timestamps, actor (`RECONCILIATION_SERVICE`), and before/after state diffs.

---

## 6. Stage 8 Discrepancy Refusal & Verified Recovery Attribution

Demonstrated in **Scenario F**:
1. **Settlement Discrepancy Detection**:
   When provider reports settling ₹3,000 for an expected ₹5,000 transaction, the reconciliation engine intercepts the mismatch:
   ```json
   {
     "reconciliation_status": "RECONCILIATION_REQUIRED",
     "verified": false,
     "discrepancy": "amount_mismatch",
     "expected_amount": 5000.00,
     "settled_amount": 3000.00
   }
   ```
2. **Refusal of False Verification**:
   The recovery action remains `UNVERIFIED`, opportunity status remains unrecovered, and zero rupees are credited to Actual Recovered Revenue.
3. **Single Source of Truth Guarantee**:
   Only payments where `reconciliation_status == "MATCHED"` and `verified == True` update `RecoveryAction.actual_recovered_amount`, feeding directly into `/analytics/business-metrics` and `/analytics/roi`.

