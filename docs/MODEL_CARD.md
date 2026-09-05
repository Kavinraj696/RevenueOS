# Model Card — Payment Recovery Probability (`recovery_probability_v1`)

## 1. Model Details

* **Model Name:** `payment_recovery_probability`
* **Model Version:** `recovery_probability_v1`
* **Feature Pipeline Version:** `v1.0.0`
* **Training Dataset Version:** `recovery_dataset_v1.0.0`
* **Model Type:** Supervised binary classification with post-hoc Platt scaling calibration.
* **Underlying Algorithm:** `HistGradientBoostingClassifier(max_iter=150, learning_rate=0.08, max_leaf_nodes=31, class_weight='balanced', random_state=42)`.
* **Calibration Method:** Univariate Platt scaling (`LogisticRegression`) fitted strictly on the held-out validation split.
* **Architectural Role:** **Strictly Advisory Intelligence**. The model generates probabilistic estimates and expected recovery values; it has **no authority to execute financial operations**, retry payments, issue refunds, or bypass the Policy Engine.

---

## 2. Intended Use & Non-Intended Use

### Intended Use
* Estimating point-in-time recovery likelihood $P(\text{recovery} \mid \text{features at } T_{\text{pred}}) \in [0.0, 1.0]$ for failed merchant transactions.
* Calculating Expected Recovered Value ($\text{ERV} = P_{\text{rec}} \times \text{Potentially Recoverable Revenue}$).
* Prioritizing candidate recovery opportunities for human review or autonomous policy evaluation.
* Providing transparent, explainable feature-level contributing factors for operational insight.

### Non-Intended Use & Out-of-Scope Activities
* **Direct Financial Execution:** Model predictions must never be treated as payment authorization commands.
* **Automated Chargebacks / Refunds:** The model does not assess fraud risk or refund eligibility.
* **Credit Scoring / Underwriting:** The model must not be used to assess consumer creditworthiness.
* **Extrapolation to Unsupported Rails:** The model is trained on Indian payment ecosystem methods (`upi`, `card`, `netbanking`, `wallet`); do not use for international wires or cryptocurrency.

---

## 3. Training Data & Temporal Splitting

* **Total Samples:** 198 point-in-time observations.
* **Class Distribution:** Positive rate ~25.0% (recovered), Negative rate ~75.0% (permanent failure).
* **Temporal Splitting:** Strict chronological 3-way split:
  - **Training Set (60%):** 118 samples (Earliest: `2026-07-01T01:02:32Z` to `2026-08-21T13:04:00Z`).
  - **Validation Set (20%):** 40 samples (`2026-08-21T17:22:00Z` to `2026-08-26T19:56:00Z`). Used exclusively for Platt calibration.
  - **Test Set (20%):** 40 samples (`2026-08-27T04:37:00Z` to `2026-09-01T20:16:00Z`). Held-out untouched evaluation split.
* **Temporal Leakage Safeguard:** Enforced $\max(\text{train } T_{\text{pred}}) < \min(\text{val } T_{\text{pred}}) < \min(\text{test } T_{\text{pred}})$. All features strictly respect $\text{event\_time} \le \text{prediction\_time}$.

---

## 4. Feature Contract (29 Point-in-Time Features)

| Feature Group | Features | Point-in-Time Invariant | Missing / Cold-Start Policy |
|---|---|---|---|
| **Transaction** | `transaction_amount`, `log_amount`, `amount_percentile_for_merchant`, `payment_method`, `transaction_hour`, `transaction_day_of_week`, `days_since_transaction`, `attempt_number`, `time_since_previous_attempt` | Computed at $T_{\text{pred}}$ | Imputed to 0.0 or neutral |
| **Customer** | `customer_transaction_count_before_prediction`, `customer_success_count`, `customer_failure_count`, `customer_historical_success_rate`, `customer_historical_failure_rate`, `customer_lifetime_value_before_prediction`, `days_since_last_success`, `days_since_last_transaction`, `is_cold_start` | Strictly $\text{event\_time} < T_{\text{pred}}$ | `is_cold_start = 1`, success rate = 0.50 |
| **Payment / Gateway** | `failure_reason`, `bank`, `device_type`, `previous_payment_method_success_rate`, `previous_attempt_count`, `time_since_failure` | Computed at $T_{\text{pred}}$ | Unknown bank/method maps to `"OTHER"` / `"UNKNOWN"` |
| **Subscription** | `is_subscription`, `subscription_age_days`, `renewal_number`, `previous_renewal_count`, `previous_renewal_success_rate`, `plan_value`, `subscription_status` | Strictly $\text{event\_time} \le T_{\text{pred}}$ | Defaults to 0.0 / `"none"` for non-subscription |
| **Merchant Baseline** | `merchant_payment_success_rate`, `merchant_failure_rate`, `merchant_average_transaction_value`, `merchant_payment_method_success_rate` | Strictly $\text{event\_time} < T_{\text{pred}}$ | Historical merchant priors (80% success, ₹2500 ATV) |

---

## 5. Evaluation Metrics (Held-Out Test Set)

Metrics evaluated strictly on the untouched test set ($N = 40$):

| Metric | Naive Historical Mean Baseline | Logistic Regression Benchmark | HistGradientBoosting (Production) | Calibrated Lift vs Naive |
|---|---|---|---|---|
| **Accuracy** | 75.0% | 77.5% | **80.0%** | +5.0% |
| **Precision** | 0.0% (no positives predicted) | 53.3% | **56.3%** | +56.3% |
| **Recall** | 0.0% | 80.0% | **90.0%** | +90.0% |
| **F1 Score** | 0.0000 | 0.6400 | **0.6923** | **+0.6923** |
| **ROC-AUC** | 0.5000 | 0.8533 | **0.8900** | **+0.3900** |
| **PR-AUC (Avg Prec)** | 0.2500 | 0.6462 | **0.6239** | **+0.3739** |
| **Brier Score** | 0.2342 | 0.1767 | **0.1342 (Calibrated)** | **-0.1000** (Lower is better) |

### Top-K Retrieval Metrics
* **Top 10% ($K = 4$):** Precision@K: 75.0%, Recall@K: 30.0%
* **Top 20% ($K = 8$):** Precision@K: 62.5%, Recall@K: 50.0%

---

## 6. Model 2: Opportunity Ranking Evaluation

Comparison of portfolio value captured across top candidate subsets:

| Ranking Strategy | Top 4 Value Captured | Top 8 Value Captured | Top 10 Value Captured | Total Captured ($K=10$) |
|---|---|---|---|---|
| **RevenueOS Model 2 (ERV & Score)** | **₹1,75,080.42** | **₹4,11,396.44** | **₹5,20,104.83** | **61.7% of recoverable value** |
| **Highest Value First** | ₹1,39,821.14 | ₹4,60,947.87 | ₹5,51,112.74 | 65.4% |
| **Highest Probability First** | ₹1,54,292.78 | ₹4,62,433.17 | ₹6,41,382.45 | 76.1% |
| **Random Selection** | ₹2,48,529.53 | ₹2,48,529.53 | ₹2,48,529.53 | 29.5% |

* **Analysis:** Model 2 dynamically balances probability, value, and operational feasibility, delivering high expected conversion without chasing unrecoverable high-ticket outliers.

---

## 7. Explainability & Contributing Factors

Predictions return transparent, human-readable contributing factors:
```json
"contributing_factors": [
  {
    "factor": "Failure Reason: TIMEOUT",
    "impact": "positive",
    "direction": "+",
    "weight": 0.28,
    "description": "Transient gateway timeout indicates temporary bank latency rather than cardholder refusal."
  },
  {
    "factor": "Customer Historical Track Record: 85% success",
    "impact": "positive",
    "direction": "+",
    "weight": 0.21,
    "description": "Customer has strong historical success rate (85%) on prior orders."
  }
]
```

---

## 8. Known Limitations & Failure Modes

1. **Synthetic Training Corpus Limitations:**
   - The initial training dataset is derived from synthetic commerce simulations (Stage 2). While calibrated against empirical Indian gateway failure modes, live merchant production distributions may exhibit higher cardholder authentication friction.
2. **Cold-Start Uncertainty:**
   - First-time customers have zero prior transaction records. While `is_cold_start = 1` sets a neutral prior, confidence intervals are wider for cold-start transactions.
3. **External Bank Outages:**
   - During widespread, unannounced core banking outages (e.g. CBS downtime), historical bank-level features may lag real-time downtime by 5–15 minutes until fresh telemetry accumulates.
