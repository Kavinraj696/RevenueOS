# RevenueOS — Razorpay Revenue Recovery Intelligence Agent
## Full Pre-Implementation Blueprint

This document covers the nine deliverables required before writing any code:
architecture, repo structure, DB schema, API contract, agent workflow, ML
workflow, security model, demo scenarios, and implementation roadmap.

---

## 1. Final Architecture

### 1.1 System-level view

```
                         ┌─────────────────────────────┐
                         │        Next.js Frontend      │
                         │  Dashboard / Opportunity     │
                         │  Detail / Approval UI        │
                         └───────────────┬──────────────┘
                                         │ REST/JSON (HTTPS)
                         ┌───────────────▼──────────────┐
                         │        FastAPI Backend        │
                         │ ┌───────────────────────────┐│
                         │ │  API Layer (routers)      ││
                         │ ├───────────────────────────┤│
                         │ │  Revenue Leak Detection    ││
                         │ │  Engine                    ││
                         │ ├───────────────────────────┤│
                         │ │  Transaction Analytics     ││
                         │ ├───────────────────────────┤│
                         │ │  Recovery Probability      ││
                         │ │  Model (ML service)        ││
                         │ ├───────────────────────────┤│
                         │ │  Revenue-at-Risk Calculator││
                         │ ├───────────────────────────┤│
                         │ │  AI Agent Orchestrator     ││
                         │ │  (state machine / LangGraph││
                         │ │   + Tool Layer)            ││
                         │ ├───────────────────────────┤│
                         │ │  Policy / Governance Engine││
                         │ │  (deterministic, no LLM)   ││
                         │ ├───────────────────────────┤│
                         │ │  Recovery Execution Engine ││
                         │ ├───────────────────────────┤│
                         │ │  Webhook/Event Processor   ││
                         │ ├───────────────────────────┤│
                         │ │  Audit Trail Writer        ││
                         │ ├───────────────────────────┤│
                         │ │  ROI Analytics             ││
                         │ ├───────────────────────────┤│
                         │ │  Synthetic Data Generator  ││
                         │ └───────────────────────────┘│
                         └───────┬───────────────┬───────┘
                                 │               │
                     ┌───────────▼───┐   ┌───────▼─────────────┐
                     │  PostgreSQL    │   │ Payment Provider     │
                     │  (all state)   │   │ Adapter              │
                     └────────────────┘   │  RazorpayTestProvider│
                                          │  MockPaymentProvider │
                                          └──────────┬───────────┘
                                                     │
                                          ┌──────────▼───────────┐
                                          │ Razorpay Test Mode API│
                                          │ + Webhooks            │
                                          └────────────────────────┘
```

### 1.2 Design principles

- **Separation of cognition and execution.** The LLM (agent) only reasons,
  calls tools, and proposes actions. It never touches the database or the
  payment provider directly. Every proposed action passes through the
  deterministic Policy Engine, which is plain Python logic — testable,
  auditable, and immune to prompt injection or hallucination.
- **Everything traceable.** Every number shown on the dashboard must trace
  back to a row in Postgres, and every action must trace back to an
  `AgentDecision` + `PolicyDecision` + `AuditEvent` chain.
- **Provider-agnostic core.** The core domain logic never calls Razorpay
  directly — it calls a `PaymentProvider` interface, so demo mode
  (`MockPaymentProvider`) and real test mode (`RazorpayTestProvider`) are
  interchangeable at runtime via an environment flag.
- **Explainability over cleverness.** Every ML prediction returns a
  probability + the top contributing features, not just a number.

### 1.3 Layered internal architecture (backend)

1. **API layer** — FastAPI routers, Pydantic request/response schemas, auth.
2. **Service layer** — business logic (leak detection, RAR calculator, ROI).
3. **Agent layer** — orchestration graph + tool implementations.
4. **Policy layer** — pure functions, no I/O side effects except audit log.
5. **Data access layer** — SQLAlchemy models + repositories.
6. **Integration layer** — payment provider adapters, webhook verification.
7. **ML layer** — trained models loaded at startup, served via an internal
   prediction API used by both the service layer and the agent's tools.

---

## 2. Repository Structure

```
revenueos/
├── docker-compose.yml
├── .env.example
├── README.md
├── ARCHITECTURE.md
├── API.md
├── AI_AGENT.md
├── ML.md
├── SECURITY.md
├── DEMO.md
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic/                     # DB migrations
│   │   └── versions/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py                 # env vars, settings
│   │   ├── db/
│   │   │   ├── session.py
│   │   │   └── base.py
│   │   ├── models/                   # SQLAlchemy models (one file per entity)
│   │   │   ├── merchant.py
│   │   │   ├── customer.py
│   │   │   ├── payment.py
│   │   │   ├── payment_attempt.py
│   │   │   ├── subscription.py
│   │   │   ├── checkout_session.py
│   │   │   ├── revenue_leak.py
│   │   │   ├── recovery_opportunity.py
│   │   │   ├── recovery_action.py
│   │   │   ├── agent_decision.py
│   │   │   ├── policy_decision.py
│   │   │   ├── audit_event.py
│   │   │   ├── webhook_event.py
│   │   │   ├── experiment.py
│   │   │   └── model_prediction.py
│   │   ├── schemas/                  # Pydantic DTOs
│   │   ├── api/
│   │   │   ├── deps.py
│   │   │   └── v1/
│   │   │       ├── merchants.py
│   │   │       ├── dashboard.py
│   │   │       ├── leaks.py
│   │   │       ├── opportunities.py
│   │   │       ├── agent.py
│   │   │       ├── actions.py
│   │   │       ├── webhooks.py
│   │   │       ├── roi.py
│   │   │       └── demo.py
│   │   ├── services/
│   │   │   ├── leak_detection.py
│   │   │   ├── transaction_analytics.py
│   │   │   ├── revenue_at_risk.py
│   │   │   ├── roi.py
│   │   │   └── audit.py
│   │   ├── agent/
│   │   │   ├── graph.py              # LangGraph / state machine definition
│   │   │   ├── state.py              # AgentState schema
│   │   │   ├── prompts.py
│   │   │   └── tools/
│   │   │       ├── transaction_tools.py
│   │   │       ├── analytics_tools.py
│   │   │       ├── recovery_tools.py
│   │   │       └── reporting_tools.py
│   │   ├── policy/
│   │   │   ├── engine.py
│   │   │   └── rules.py
│   │   ├── providers/
│   │   │   ├── base.py               # PaymentProvider interface
│   │   │   ├── razorpay_test.py
│   │   │   └── mock_provider.py
│   │   ├── ml/
│   │   │   ├── features.py
│   │   │   ├── train_failure_model.py
│   │   │   ├── train_anomaly_model.py
│   │   │   ├── train_recovery_model.py
│   │   │   ├── predict.py
│   │   │   └── registry/             # saved model artifacts + version.json
│   │   ├── synthetic/
│   │   │   ├── generator.py
│   │   │   └── scenarios.py          # Scenario A–E definitions
│   │   └── core/
│   │       ├── security.py
│   │       ├── idempotency.py
│   │       └── logging.py
│   └── tests/
│       ├── unit/
│       ├── api/
│       ├── agent/
│       ├── policy/
│       ├── webhooks/
│       └── e2e/
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── next.config.js
│   ├── tailwind.config.ts
│   └── src/
│       ├── app/
│       │   ├── page.tsx                      # main dashboard
│       │   ├── opportunities/[id]/page.tsx
│       │   └── layout.tsx
│       ├── components/
│       │   ├── dashboard/
│       │   ├── priority-queue/
│       │   ├── opportunity-detail/
│       │   ├── audit-timeline/
│       │   └── roi/
│       ├── lib/
│       │   └── api-client.ts
│       └── types/
│
└── infra/
    └── seed/                          # scenario seed scripts invoked at startup
```

---

## 3. Database Schema

Below is the entity design (PostgreSQL, SQLAlchemy). Types are indicative;
adjust precision as needed. All monetary columns use `NUMERIC(14,2)` in the
merchant's currency (assume INR, paise-safe by storing rupees as decimal).

**merchants**
`id (uuid pk)`, `name`, `email`, `created_at`, `settings_json` (policy overrides, currency)

**customers**
`id (uuid pk)`, `merchant_id (fk)`, `external_ref` (synthetic ID, never real PII), `risk_segment`, `lifetime_value`, `created_at`

**payments**
`id (uuid pk)`, `merchant_id (fk)`, `customer_id (fk)`, `amount`, `currency`, `status` (success/failed/pending/recovered), `payment_method`, `bank`, `device_type`, `created_at`, `route`

**payment_attempts**
`id (uuid pk)`, `payment_id (fk)`, `attempt_number`, `status`, `failure_reason`, `error_code`, `attempted_at`

**subscriptions**
`id (uuid pk)`, `merchant_id (fk)`, `customer_id (fk)`, `plan_amount`, `billing_cycle`, `status` (active/paused/failed/cancelled), `created_at`

**subscription_attempts**
`id (uuid pk)`, `subscription_id (fk)`, `status`, `failure_reason`, `attempted_at`

**checkout_sessions**
`id (uuid pk)`, `merchant_id (fk)`, `customer_id (fk, nullable)`, `cart_value`, `status` (completed/abandoned), `stage_dropped` (e.g. otp/payment_method_select), `created_at`

**revenue_leaks**
`id (uuid pk)`, `merchant_id (fk)`, `leak_type` (payment_failure/checkout_abandonment/subscription_failure/anomaly), `pattern_description`, `gross_value_affected`, `detection_window_start`, `detection_window_end`, `severity_score`, `created_at`

**recovery_opportunities**
`id (uuid pk)`, `revenue_leak_id (fk)`, `merchant_id (fk)`, `customer_id (fk, nullable)`, `gross_value_affected`, `potentially_recoverable_value`, `recovery_probability`, `expected_recovered_value`, `actual_recovered_value (nullable)`, `status` (open/investigating/action_selected/pending_approval/executing/recovered/failed/dismissed), `priority_score`, `created_at`, `updated_at`

**recovery_actions**
`id (uuid pk)`, `opportunity_id (fk)`, `action_type` (retry/payment_link/notification/alt_method/subscription_workflow/escalate/no_action), `reason`, `predicted_outcome`, `policy_decision_id (fk)`, `execution_result` (nullable json), `status` (proposed/approved/executed/succeeded/failed/blocked), `created_at`, `executed_at`

**agent_decisions**
`id (uuid pk)`, `opportunity_id (fk)`, `problem`, `evidence_json`, `estimated_impact`, `recovery_probability`, `recommended_action`, `reason`, `risk_level`, `expected_recovery`, `actual_recovery (nullable)`, `created_at`

**policy_decisions**
`id (uuid pk)`, `agent_decision_id (fk)`, `action_type`, `allowed (bool)`, `approval_required (bool)`, `max_amount_allowed`, `retry_limit`, `cooldown_seconds`, `confidence_threshold`, `decision_reason`, `created_at`

**audit_events**
`id (uuid pk)`, `merchant_id (fk)`, `related_entity_type`, `related_entity_id`, `event_type`, `message`, `request_id`, `agent_decision_id (nullable fk)`, `action_id (nullable fk)`, `created_at`

**webhook_events**
`id (uuid pk)`, `provider`, `event_id` (external, unique — idempotency key), `event_type`, `raw_payload_json`, `signature_verified (bool)`, `processed (bool)`, `received_at`, `processed_at`

**experiments**
`id (uuid pk)`, `name`, `hypothesis`, `scenario`, `started_at`, `ended_at`, `result_summary`

**model_predictions**
`id (uuid pk)`, `model_name`, `model_version`, `entity_type`, `entity_id`, `input_features_json`, `prediction`, `confidence`, `created_at`

Indexes: `merchant_id` on every merchant-scoped table; `status` on
`recovery_opportunities` and `recovery_actions`; unique constraint on
`webhook_events.event_id` for idempotency.

---

## 4. API Contract (v1, illustrative)

Auth: bearer token per merchant (demo mode uses a fixed dev token).

```
GET   /api/v1/merchants                       list demo merchants
GET   /api/v1/merchants/{id}/dashboard        summary metrics (processed,
                                               at-risk, recoverable, recovered,
                                               recovery rate, leak breakdown)

GET   /api/v1/merchants/{id}/leaks            list revenue_leaks
GET   /api/v1/leaks/{leak_id}                 leak detail + linked opportunities

GET   /api/v1/merchants/{id}/opportunities    priority queue (sorted by
                                               priority_score)
GET   /api/v1/opportunities/{id}              full detail incl. agent_decisions,
                                               recovery_actions, audit trail

POST  /api/v1/opportunities/{id}/investigate  triggers agent OBSERVE→DIAGNOSE
                                               run, returns AgentDecision
POST  /api/v1/opportunities/{id}/approve      merchant approves a
                                               pending_approval action
POST  /api/v1/opportunities/{id}/reject       merchant rejects it

POST  /api/v1/actions/{action_id}/execute     executes an approved/auto action
GET   /api/v1/actions/{action_id}             action status + execution_result

GET   /api/v1/merchants/{id}/audit            audit timeline (paginated)
GET   /api/v1/merchants/{id}/roi              before/after ROI analytics

POST  /api/v1/webhooks/razorpay               signature-verified webhook intake

POST  /api/v1/demo/scenario                   { "scenario": "B" } — switches
                                               active synthetic dataset
GET   /api/v1/demo/scenarios                  list available scenarios

GET   /api/v1/ml/models                       model registry: name, version,
                                               metrics
```

Every response includes `request_id`. Mutating endpoints (`execute`,
`approve`) require an `Idempotency-Key` header.

---

## 5. Agent Workflow

### 5.1 State machine

```
OBSERVE → INVESTIGATE → DIAGNOSE → QUANTIFY → SELECT_ACTION
        → POLICY_CHECK → EXECUTE_OR_REQUEST_APPROVAL → VERIFY → REPORT
```

- **OBSERVE**: reads the triggering `RevenueLeak`/`RecoveryOpportunity`.
- **INVESTIGATE**: calls `get_transaction_history`, `search_transactions`,
  `get_customer_history`, `get_payment_failure_analysis` to gather evidence.
- **DIAGNOSE**: LLM synthesizes evidence into a root-cause hypothesis
  (e.g. "62% of failures on route X, correlated with bank Y outage window").
- **QUANTIFY**: calls `estimate_recoverable_revenue` and
  `calculate_recovery_probability` (these call the ML prediction API, not
  the LLM — numbers must come from the model, not be invented).
- **SELECT_ACTION**: LLM picks from the bounded action set via
  `recommend_recovery_action`, with a `reason`.
- **POLICY_CHECK**: deterministic Python — the LLM's proposed action is
  passed to the Policy Engine, which returns allow/deny/approval-required
  plus constraints (max amount, cooldown, retry limit).
- **EXECUTE_OR_REQUEST_APPROVAL**: if auto-allowed, calls
  `execute_allowed_recovery_action`; otherwise creates a pending approval
  and stops, waiting for a merchant decision via the API.
- **VERIFY**: after execution (or after a webhook confirms payment),
  `get_recovery_result` checks actual outcome and records
  `actual_recovered_value`.
- **REPORT**: `generate_merchant_report` produces the user-facing summary
  fields (`problem`, `evidence`, `recommended_action`, `expected_recovery`,
  `actual_recovery`) — this is the only agent output surfaced to the UI.
  No raw chain-of-thought is exposed.

### 5.2 Tool layer contract

Each tool is a typed Python function with a Pydantic input/output schema,
registered with the LLM via tool-calling. Tools that read data hit the
service layer; tools that act (`execute_allowed_recovery_action`,
`create_test_payment_link`, `send_recovery_notification`) go through the
Policy Engine first — even if the agent "forgets" to call `POLICY_CHECK",
the execution tool itself refuses to run without a passing
`PolicyDecision` row. This makes the safety boundary structural, not just
prompt-based.

---

## 6. ML Workflow

Three models, each with its own pipeline:

**Model 1 — Payment failure/recovery prediction** (binary classification:
will this failed payment be recoverable if retried/actioned?)
Features: payment method, bank, device, hour-of-day, amount bucket,
customer failure history, retry count. Metrics: Precision, Recall, F1,
ROC-AUC against a held-out synthetic test set.

**Model 2 — Revenue anomaly detection** (unsupervised or statistical:
detect abnormal failure-rate spikes per route/bank/hour vs. baseline).
Method: rolling baseline + z-score or isolation forest on aggregated
time-bucketed failure rates. Metrics: precision/recall against injected
synthetic anomalies (since ground truth is generated, this is knowable).

**Model 3 — Recovery probability estimation** (regression/probability
output feeding `calculate_recovery_probability`). Features similar to
Model 1 plus proposed action type. Metrics: Brier score / MAE / ROC-AUC
depending on framing.

Common pipeline: `synthetic/generator.py` produces train+test splits →
`ml/features.py` builds feature vectors → `ml/train_*.py` scripts fit
scikit-learn models, compute real metrics on the test split, compare
against a naive baseline (e.g. majority class / historical average), and
write `{model, metrics, version, trained_at}` into
`ml/registry/`. `ml/predict.py` loads the current registry version at
startup and exposes a prediction function used by both the service layer
and the agent's tools. Every prediction is logged to `model_predictions`
for traceability.

---

## 7. Security Model

- **Secrets**: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`,
  `RAZORPAY_WEBHOOK_SECRET` live only in backend environment variables,
  never sent to the frontend, never logged.
- **Webhook verification**: every inbound webhook's signature is verified
  against `RAZORPAY_WEBHOOK_SECRET` before the payload is trusted; raw
  payloads are stored in `webhook_events` regardless, for audit purposes,
  but `processed=false` until verified.
- **Idempotency**: `webhook_events.event_id` is unique; mutating financial
  endpoints require an `Idempotency-Key` header stored against the action
  row, so retried requests don't double-execute.
- **Policy boundary**: the LLM has no direct DB or payment-provider
  access — only through tools, and action-executing tools hard-require a
  passing `PolicyDecision`.
- **Action limits**: the Policy Engine enforces max amount, retry count,
  and cooldown period per customer/action-type, independent of what the
  LLM requests.
- **Data**: no real customer PII — synthetic `external_ref` identifiers
  only, consistent with a demo/test-mode system.
- **Input validation**: all API inputs validated via Pydantic schemas;
  authorization is role-aware (merchant-scoped access checks on every
  query).
- **Least privilege UI**: frontend never receives secret keys or raw
  webhook payloads — only sanitized DTOs.

---

## 8. Demo Scenarios

Deterministic synthetic datasets, selectable via `POST /demo/scenario`:

- **A — Normal merchant**: healthy baseline, low failure rate, mostly
  successful payments, minimal leaks — establishes what "normal" looks
  like for contrast.
- **B — UPI/payment-method degradation**: a spike in failures concentrated
  on one payment method/bank, moderate-value impact, high recovery
  probability via alternative method — good for showing pattern detection.
- **C — High-value checkout abandonment**: fewer events but large cart
  values dropped near payment step — showcases the abandonment leak type
  and a payment-link recovery action.
- **D — Subscription failure spike**: recurring billing failures
  clustering around a billing date/bank — showcases the subscription
  recovery workflow action.
- **E — Successful recovery campaign**: a fully played-out story where
  detection → diagnosis → policy-approved action → execution → webhook
  confirms payment → ROI updates — the "happy path" for the live demo.

Each scenario seeds `payments`, `payment_attempts`, `subscriptions`,
`checkout_sessions` with enough volume and pattern structure for the leak
detection engine and ML models to surface real (not scripted) findings.

---

## 9. Implementation Roadmap

**Stage 0 — Foundations**
Repo scaffold, Docker Compose (Postgres + backend + frontend), env config,
Alembic migrations for all entities, base FastAPI app with health check,
base Next.js app with empty dashboard shell.

**Stage 1 — Data & Synthetic Generation**
Implement all SQLAlchemy models, synthetic data generator, Scenarios A–E,
seed script wired to `docker compose up`.

**Stage 2 — Analytics Core**
Transaction Analytics Engine, Revenue Leak Detection Engine, Revenue-at-Risk
Calculator, dashboard summary + leak endpoints, first dashboard UI pass.

**Stage 3 — ML Layer**
Feature pipeline, train all three models on synthetic data, real metrics,
baseline comparisons, prediction API, model registry.

**Stage 4 — Policy Engine**
Deterministic rules for each action type, unit tests covering allow/deny/
approval-required/blocked paths, `PolicyDecision` persistence.

**Stage 5 — Agent + Tool Layer**
State machine/LangGraph implementation, all tools wired to services/ML/
policy, `AgentDecision` persistence, `/investigate` endpoint.

**Stage 6 — Recovery Execution + Providers**
`PaymentProvider` interface, `MockPaymentProvider`,
`RazorpayTestProvider`, action execution engine, webhook processor with
signature verification and idempotency.

**Stage 7 — Audit, Approval Flow, ROI**
Audit event writer wired into every stage above, approve/reject endpoints,
ROI analytics (before/after), audit timeline UI, ROI UI.

**Stage 8 — Frontend Completion**
Full dashboard (metrics, leak breakdown, priority queue, opportunity
detail, audit timeline, ROI section), scenario switcher, approval modal.

**Stage 9 — Testing & Hardening**
Unit, API, agent-tool, policy-engine, webhook tests; end-to-end scenario
test scripted through the full demo story; security review pass.

**Stage 10 — Documentation & Demo Polish**
README with exact `docker compose up` instructions, ARCHITECTURE.md,
API.md, AI_AGENT.md, ML.md, SECURITY.md, DEMO.md; rehearse the 14-step
judge walkthrough end-to-end.

At the end of every stage, `docker compose up` must still bring up a
working application — no stage should leave the system broken.
