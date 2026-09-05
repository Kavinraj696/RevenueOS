# RevenueOS — API Specification

This document details all API endpoints that **actually exist** in the RevenueOS backend codebase (`backend/app/api/v1/` and `backend/app/main.py`), including HTTP method, path, purpose, request parameters, response schemas, error responses, authentication mechanisms, and implementation status.

---

## 1. System & Root Endpoints

### 1.1 Health Check
* **Method:** `GET`
* **Path:** `/health` and `/api/v1/health`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Heartbeat endpoint for liveness probes and uptime monitors.
* **Request:** None
* **Response (200 OK):**
  ```json
  {
    "status": "healthy",
    "service": "RevenueOS",
    "environment": "development",
    "database": "connected"
  }
  ```
* **Errors (503 Service Unavailable):**
  ```json
  {
    "status": "unhealthy",
    "service": "RevenueOS",
    "environment": "development",
    "database": "disconnected",
    "error": "Database connectivity check failed"
  }
  ```

### 1.2 Dashboard UI
* **Method:** `GET`
* **Path:** `/` and `/dashboard`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Serves the primary merchant operations fintech dashboard UI.
* **Request:** None
* **Response (200 OK):** `text/html` (Contains complete 8-page operations console)

### 1.3 Audit UI
* **Method:** `GET`
* **Path:** `/audit`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Serves the interactive standalone Audit Timeline and Causality Graph interface.
* **Request:** None
* **Response (200 OK):** `text/html`

---

## 2. Merchants & Organization Context

### 2.1 List Merchants
* **Method:** `GET`
* **Path:** `/api/v1/merchants`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** List all configured merchants in the system.
* **Request:** None
* **Response (200 OK):** `List[MerchantResponse]`
  ```json
  [
    {
      "id": "11111111-1111-1111-1111-111111111111",
      "name": "Apex Electronics Ltd",
      "email": "finance@apexelectronics.in",
      "created_at": "2026-09-01T00:00:00Z",
      "settings_json": {}
    }
  ]
  ```

### 2.2 Get Merchant
* **Method:** `GET`
* **Path:** `/api/v1/merchants/{merchant_id}`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Retrieve details for a specific merchant.
* **Request:** Path parameter `merchant_id` (UUID)
* **Response (200 OK):** `MerchantResponse`
* **Errors:** `404 Not Found` if merchant does not exist.

### 2.3 Get Merchant Summary
* **Method:** `GET`
* **Path:** `/api/v1/merchants/{merchant_id}/summary`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Aggregated counts of transactions, customers, active leaks, and open opportunities.
* **Response (200 OK):** `MerchantSummaryResponse`

---

## 3. Transactions, Subscriptions & Checkout Sessions

### 3.1 List Transactions
* **Method:** `GET`
* **Path:** `/api/v1/merchants/{merchant_id}/transactions`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Paginated list of transactions with status, amount, and payment attempt details.
* **Query Parameters:** `page` (default 1), `page_size` (default 20), `status` (optional filter).
* **Response (200 OK):** `PaginatedPaymentsResponse`

### 3.2 List Payment Failures
* **Method:** `GET`
* **Path:** `/api/v1/merchants/{merchant_id}/failures`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** List recent payment failures including gateway error codes and attempt sequences.
* **Response (200 OK):** `List[PaymentFailureResponse]`

### 3.3 List Subscriptions
* **Method:** `GET`
* **Path:** `/api/v1/merchants/{merchant_id}/subscriptions`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Paginated view of recurring billing plans, statuses, and retry attempts.
* **Response (200 OK):** `PaginatedSubscriptionsResponse`

### 3.4 List Checkout Sessions
* **Method:** `GET`
* **Path:** `/api/v1/merchants/{merchant_id}/checkout-sessions`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** List customer checkout sessions and drop-off stages (e.g. `otp_verification`).
* **Response (200 OK):** `PaginatedCheckoutSessionsResponse`

---

## 4. Revenue Leaks

### 4.1 List Revenue Leaks
* **Method:** `GET`
* **Path:** `/api/v1/revenue-leaks` (also `/api/v1/leaks`)
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Retrieve detected revenue leak patterns (payment failure surges, cart abandonment, mandate drops).
* **Query Parameters:** `merchant_id` (optional), `status` (optional, default `open`).
* **Response (200 OK):** `List[RevenueLeakResponse]`
  ```json
  [
    {
      "id": "c1f72b9a-4c2f-48d9-bf12-421731671982",
      "merchant_id": "11111111-1111-1111-1111-111111111111",
      "leak_type": "payment_failure",
      "pattern_description": "UPI degradation on HDFC Bank route",
      "affected_amount": 48500.00,
      "revenue_at_risk": 48500.00,
      "currency": "INR",
      "severity": "high",
      "severity_score": 8.50,
      "confidence": 0.9400,
      "status": "open",
      "root_cause_candidates": ["HDFC Gateway Timeout", "Device network disconnect"],
      "created_at": "2026-09-05T10:00:00Z"
    }
  ]
  ```

### 4.2 Get Revenue Leak Detail
* **Method:** `GET`
* **Path:** `/api/v1/revenue-leaks/{leak_id}`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Detailed diagnostic data for a specific leak pattern.
* **Response (200 OK):** `RevenueLeakResponse`
* **Errors:** `404 Not Found` if leak does not exist.

---

## 5. Recovery Opportunities (Priority Queue)

### 5.1 List Recovery Opportunities
* **Method:** `GET`
* **Path:** `/api/v1/recovery-opportunities`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Priority queue of addressable failures sorted by Expected Recovered Value.
* **Query Parameters:** `merchant_id` (optional), `status` (optional), `limit` (default 50).
* **Response (200 OK):** `RecoveryOpportunitiesListResponse`

### 5.2 Get Opportunity Detail
* **Method:** `GET`
* **Path:** `/api/v1/recovery-opportunities/{id}`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Opportunity investigation drawer with customer history, attempts, and agent decisions.
* **Response (200 OK):** `RecoveryOpportunityResponse`
* **Errors:** `404 Not Found` if opportunity does not exist.

---

## 6. AI Recovery Agent

### 6.1 Autonomous Opportunity Investigation
* **Method:** `POST`
* **Path:** `/api/v1/agent/investigate`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Triggers the 9-stage recovery state machine (`OBSERVE` to `REPORT`) on a target leak/opportunity.
* **Request:**
  ```json
  {
    "merchant_id": "11111111-1111-1111-1111-111111111111",
    "leak_id": "optional-leak-uuid",
    "opportunity_id": "optional-opportunity-uuid",
    "auto_execute": true
  }
  ```
* **Response (200 OK):** `AgentInvestigationResponse` (contains problem, evidence, recommended action, policy verdict, telemetry execution logs).

### 6.2 Conversational Investigation Chat
* **Method:** `POST`
* **Path:** `/api/v1/agent/chat`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Interactive conversational chat interface explaining revenue changes and diagnosing failure spikes with grounded evidence cards.
* **Request:**
  ```json
  {
    "merchant_id": "11111111-1111-1111-1111-111111111111",
    "message": "Why did revenue drop yesterday?"
  }
  ```
* **Response (200 OK):** `AgentChatResponse` (includes assistant message, structured evidence card, telemetry logs, and suggestions).

### 6.3 List Agent Decisions
* **Method:** `GET`
* **Path:** `/api/v1/agent/decisions`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Retrieve persisted decisions made by the AI Recovery Agent.
* **Response (200 OK):** `AgentDecisionsListResponse`

---

## 7. Financial Action Policy Engine

### 7.1 Evaluate Proposed Action
* **Method:** `POST`
* **Path:** `/api/v1/policy/evaluate`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Deterministically evaluates a proposed financial recovery action against risk policies.
* **Request:** `PolicyEvaluationRequest` (action, amount, confidence, previous attempts, VIP status).
* **Response (200 OK):** `PolicyDecisionResponse` (`allowed: bool`, `approval_required: bool`, `reason: str`).

### 7.2 Get Active Policy Limits
* **Method:** `GET`
* **Path:** `/api/v1/policy/limits`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Returns active financial governance constraints (₹15k auto ceiling, 3 retries/24h, 4h cooldown).
* **Response (200 OK):** `PolicyLimitsConfig`

### 7.3 Get Audit Rules
* **Method:** `GET`
* **Path:** `/api/v1/policy/audit-rules`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Returns all active policy rule descriptions and rationale.

---

## 8. Recovery Execution Pipeline

### 8.1 Execute Recovery Pipeline
* **Method:** `POST`
* **Path:** `/api/v1/recovery/execute`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Runs end-to-end pipeline: Policy evaluation $\to$ Action execution $\to$ Audit logging.
* **Headers:** `Idempotency-Key` (recommended)
* **Response (200 OK):** `RecoveryPipelineExecutionResponse`

### 8.2 Execute Opportunity Action
* **Method:** `POST`
* **Path:** `/api/v1/recovery/opportunities/{id}/execute`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Execute the selected recovery action for an opportunity.
* **Response (200 OK):** `RecoveryPipelineExecutionResponse`

### 8.3 Approve Pending Action
* **Method:** `POST`
* **Path:** `/api/v1/recovery/actions/{id}/approve`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Merchant operations sign-off for actions requiring approval ($> \text{₹}15,000$).
* **Response (200 OK):** `RecoveryActionResponse`

### 8.4 Retry Failed Recovery Action
* **Method:** `POST`
* **Path:** `/api/v1/recovery/actions/{id}/retry`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Triggers a safe retry of a failed recovery action subject to policy limits.
* **Response (200 OK):** `RecoveryActionResponse`

### 8.5 List Recovery Actions
* **Method:** `GET`
* **Path:** `/api/v1/recovery/actions`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** List executed and proposed recovery actions across opportunities.
* **Response (200 OK):** `RecoveryActionListResponse`

---

## 9. Webhooks (Inbound Razorpay Events)

### 9.1 Ingest Webhook
* **Method:** `POST`
* **Path:** `/api/v1/webhooks/razorpay` (and `/api/webhooks/razorpay`)
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Ingests external webhook callbacks from Razorpay with HMAC-SHA256 signature verification and idempotency protection.
* **Headers:** `X-Razorpay-Signature` (HMAC hex digest)
* **Events Handled:** `payment.captured`, `payment.authorized`, `payment.failed`, `subscription.charged`, `payment_link.paid`.
* **Response (200 OK):**
  ```json
  {
    "status": "success",
    "event_id": "evt_01J6M78X9A...",
    "idempotent": false,
    "state_updated": true,
    "related_entity_type": "payment"
  }
  ```
* **Errors:** `400 Bad Request` if signature missing or invalid.

---

## 10. Payment Providers & Integration

### 10.1 Provider Status
* **Method:** `GET`
* **Path:** `/api/v1/payment-provider/status`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Returns active provider mode (`MOCK` or `RAZORPAY_TEST`), credentials masking, and fallback status.

### 10.2 Toggle Provider Mode
* **Method:** `POST`
* **Path:** `/api/v1/payment-provider/toggle` (also `/api/payment-provider/mode`)
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Dynamically toggle between mock mode and official Razorpay test mode.

### 10.3 Create Payment Link Direct
* **Method:** `POST`
* **Path:** `/api/v1/payment-provider/create-link`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Direct endpoint for payment link generation via active provider adapter.

---

## 11. Audit System

### 11.1 Query Audit Ledger
* **Method:** `GET`
* **Path:** `/api/v1/audit`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Query immutable operational audit events with filtering and pagination.
* **Query Parameters:** `merchant_id`, `event_type`, `related_entity_type`, `limit` (default 50), `offset`.
* **Response (200 OK):** `AuditEventListResponse`

### 11.2 Action Causality Timeline
* **Method:** `GET`
* **Path:** `/api/v1/audit/timeline/{action_id}`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Reconstructs the complete causality trace for a recovery action.
* **Response (200 OK):** `ActionCausalityTimelineResponse`

---

## 12. Analytics & ROI

### 12.1 Overview Analytics & KPIs
* **Method:** `GET`
* **Path:** `/api/v1/analytics/overview`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Computes real-time gross processed volume, revenue at risk, potentially recoverable volume, recovered revenue, recovery rate %, and chart time-series datasets.
* **Response (200 OK):** `OverviewAnalyticsResponse`

### 12.2 Before vs. After ROI Impact
* **Method:** `GET`
* **Path:** `/api/v1/analytics/roi`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Institutional Before vs. After RevenueOS analysis: recovery rate lift, net recovered INR, manual hours saved, automation rate.
* **Response (200 OK):** `RoiAnalyticsResponse`

---

## 13. Machine Learning & Model Registry

### 13.1 Predict Recovery Probability
* **Method:** `GET`
* **Path:** `/api/v1/ml/recovery-probability/{transaction_id}`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Real-time ML inference estimating recoverability probability $P_{\text{rec}} \in [0, 1]$ and top contributing feature importances.
* **Response (200 OK):** `RecoveryProbabilityResponse`

### 13.2 ML Metrics & Benchmarks
* **Method:** `GET`
* **Path:** `/api/v1/ml/metrics`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Returns model performance metrics (ROC-AUC, Precision, Recall, F1) comparing baseline vs RevenueOS models.

---

## 14. Evaluation & Benchmarking

### 14.1 Run Evaluation
* **Method:** `POST`
* **Path:** `/api/v1/evaluation/run`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Executes evaluation framework comparing baseline heuristic recovery against RevenueOS across held-out test data.

### 14.2 Get Evaluation Report
* **Method:** `GET`
* **Path:** `/api/v1/evaluation/report`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Returns complete evaluation report artifact with confusion matrices and business metrics.

---

## 15. Security & Demo Scenarios

### 15.1 Security Status & Evaluation
* **Method:** `GET` `/api/v1/security/status` and `POST` `/api/v1/security/run-audit`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Runs 7 HIGH severity security checks (prompt injection detection, tool restrictions, amount caps, webhook verification).

### 15.2 Demo Scenarios Management
* **Method:** `GET` `/api/v1/demo/scenarios`, `POST` `/api/v1/demo/scenarios/run/{scenario_id}`, `POST` `/api/v1/demo/reset`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Switches between Scenarios 1–5 (Gateway Degradation, Checkout Abandonment, Subscriptions, Recovery Failure, Safety Guardrail Verification).

---

## 16. Planned APIs (🔵 PLANNED)

The following APIs are planned for enterprise multi-tenant production:
* `POST /api/v1/auth/login` (OAuth2 / JWT merchant authentication).
* `POST /api/v1/auth/refresh` (Token refresh endpoint).
* `POST /api/v1/webhooks/subscriptions` (Dynamic merchant webhook URL registration).
* `GET /api/v1/merchants/{id}/policies/custom` (Custom merchant policy editor).
