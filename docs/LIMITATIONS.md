# RevenueOS — System Limitations & Boundaries

## 1. System Scope & Boundaries

RevenueOS is an autonomous revenue leak detection, triage, and recovery orchestration platform purpose-built for the Indian digital commerce and payments ecosystem. To maintain complete transparency with merchants and auditors, this document articulates explicit system boundaries, test mode constraints, and operational non-goals.

---

## 2. Test & Sandbox Mode Operational Constraints

* **Strict Test Mode Isolation**: RevenueOS operates in **Razorpay Test Mode** using sandbox API keys (`rzp_test_*`). No live bank charges, credit card authorizations, or real financial settlements are initiated.
* **Simulated Webhooks & Settlement**: Webhook deliveries, payment link captures, and mandate debits are triggered against mock/sandbox provider endpoints with HMAC-SHA256 cryptographic verification.
* **Zero Real Money Movement**: Financial figures displayed on the dashboard represent realistic synthetic transaction telemetry. No merchant or consumer bank accounts are touched.

---

## 3. Explicit Non-Goals: What RevenueOS Cannot Do

1. **Not a Core Payment Gateway**: RevenueOS is not a card network acquiring switch, payment gateway, or banking aggregator. It does not replace Razorpay, Cashfree, or PayU; rather, it sits on top of payment service providers (PSPs) as an intelligence and recovery layer.
2. **Not an Arbitrary Financial Transfer System**: RevenueOS cannot unilaterally debit customer bank accounts or credit cards without explicit prior mandate authorization or consumer-initiated payment link completion.
3. **Not a Dispute Arbitrator**: The platform does not handle chargeback arbitration or legal dispute litigation with card networks (Visa/Mastercard/RuPay).
4. **No Speculative Recovery Booking**: Under no circumstances does the system book predicted, modeled, or anticipated revenue as realized capital on accounting ledgers.

---

## 4. Machine Learning Model Boundaries & Fallback Behavior

* **Confidence Floor ($P_{rec} \ge 0.20$)**:
  - The ML LightGBM recovery probability model enforces an operational floor of 20%. Any opportunity scoring below 0.20 is treated as a **non-recoverable false positive** or low-yield transaction and suppressed from automated outreach.
* **Transient Failure Specialization**:
  - The model is optimized for transient network timeouts, gateway degradations, bank downtime spikes, and session abandonments. It cannot predict recovery for permanently closed bank accounts or cancelled card numbers.
* **Cold-Start Fallback**:
  - When historical customer tenure or previous transaction records are unavailable, the model defaults to conservative merchant-level empirical recovery baselines (45.0% for UPI, 35.0% for Cards, 25.0% for Netbanking).

---

## 5. Unsupported Payment Rails & Failure Scenarios

| Category | Supported by RevenueOS | Unsupported Rails / Exceptions |
| :--- | :--- | :--- |
| **Payment Rails** | UPI (Collect & Intent), Credit/Debit Cards, Netbanking (Top 10 Indian Banks), e-Mandates | Offline Cash on Delivery (COD), International Wire Transfers (SWIFT), Crypto/Virtual Digital Assets |
| **Failure Types** | Gateway timeouts, route degradation, checkout abandonment, mandate renewal drops | Stolen card fraud blocks, blacklisted VPA IDs, OFAC sanctions list rejections |
| **Recovery Actions** | 1-click Razorpay payment links, multi-channel payment retries, mandate re-triggering | Cold telephone debt collections, physical door-to-door recovery, legal notices |

---

## 6. Regulatory & Compliance Boundaries

* **RBI Auto-Debit Mandate Circulars**: RevenueOS respects Reserve Bank of India (RBI) regulations requiring Pre-Debit Notifications (AFA / Additional Factor of Authentication) at least 24 hours prior to recurring debit executions.
* **DPDP Act (Digital Personal Data Protection)**: All consumer telemetry (phone numbers, email addresses, names) is stored masked (e.g. `98765*****`) and salted in production environments. Zero raw cardholder PAN or CVV data is stored (PCI-DSS Level 1 compliance delegated to Razorpay).
* **Deterministic Policy Engine Supremacy**: AI Agent recommendations are advisory. The hardcoded, auditable **Financial Action Policy Engine** possesses absolute veto power over every action dispatched by the platform.
