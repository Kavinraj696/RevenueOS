# RevenueOS Incident Response & Security Operations Playbook

## 1. Incident Classification & Severity Levels

| Severity | Definition | Response SLA | Escalation Target | Example |
| :--- | :--- | :--- | :--- | :--- |
| **SEV-1 (Critical)** | Active financial loss, unauthorized payment link creation, cross-tenant data breach, or secret leakage | Immediate (< 15 mins) | CTO, Head of Security, On-call Lead | Razorpay Key Secret leaked; cross-tenant data visible |
| **SEV-2 (High)** | Webhook validation failure spike, rate limiter failure, policy engine bypass attempt, or high gateway timeout rate | < 1 hour | Security Engineering, Backend Lead | HMAC mismatch on 50%+ of webhooks; prompt injection bypass |
| **SEV-3 (Medium)** | AI Agent loop exhaustion, ML model drift, single recovery failure without fallback | < 4 hours | Platform Engineering | AI agent timing out on complex multi-hop analysis |
| **SEV-4 (Low)** | Non-blocking telemetry error, UI display discrepancy | < 24 hours | Product Engineering | Discrepancy in dashboard chart rendering |

---

## 2. Emergency Operational Playbooks

### Playbook A: Compromised Credentials or API Keys (SEV-1)
1. **Immediate Revocation**:
   - Access Razorpay Dashboard $\rightarrow$ Settings $\rightarrow$ API Keys $\rightarrow$ Regenerate Key Secret.
   - Update `.env` / Secret Manager with new `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`.
2. **Rotate Application JWT Secrets**:
   - Rotate `JWT_SECRET_KEY` in environment configuration.
   - Invalidate all existing bearer tokens immediately.
3. **Restart RevenueOS Backend**:
   - Rolling restart of backend worker processes to pick up clean environment variables.
4. **Audit Historical Activity**:
   - Execute query on `audit_events` to inspect all actions executed within the exposure window:
     ```sql
     SELECT * FROM audit_events WHERE timestamp >= 'YYYY-MM-DD HH:MM:SS' ORDER BY timestamp DESC;
     ```
5. **Freeze Recovery Pipeline if Needed**:
   - Switch `RAZORPAY_TEST_MODE=True` or set `MAX_SINGLE_RECOVERY_AMOUNT=0` to immediately halt automated money movement.

---

### Playbook B: Detected Webhook Forgery or Replay Attack (SEV-2)
1. **Verify Webhook Engine Status**:
   - Inspect `/api/v1/security/audit` to confirm `X-Razorpay-Signature` validation is active.
2. **Review Webhook Event Logs**:
   - Inspect `webhook_events` for duplicate `event_id` occurrences:
     ```sql
     SELECT event_id, count(*) FROM webhook_events GROUP BY event_id HAVING count(*) > 1;
     ```
   - Verify that duplicates returned `idempotent_duplicate` with zero state mutations.
3. **Rotate Webhook Secret**:
   - In Razorpay Dashboard, update the webhook endpoint secret.
   - Update `RAZORPAY_WEBHOOK_SECRET` in RevenueOS config.

---

### Playbook C: Cross-Tenant Authorization Violation (SEV-1)
1. **Isolate Affected Tenant**:
   - Immediately verify bearer token claims vs target merchant UUID.
2. **Check Access Logs**:
   - Filter logs for `[SECURITY] Authorization denied: User merchant ... attempted cross-tenant access`.
3. **Audit Data Leakage**:
   - Query `audit_events` for unauthorized reads or mutations across tenant boundaries.

---

### Playbook D: High Gateway Failure Rate or Network Partition (SEV-2)
1. **Verify Circuit Breaker**:
   - Ensure `RecoveryExecutor` falls back to `ActionStatus.FAILED` and triggers alternative recommendations.
2. **Reconciliation Inspection**:
   - Run manual reconciliation sweep via `/api/v1/recovery/reconcile` once gateway restores.
3. **Notify Merchants**:
   - Display operational degradation banner on merchant dashboard.
