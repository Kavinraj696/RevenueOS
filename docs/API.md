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

### 4.3 Trigger Revenue Leak Detection
* **Method:** `POST`
* **Path:** `/api/v1/revenue-leaks/detect` (also `/api/revenue-leaks/detect`)
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Triggers the deterministic Stage 3 Revenue Leak Detection Engine across transaction streams for a specified merchant and analysis/baseline window.
* **Request:** `LeakDetectionRequest`
  ```json
  {
    "merchant_id": "11111111-1111-1111-1111-111111111111",
    "analysis_window_days": 14,
    "analysis_window_start": "2026-08-18T00:00:00Z",
    "analysis_window_end": "2026-09-01T12:00:00Z",
    "baseline_window_start": "2026-07-21T00:00:00Z",
    "baseline_window_end": "2026-08-18T00:00:00Z"
  }
  ```
* **Response (200 OK):** `LeakDetectionSummaryResponse`
  ```json
  {
    "status": "success",
    "merchant_id": "11111111-1111-1111-1111-111111111111",
    "detected_leaks_count": 2,
    "total_revenue_at_risk": 128450.00,
    "analysis_window": {
      "start": "2026-08-18T00:00:00Z",
      "end": "2026-09-01T12:00:00Z"
    },
    "baseline_window": {
      "start": "2026-07-21T00:00:00Z",
      "end": "2026-08-18T00:00:00Z"
    },
    "leaks": []
  }
  ```
* **Errors:** `404 Not Found` if merchant does not exist; `422 Unprocessable Entity` for invalid datetime or request formats.

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

---

## 16. AI Recovery Agent & Action Execution (Stage 5)

### 16.1 Start Agent Run
* **Method:** `POST`
* **Path:** `/api/agent/runs` and `/api/v1/agent/runs`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Triggers the 9-stage AI Recovery Agent workflow (`OBSERVE` $\rightarrow$ `REPORT`) for a specific merchant and leak or opportunity.
* **Request:**
  ```json
  {
    "merchant_id": "11111111-1111-1111-1111-111111111111",
    "trigger": "revenue_leak_detected",
    "leak_id": "99999999-9999-9999-9999-999999999999"
  }
  ```
* **Response (200 OK):** `AgentRunResponse` containing `agent_run_id`, `merchant_id`, `current_state`, `status`, `causal_trace_id`, `diagnostics`, `recommendation`, and `policy_verdict`.

### 16.2 Get Agent Run Details
* **Method:** `GET`
* **Path:** `/api/agent/runs/{id}` and `/api/v1/agent/runs/{id}`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Inspects real-time state, execution log, and structured reasoning summary for an agent run.
* **Response (200 OK):** `AgentRunResponse`

### 16.3 List Agent Runs
* **Method:** `GET`
* **Path:** `/api/agent/runs` and `/api/v1/agent/runs`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Lists all agent runs scoped to a merchant ID with optional state and status filters.

### 16.4 Approve Pending Action
* **Method:** `POST`
* **Path:** `/api/agent/runs/{id}/approve`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Human operator sign-off on an action held in `REQUIRE_APPROVAL` state.
* **Request:**
  ```json
  {
    "notes": "Approved by senior finance operations."
  }
  ```
* **Response (200 OK):** `ActionResponse` with updated status `EXECUTING` / `SUCCEEDED`.

### 16.5 Get Operational Agent Report
* **Method:** `GET`
* **Path:** `/api/agent/runs/{id}/report`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Returns the final structured operational recovery report detailing root cause, revenue at risk, policy breakdown, actual recovered revenue, and ROI.
* **Response (200 OK):** Structured JSON report separating estimated from actual verified metrics.

### 16.6 Inspect Recovery Action
* **Method:** `GET`
* **Path:** `/api/actions/{id}`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Fetches status, idempotency key, causal trace ID, and verification details of an individual recovery action.
* **Response (200 OK):** `RecoveryActionDetailResponse`

### 16.7 Trace Causality Timeline
* **Method:** `GET`
* **Path:** `/api/audit/{trace_id}` and `/api/audit/trace/{trace_id}`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Fetches the immutable chronological event sequence for an agent causal trace.
* **Response (200 OK):** List of audit events bound by `causal_trace_id`.

---

## 17. Razorpay Test Mode & Webhook Reconciliation APIs (Stage 6)

### 17.1 Ingest Razorpay Webhook
* **Method:** `POST`
* **Path:** `/api/v1/webhooks/razorpay` and `/api/webhooks/razorpay`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Real-time webhook ingestion from Razorpay Sandbox with HMAC-SHA256 signature verification and 1MB size limit.
* **Headers:** `X-Razorpay-Signature: <hmac-sha256-hex>`, `Content-Type: application/json`
* **Request Body:** Raw Razorpay webhook JSON payload (e.g. `payment.captured`, `payment.failed`, `payment_link.paid`).
* **Response (200 OK):**
  ```json
  {
    "status": "success",
    "event_id": "evt_rzp_987654321",
    "event_type": "payment.captured",
    "idempotent": false,
    "processing_status": "PROCESSED",
    "state_updated": true,
    "related_entity_type": "payment",
    "related_entity_id": "99999999-9999-9999-9999-999999999999",
    "recovery_triggered": false,
    "audit_event_id": "88888888-8888-8888-8888-888888888888",
    "processed_at": "2026-09-05T12:00:00Z"
  }
  ```
* **Duplicate Delivery Response (200 OK):**
  ```json
  {
    "status": "idempotent_duplicate",
    "event_id": "evt_rzp_987654321",
    "event_type": "payment.captured",
    "message": "Webhook event already processed previously. Zero duplicate mutations.",
    "idempotent": true,
    "processing_status": "DUPLICATE",
    "processed_at": "2026-09-05T12:00:00Z"
  }
  ```
* **Errors:** `400 Bad Request` if signature missing or invalid; `413 Request Entity Too Large` if payload exceeds 1MB.

### 17.2 List Ingested Webhook Events
* **Method:** `GET`
* **Path:** `/api/v1/webhooks/events`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Queries audit log of received webhook events with processing status, payload hash, and zero secret leakage.
* **Query Parameters:** `merchant_id` (optional), `event_type` (optional), `status` (optional), `limit` (default 50), `offset` (default 0).
* **Response (200 OK):** Array of webhook event summaries with masked payloads.

### 17.3 Inspect Webhook Event Detail
* **Method:** `GET`
* **Path:** `/api/v1/webhooks/events/{event_id}`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Inspects single webhook event status, received timestamp, and processing errors if any.
* **Response (200 OK):** Webhook event detail object.
* **Errors:** `404 Not Found` if event ID not found.

### 17.4 Reprocess Webhook Event
* **Method:** `POST`
* **Path:** `/api/v1/webhooks/events/{event_id}/reprocess`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Re-evaluates a previously received webhook event safely with idempotency protection.

### 17.5 Reconcile Payment (Independent Verification)
* **Method:** `POST`
* **Path:** `/api/v1/recovery/payments/{payment_id}/reconcile`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Performs independent financial reconciliation against provider state, verifying amount, currency, and settlement status. Transitions matching recovery actions to `VERIFIED` and marks recovery opportunities as `RECOVERED`.
* **Query Parameters:** `causal_trace_id` (optional string for audit linkage).
* **Response (200 OK):**
  ```json
  {
    "payment_id": "99999999-9999-9999-9999-999999999999",
    "reconciliation_status": "MATCHED",
    "verified": true,
    "actual_recovered_amount": 3500.00,
    "provider_payment_id": "pay_test_3500",
    "reconciled_at": "2026-09-05T12:05:00Z"
  }
  ```
* **Discrepancy Response (200 OK):**
  ```json
  {
    "payment_id": "99999999-9999-9999-9999-999999999999",
    "reconciliation_status": "RECONCILIATION_REQUIRED",
    "verified": false,
    "discrepancy": "amount_mismatch",
    "expected_amount": 1000.00,
    "provider_amount": 10000.00
  }
  ```

### 17.6 Inspect Payment Provider Status
* **Method:** `GET`
* **Path:** `/api/v1/payment-provider/status` and `/api/payment-provider/status`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Diagnostic health check confirming active provider mode (`razorpay_test` or `mock`), safety checks, and masked credentials.
* **Response (200 OK):**
  ```json
  {
    "requested_mode": "TEST",
    "effective_provider": "razorpay_test",
    "available_modes": ["MOCK", "TEST"],
    "key_id_masked": "rzp_test_****",
    "mode_enforced": "test",
    "is_sandboxed": true
  }
  ```

---

## 18. Stage 8 Business Validation, Metrics & Explainability APIs

### 18.1 Comprehensive Business Success Metrics
* **Method:** `GET`
* **Path:** `/api/v1/analytics/business-metrics`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Computes all 18 mandatory business success KPIs across Volume, Detection, ML, Policy, Execution, and Strict Financial Truth.
* **Query Parameters:** `merchant_id` (optional UUID filter).
* **Response (200 OK):**
  ```json
  {
    "total_transactions": 1420,
    "total_revenue": "4520000.00",
    "total_revenue_at_risk": "184500.00",
    "detected_revenue_leaks": 12,
    "recovery_opportunities": 8,
    "potential_recoverable_revenue": "122450.00",
    "approved_recoveries": 7,
    "executed_recoveries": 6,
    "verified_recoveries": 5,
    "actual_recovered_revenue": "28500.00",
    "recovery_rate": 28.5,
    "detection_rate": 96.2,
    "false_positive_rate": 4.1,
    "average_recovery_value": "5700.00",
    "average_time_to_recovery_seconds": 184.2,
    "policy_denial_rate": 12.5,
    "approval_rate": 87.5,
    "provider_success_rate": 94.0,
    "system_cost": "225.00",
    "net_recovered_revenue": "28275.00",
    "roi_multiplier": 125.7,
    "roi_percentage": 12570.0
  }
  ```

### 18.2 9-Stage Recovery Funnel
* **Method:** `GET`
* **Path:** `/api/v1/analytics/funnel`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Quantifies operational conversion through all 9 stages: Transactions $\to$ Potential Leaks $\to$ Confirmed Leaks $\to$ Recovery Opportunities $\to$ Recommended $\to$ Policy Allowed $\to$ Executed $\to$ Verified $\to$ Recovered Revenue.
* **Query Parameters:** `merchant_id` (optional UUID filter).
* **Response (200 OK):**
  ```json
  {
    "merchant_id": "00000000-0000-0000-0000-000000000000",
    "stages": [
      { "stage_number": 1, "stage_name": "Transactions Processed", "count": 1420, "volume": 4520000.0, "conversion_from_previous": 100.0 },
      { "stage_number": 2, "stage_name": "Potential Revenue Leaks", "count": 14, "volume": 210000.0, "conversion_from_previous": 4.6 },
      { "stage_number": 3, "stage_name": "Confirmed Revenue Leaks", "count": 12, "volume": 184500.0, "conversion_from_previous": 87.9 },
      { "stage_number": 4, "stage_name": "Recovery Opportunities", "count": 8, "volume": 122450.0, "conversion_from_previous": 66.4 },
      { "stage_number": 5, "stage_name": "Recommended Actions", "count": 8, "volume": 122450.0, "conversion_from_previous": 100.0 },
      { "stage_number": 6, "stage_name": "Policy Allowed Actions", "count": 7, "volume": 107450.0, "conversion_from_previous": 87.8 },
      { "stage_number": 7, "stage_name": "Executed Recoveries", "count": 6, "volume": 38450.0, "conversion_from_previous": 35.8 },
      { "stage_number": 8, "stage_name": "Verified Recoveries", "count": 5, "volume": 28500.0, "conversion_from_previous": 74.1 },
      { "stage_number": 9, "stage_name": "Actual Recovered Revenue", "count": 5, "volume": 28500.0, "conversion_from_previous": 100.0 }
    ],
    "overall_conversion_rate": 28.5
  }
  ```

### 18.3 Executive Business Impact Report
* **Method:** `GET`
* **Path:** `/api/v1/analytics/business-report`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Executive dossier containing Category Leakage Breakdown, ML Model Performance, Agent Performance, Policy Performance, and Latency Benchmarks.
* **Query Parameters:** `merchant_id` (optional UUID filter).

### 18.4 Deep 10-Question Diagnostic Explainability & Audit Trace
* **Method:** `GET`
* **Path:** `/api/v1/recovery-opportunities/{id}/explainability`
* **Status:** ✅ IMPLEMENTED
* **Purpose:** Returns complete auditable explainability including 10 diagnostic Q&As, structured AI rationale, deterministic policy rules evaluation, chronological timeline, and database causal audit IDs.
* **Response (200 OK):**
  ```json
  {
    "opportunity_id": "00000000-0000-0000-0000-000000000000",
    "diagnostic_qa": [
      { "question": "What happened to cause this transaction to fail?", "answer": "Transaction failed at gateway due to timeout on upi route with bank HDFC." },
      { "question": "Why was this flagged as a revenue leak?", "answer": "The failure pattern matched active leak cluster: UPI Route Degradation." }
    ],
    "ai_explanation": {
      "problem": "Transient gateway route timeout during high-traffic window.",
      "evidence": { "bank": "HDFC", "method": "upi", "error": "GATEWAY_TIMEOUT" },
      "diagnosis": "Customer payment behavior indicates strong intent; failure is infrastructure-transient.",
      "confidence": 0.91
    },
    "policy_explanation": {
      "verdict": "ALLOW",
      "allowed": true,
      "approval_required": false,
      "rules_evaluated": [
        { "rule_id": "RULE_1", "rule_name": "Maximum Transaction Value Cap", "status": "PASSED" }
      ]
    },
    "timeline": [
      { "timestamp": "2026-09-05T12:00:00Z", "event_type": "transaction_failed", "actor": "GATEWAY", "description": "Payment failed" }
    ],
    "audit_trace": {
      "opportunity_id": "...",
      "payment_id": "...",
      "action_id": "...",
      "policy_decision_id": "..."
    }
  }
  ```

---

## 19. Planned APIs (🔵 PLANNED)

The following APIs are planned for enterprise multi-tenant production:
* `POST /api/v1/auth/login` (OAuth2 / JWT merchant authentication).
* `POST /api/v1/auth/refresh` (Token refresh endpoint).
* `POST /api/v1/webhooks/subscriptions` (Dynamic merchant webhook URL registration).
* `GET /api/v1/merchants/{id}/policies/custom` (Custom merchant policy editor).

