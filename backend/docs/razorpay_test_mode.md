# Razorpay Test Mode Integration & Webhook Engine — Setup Guide

RevenueOS includes a robust payment abstraction layer supporting both deterministic local simulations (`MockPaymentProvider`) and the official Razorpay test mode APIs (`RazorpayTestProvider`).

---

## 1. Provider Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    PaymentProvider (ABC)                    │
└──────────────────────────────┬──────────────────────────────┘
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
   ┌───────────────────────┐       ┌───────────────────────┐
   │  MockPaymentProvider  │       │  RazorpayTestProvider │
   │  - Deterministic mock │       │  - httpx HTTP client  │
   │  - Zero network reqs  │       │  - Official Test REST │
   │  - Always available   │       │  - rzp_test_ keys only│
   └───────────────────────┘       └───────────────────────┘
               ▲                               ▲
               └───────────────┬───────────────┘
                               │
               ┌───────────────┴───────────────┐
               │    PaymentProviderRegistry    │
               │  [Automatic Mock Fallback]    │
               └───────────────────────────────┘
```

### Supported Provider Modes
1. **`MOCK` (Default):**
   - 100% in-memory deterministic simulation.
   - Zero network dependencies, zero credentials required.
   - Ideal for continuous integration tests, demo walkthroughs, and offline environments.
2. **`RAZORPAY_TEST`:**
   - Connects to official Razorpay REST APIs (`https://api.razorpay.com/v1`).
   - Requires valid `rzp_test_...` credentials.
   - **Automatic Fallback:** If credentials are missing, empty, or set to placeholder strings, the registry automatically falls back to `MockPaymentProvider` without crashing or interrupting operations.

---

## 2. Environment Variables & Security Constraints

Configure credentials in `.env` (or through process environment variables):

```ini
# Provider Mode ("MOCK" or "RAZORPAY_TEST")
PAYMENT_PROVIDER_MODE=MOCK

# Razorpay Test Mode Credentials (Backend Only - NEVER expose to frontend)
RAZORPAY_KEY_ID=rzp_test_placeholder_key
RAZORPAY_KEY_SECRET=rzp_test_placeholder_secret
RAZORPAY_WEBHOOK_SECRET=rzp_webhook_secret_placeholder
```

### Security Guardrails
* **No Live Credentials:** Any `key_id` beginning with `rzp_live_` is strictly rejected with a `ValueError`.
* **Zero Secret Leakage:** Neither `RAZORPAY_KEY_SECRET` nor `RAZORPAY_WEBHOOK_SECRET` are ever returned in API responses or serialized to client UIs. The `/api/payment-provider/status` endpoint provides only a masked identifier (e.g. `rzp_test_****`).

---

## 3. Webhook Handling (`POST /api/webhooks/razorpay`)

RevenueOS provides a production-grade webhook ingestion pipeline:

```
Incoming Webhook HTTP POST
  │
  ├── 1. Signature Verification (HMAC-SHA256 via X-Razorpay-Signature)
  │      └── Reject with HTTP 400 if invalid or missing
  │
  ├── 2. Idempotency Check (WebhookEvent.event_id query)
  │      └── If already processed, return HTTP 200 idempotent duplicate response
  │
  ├── 3. Database State Mutation:
  │      ├── payment.captured / payment.authorized ──> Payment marked SUCCESS; Opportunity marked RECOVERED
  │      ├── payment.failed ──────────────────────────> Payment marked FAILED; triggers Recovery Opportunity
  │      ├── payment_link.paid ───────────────────────> Opportunity marked RECOVERED with actual recovery value
  │      ├── subscription.charged ────────────────────> Subscription marked ACTIVE
  │      └── subscription.halted / cancelled ─────────> Subscription marked FAILED; triggers Recovery Opportunity
  │
  ├── 4. Audit Event Creation (Immutable AuditEvent recorded in database)
  │
  └── 5. Mark Event Processed (WebhookEvent.processed = True)
```

---

## 4. Demo Mode Switch Endpoints

Merchants and demo presenters can toggle provider modes dynamically at runtime:

### Inspect Active Mode
```http
GET /api/payment-provider/status
```
**Response:**
```json
{
  "requested_mode": "MOCK",
  "effective_provider": "mock",
  "is_razorpay_configured": false,
  "key_id_masked": null,
  "fallback_active": false,
  "available_modes": ["MOCK", "RAZORPAY_TEST"]
}
```

### Switch Mode
```http
POST /api/payment-provider/mode
Content-Type: application/json

{
  "mode": "RAZORPAY_TEST"
}
```
*(If Razorpay test keys are not configured, `effective_provider` will automatically remain `"mock"` with `fallback_active = true`)*.
