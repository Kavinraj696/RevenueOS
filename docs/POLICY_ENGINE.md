# RevenueOS — Deterministic Policy Engine Specification

## 1. Executive Summary & Core Principle

In RevenueOS, **the AI Agent is non-authoritative**. The **Financial Action Policy Engine** (`backend/app/services/policy_engine.py`) is the sole, definitive authorization gate governing all financial recovery actions.

```
┌────────────────────────────────────────────────────────┐
│                   AI RECOVERY AGENT                    │
│      Reasons, investigates, predicts, recommends        │
│              (STRICTLY NON-AUTHORITATIVE)              │
└───────────────────────────┬────────────────────────────┘
                            │ Action Proposal
                            ▼
┌────────────────────────────────────────────────────────┐
│             DETERMINISTIC POLICY ENGINE                │
│    Evaluates hardcoded, deterministic rules & limits    │
│            (AUTHORITATIVE AUTHORIZATION GATE)           │
└──────────────┬────────────┬─────────────┬──────────────┘
               │            │             │
        ALLOW  │            │ REQUIRE_    │ DENY
               ▼            │ APPROVAL    ▼
      Auto-Execution        │       Halt Action &
    via PaymentProvider     ▼       Record Reason
                    Human Approval
                         Queue
```

No financial transaction can ever execute without an explicit `ALLOW` or human operator `APPROVED` verdict.

---

## 2. Policy Engine Interface & Output Contract

### Evaluation Interface
```python
def evaluate(self, request: PolicyCheckRequest) -> PolicyDecisionResponse:
    """
    Evaluates proposed action against deterministic financial governance rules.
    Guaranteed deterministic: identical input + policy version yields identical verdict.
    """
```

### PolicyDecisionResponse Contract
Every evaluation produces a structured, audit-ready decision record:

| Field | Type | Description |
|---|---|---|
| `decision` | `str` | Definitive verdict: `"ALLOW"`, `"REQUIRE_APPROVAL"`, or `"DENY"` |
| `policy_version` | `str` | Immutable version tag (e.g. `"policy_v1"`) |
| `allowed` | `bool` | `True` if action is permitted to execute immediately |
| `approval_required` | `bool` | `True` if action requires explicit merchant sign-off |
| `rules_evaluated` | `List[str]` | Ordered list of evaluated rules (e.g. `["ACTION_ALLOWLIST", "AMOUNT_LIMIT"]`) |
| `reason` | `str` | Clear, human-readable rationale for verdict |
| `evaluated_at` | `datetime` | UTC timestamp of decision |
| `bounds` | `Dict[str, Any]` | Applied thresholds (max retry limit, amount cap, cooldown) |

---

## 3. The Three Policy Verdicts

### 1. `ALLOW` (Autonomous Execution)
- **Criteria:** Action is in allowlist, amount $\le \text{₹}15,000$, retry count $< 3$, cooldown satisfied ($> 4$ hours since last attempt), risk tier is not high, and customer is active.
- **Outcome:** System proceeds directly to `PaymentProvider` adapter execution.

### 2. `REQUIRE_APPROVAL` (Human-in-the-Loop)
- **Criteria:** Safe recovery opportunity exceeding the autonomous financial threshold ($\text{₹}15,000 < \text{Amount} \le \text{₹}5,00,000$) or VIP/escalation action.
- **Outcome:** System halts execution, creates an `APPROVAL_PENDING` action ticket, and alerts the merchant operations console. No funds move until explicit human approval.

### 3. `DENY` (Action Blocked)
- **Criteria:** Action exceeds hard ceiling ($\text{Amount} > \text{₹}5,00,000$), retry count exhausted ($\ge 3$), cooldown active ($< 4$ hours), customer account suspended/blocked, high fraud risk, or recovery probability below confidence floor ($P_{\text{rec}} < 0.20$).
- **Outcome:** System blocks execution permanently, records the policy denial in the immutable audit log, and stops the workflow safely.

---

## 4. Policy Rules & Guardrails

The engine executes an ordered pipeline of deterministic rules:

```
Proposed Action
      │
      ▼
1. Action Allowlist Check ──[Not in enum]──► DENY (unsupported_action)
      │
      ▼
2. Hard Ceiling Cap (> ₹5L) ──[Amount > ₹500,000]──► DENY (amount_exceeds_hard_ceiling)
      │
      ▼
3. Autonomous Amount Limit (> ₹15k) ──[Amount > ₹15,000]──► REQUIRE_APPROVAL (amount_above_automatic_threshold)
      │
      ▼
4. Retry Limit Check (>= 3 attempts) ──[Retries >= 3]──► DENY (retry_limit_exhausted)
      │
      ▼
5. Cooldown Window Check (< 4h) ──[Time < 14,400s]──► DENY (cooldown_period_active)
      │
      ▼
6. Customer State & Fraud Risk ──[High Risk / Blocked]──► REQUIRE_APPROVAL / DENY (customer_risk_restricted)
      │
      ▼
7. ML Confidence Floor (< 20%) ──[P_rec < 0.20]──► DENY (low_recovery_probability)
      │
      ▼
   ALLOW (safe_for_autonomous_recovery)
```

### Configurable Parameter Defaults
| Policy Rule | Parameter | Default Value | Purpose |
|---|---|---|---|
| `MAX_AUTONOMOUS_AMOUNT` | Amount Threshold | ₹15,000 | Max value executed without human review |
| `HARD_CEILING_AMOUNT` | Hard Ceiling | ₹5,00,000 | Absolute max recovery ceiling |
| `MAX_RETRY_LIMIT` | Retry Count | 3 attempts / 24h | Prevents dunning customer harassment |
| `COOLDOWN_SECONDS` | Cooldown Window | 14,400s (4 hours) | Prevents rapid consecutive retries |
| `MIN_ML_PROBABILITY` | Confidence Floor | 0.20 (20%) | Avoids wasteful low-probability actions |
| `MAX_DAILY_ACTIONS` | Velocity Limit | 100 actions / merchant | Prevents runaway automation loops |

---

## 5. Policy Versioning & Immutability

1. **Deterministic Reproducibility:**
   - The Policy Engine is implemented in pure, deterministic Python.
   - It contains zero randomness, zero stochastic LLM dependencies, and zero uncontrolled external network calls.
   - Given identical input parameters and the active `policy_version`, the engine will always produce the exact same verdict and rationale.

2. **Version Tagging:**
   - Every evaluated decision embeds `policy_version = "policy_v1"`.
   - When policy rules or thresholds change in future releases, a new policy version tag (`"policy_v2"`) is minted.
   - Past decisions remain permanently verifiable against the historical policy version recorded at time of evaluation.

---

## 6. Human Approval Workflow

When a decision evaluates to `REQUIRE_APPROVAL`:
1. An action record is created with status `PENDING_APPROVAL`.
2. The agent workflow transitions safely to terminal investigation state with `requires_approval: true`.
3. Merchant operations review the request via `GET /api/actions/{id}`.
4. An authorized merchant operator approves via `POST /api/agent/runs/{id}/approve` or `POST /api/v1/recovery/actions/{id}/approve`.
5. The endpoint validates:
   - Authenticated operator identity and merchant tenancy.
   - Action is currently in `PENDING_APPROVAL` status (cannot approve already executed or rejected actions).
   - Approval notes are recorded in the immutable audit ledger.
6. Execution proceeds via `PaymentProvider` adapter.
