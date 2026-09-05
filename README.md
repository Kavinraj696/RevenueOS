# Razorpay RevenueOS ⚡

> **Autonomous Payment Failure & Revenue Recovery Intelligence Platform**  
> *Deterministic Detection • Machine Learning Scoring • AI Agent Recovery • Policy Guardrails • Razorpay Test Mode & Mock Execution • Immutable Audit Ledger*

---

## 🌟 Overview

**RevenueOS** is an autonomous revenue recovery engine built for modern fintechs and merchants. It transforms payment failures, checkout drop-offs, and subscription churn into recoverable revenue opportunities with zero human friction.

By orchestrating deterministic leak detection, calibrated machine learning recovery models, an autonomous tool-driven AI recovery agent, and a strict deterministic Financial Action Policy Engine, RevenueOS safely triggers high-probability recovery actions (1-click payment links, alternate bank rails, proactive notifications, and smart retries) through **Razorpay Test Mode** and **Mock Providers**.

---

## 🔄 End-to-End Autonomous Lifecycle

```
Transaction Event 
  └── 1. Failure / Degradation Detection (9 Deterministic Anomaly Detectors)
        └── 2. Revenue Leak Incident Created (Gross Value, Severity, Confidence)
              └── 3. ML Recovery Prediction (Calibrated Probability Model: 0.0 - 1.0)
                    └── 4. Recovery Opportunity Prioritized (Financial Impact × Probability)
                          └── 5. AI Agent Investigation & Recommendation (Tool-Driven)
                                └── 6. Financial Action Policy Engine Gate (Deterministic Limits & Cooldowns)
                                      └── 7. Approval Workflow (Automatic vs Merchant Sign-off)
                                            └── 8. Recovery Executor (Idempotent Provider Dispatch)
                                                  └── 9. Razorpay Test Mode / Mock Execution
                                                        └── 10. Webhook Ingestion & Signature Verification (HMAC-SHA256)
                                                              └── 11. State Mutation & Recovery Verification
                                                                    └── 12. Immutable Audit Causality Ledger & Timeline UI
```

---

## 🚀 Key Modules & Architecture

### 1. Revenue Leak Detection Engine
* 9 deterministic detection algorithms running without LLM hallucination:
  1. **Payment Failure Spikes** (Z-score anomaly detection)
  2. **Payment Method Degradation** (UPI, Card, Netbanking failure rates)
  3. **Bank-Specific Outages** (HDFC, ICICI, SBI, Axis, Kotak downtime clusters)
  4. **Device-Specific Degradation** (Android/iOS WebView drop-offs)
  5. **Time-Window Degradation** (Peak evening traffic failure clusters)
  6. **Checkout Session Abandonment** (Cart drop-offs at OTP or method selection)
  7. **Subscription Debit Spikes** (Recurring mandate renewals)
  8. **High-Value VIP Failures** (Large order drop-offs exceeding thresholds)
  9. **Repeated Customer Failures** (Multiple failed attempts per customer)

### 2. Machine Learning & Revenue Prediction Layer
* **Model 1 (Payment Recovery Probability)**: Predicts transaction recovery likelihood $[0, 1]$ based on customer tenure, bank health, error code, and amount.
* **Model 2 (Revenue Anomaly Detector)**: Unsupervised Isolation Forest detecting statistical deviations in merchant failure rates.
* **Model 3 (Opportunity Ranking)**: Prioritizes failed payments by Expected Recoverable Value ($\text{Amount} \times P(\text{recovery})$).

### 3. Tool-Driven AI Recovery Agent
* Workflow: `OBSERVE` → `INVESTIGATE` → `DIAGNOSE` → `QUANTIFY` → `RECOMMEND` → `POLICY CHECK` → `EXECUTE / REQUEST APPROVAL` → `VERIFY` → `REPORT`.
* Uses 16 strictly typed tools to inspect real database telemetry rather than inventing values.

### 4. Deterministic Financial Action Policy Engine
* Hard rules protect merchants from unauthorized or high-risk actions.
* Actions evaluated: `CREATE_PAYMENT_LINK`, `SEND_RECOVERY_NOTIFICATION`, `RECOMMEND_ALTERNATIVE_PAYMENT`, `RETRY_ALLOWED_PAYMENT`, `TRIGGER_SUBSCRIPTION_RECOVERY`, `REQUEST_MERCHANT_APPROVAL`, `BLOCK_ACTION`.
* Dynamic limits based on transaction value, risk level, and attempt cooldowns.

### 5. Payment Provider Layer (Razorpay Test Mode & Mock)
* **`RazorpayTestProvider`**: Native integration with Razorpay Test Mode API (payment links, orders, refunds, and webhooks).
* **`MockPaymentProvider`**: Instant offline fallback when API keys are absent.
* Webhook engine verifying HMAC-SHA256 signatures with replay protection and idempotent processing.

### 6. Immutable Audit System & Timeline UI
* Complete operational audit trail covering all 13 lifecycle events with zero credential exposure.
* Interactive dark-mode web application for judges and operators to trace complete causality timelines.

---

## 🛠️ Quickstart & Local Setup

### 1. Clone & Setup Environment

```bash
git clone https://github.com/Kavinraj696/RevenueOS.git
cd RevenueOS
```

### 2. Install Dependencies

```bash
cd backend
python -m venv venv
# Windows
.\venv\Scripts\activate
# Linux/macOS
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure Environment

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

*(Optional: Populate `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, and `RAZORPAY_WEBHOOK_SECRET` with your Razorpay Test Mode keys).*

### 4. Run the Application

```bash
# Start FastAPI backend
uvicorn app.main:app --reload --port 8000
```

* **Interactive OpenAPI Docs**: [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)
* **Audit Timeline UI**: [http://localhost:8000/audit](http://localhost:8000/audit)
* **Health Check**: [http://localhost:8000/health](http://localhost:8000/health)

---

## 🧪 Testing & Validation

The codebase includes comprehensive automated tests covering all engines, providers, policy guardrails, and audit ledgers:

```bash
# Run full test suite (89 passing tests)
pytest backend/tests -v
```

---

## 🛡️ Security & Privacy Guardrails

- **Zero Credential Exposure**: Automatic secret redaction strips `api_secret`, `key_secret`, `webhook_secret`, `authorization`, `password`, `token`, and `private_key` before audit logging.
- **API Key Masking**: Gateway keys are masked (e.g. `rzp_test_...5E4F`).
- **No Floating Point Money**: All financial fields strictly use `DECIMAL(14, 2)` / integer paise for mathematical correctness.

---

## 📜 License

MIT License © 2026 Razorpay RevenueOS Contributors.
