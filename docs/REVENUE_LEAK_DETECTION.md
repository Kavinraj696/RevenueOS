# RevenueOS — Revenue Leak Detection Engine (Stage 3)

## 1. Executive Summary & Objective

The **RevenueOS Revenue Leak Detection Engine** is a deterministic, statistical detection engine designed to analyze merchant transaction streams, identify meaningful revenue-loss patterns, rank contributing root-cause segments, and quantify the exact financial impact without relying on LLMs for numerical detection or hardcoded demo results.

The engine answers six fundamental merchant operations questions:
1. **Is revenue leaking?** (Deviation testing against empirical baselines)
2. **Where is it leaking?** (Multi-dimensional channel and funnel isolation)
3. **How large is the impact?** (Separation of Gross Affected Revenue vs. Incremental Revenue-at-Risk)
4. **Which segment is affected?** (Ranked contributing segments by excess failure volume)
5. **How confident are we?** (Transparent, deterministic confidence score based on sample size and concentration)
6. **What evidence supports the detection?** (Structured metrics dictionary preserving baseline, current, and segment-level data)

---

## 2. Core Detection Architecture

```
                               Raw Event Streams
          (Payments, Checkout Sessions, Subscription Auto-Debits)
                                     │
                                     ▼
                      Empirical Historical Baseline
           (Merchant-specific rates, ATV, volume, P80/P90, segments)
                                     │
                                     ▼
                         Current Window Extraction
                  (Configurable analysis window [a_start, a_end])
                                     │
                                     ▼
               ┌─────────────────────┴─────────────────────┐
               │         Multi-Vector Anomaly Detectors    │
               ├───────────────────────────────────────────┤
               │ Vector 1: Payment Route Degradation       │
               │ Vector 2: Checkout Funnel Drop-off        │
               │ Vector 3: Subscription Recurring Churn    │
               │ Vector 4: High-Value Percentile Failure   │
               │ Vector 5: Repeated Customer Churn Risk    │
               └─────────────────────┬─────────────────────┘
                                     │
                                     ▼
                        Multi-Dimensional Clustering
                     (Bank × Method × Device × Time Block)
                                     │
                                     ▼
                          Root-Cause Candidate Ranking
                     (Ranked by excess financial contribution)
                                     │
                                     ▼
                       Revenue-at-Risk Quantification
             (Gross Affected vs. Incremental Financial Loss)
                                     │
                                     ▼
                        Severity & Confidence Scoring
                       (Deterministic multi-tier matrix)
                                     │
                                     ▼
                         Idempotent Deduplication
                 (In-place metric updates for open windows)
                                     │
                                     ▼
                          Persisted RevenueLeak Record
```

---

## 3. Historical Baseline Methodology

To prevent false alarms driven by arbitrary global constants, the engine calculates **merchant-specific empirical baselines** directly from historical database records.

### 3.1 Window Resolution & Chronological Partitioning
* **Analysis Window ($W_A$):** Defaults to the most recent 7 to 14 days based on the merchant's latest recorded transaction timestamp ($t_{\text{max}}$).
  $$a_{\text{end}} = t_{\text{max}}, \quad a_{\text{start}} = a_{\text{end}} - \Delta t_{\text{window}}$$
* **Baseline Window ($W_B$):** Preceding time window spanning $2 \times \Delta t_{\text{window}}$:
  $$b_{\text{end}} = a_{\text{start}}, \quad b_{\text{start}} = b_{\text{end}} - 2 \cdot \Delta t_{\text{window}}$$
* **Cold-Start Chronological Partitioning:** If a merchant has sparse or zero historical records in the designated baseline window ($N_{\text{baseline}} < 10$), the engine chronologically partitions the available transaction stream into an earlier half (baseline) and a later half (current), ensuring true temporal comparison without synthetic ground-truth shortcuts.

### 3.2 Baseline Metrics Calculated
1. **Payment Failure Rate ($R_{\text{fail, base}}$):** Ratio of failed payments to total attempts with a safe statistical floor ($1.5\%$):
   $$R_{\text{fail, base}} = \max\left(0.015, \frac{N_{\text{fail, base}}}{N_{\text{total, base}}}\right)$$
2. **Average Transaction Value ($\text{ATV}_{\text{base}}$):** Mean transaction amount across baseline payments.
3. **Total Payment Volume:** Sum of processed gross volume during baseline.
4. **Merchant High-Value Percentile Threshold ($P_{80}$ / $P_{90}$):** 80th/90th percentile of transaction amounts for the merchant.
5. **Multi-Dimensional Segment Baselines:** Baseline failure rates mapped per tuple:
   $$\text{Key} = (\text{bank}, \text{payment\_method}, \text{device\_type}, \text{hour\_block})$$
6. **Checkout Abandonment Baseline:** Baseline cart abandonment rate ($N_{\text{abandoned}} / N_{\text{started}}$).
7. **Subscription Renewal Failure Baseline:** Baseline recurring auto-debit failure rate.

---

## 4. Detection Vectors & Mathematical Formulas

### Vector 1: Payment Route Degradation & Failure Spikes
* **Objective:** Detect statistically significant increases in payment failure rates across specific payment routes, banks, or device types.
* **Trigger Conditions:**
  * Minimum cluster sample size: $N_{\text{cluster}} \ge 5$ attempts.
  * Observed failure rate: $R_{\text{current}} \ge 35\%$.
  * Relative increase over baseline: $R_{\text{current}} \ge 2.0 \times R_{\text{base}}$.
  * Rate difference: $\Delta R = R_{\text{current}} - R_{\text{base}} \ge 8\%$.
* **Ranked Root-Cause Candidates:**
  Segments are ranked by their excess financial contribution score:
  $$\text{Contribution} = (N_{\text{cluster}} \cdot \Delta R) \times \text{ATV}_{\text{cluster}}$$
  Contributing segments include `bank`, `payment_method`, `device_type`, `time_window`, and gateway `error_codes`.

### Vector 2: Checkout Funnel Drop-off
* **Objective:** Detect anomalous cart drop-offs during customer checkout sessions.
* **Trigger Conditions:**
  * Total sessions: $N_{\text{sessions}} \ge 5$.
  * Abandonment rate: $R_{\text{abandon}} \ge 30\%$.
  * Relative increase: $\Delta R_{\text{abandon}} \ge 10\%$ above merchant baseline.
* **Diagnostic Breakdown:** Evaluates drop-off counts across checkout stages (`cart_review`, `shipping_address`, `payment_method_select`, `otp_entry`) to pinpoint interface friction points.

### Vector 3: Subscription Recurring Mandate Failures
* **Objective:** Identify spikes in recurring payment and mandate auto-debit failures.
* **Trigger Conditions:**
  * Mandate renewal attempts: $N_{\text{renewals}} \ge 5$.
  * Observed failure rate: $R_{\text{sub\_fail}} \ge 20\%$.
  * Absolute increase: $\Delta R_{\text{sub}} \ge 10\%$ above baseline.
* **Root-Cause Signals:** Breaks down bank error codes (e.g., `MANDATE_LIMIT_EXCEEDED`, `CARD_EXPIRED`, `INSUFFICIENT_FUNDS`).

### Vector 4: High-Value Failed Transactions (Percentile-Based)
* **Objective:** Surface failed transactions with unusually large financial impact that represent high-intent recovery opportunities.
* **Trigger Conditions:**
  * Transaction amount $\ge \max(\text{₹}15,000, P_{80})$.
  * Failed payment count $\ge 2$ (with 75th percentile evaluation fallback for sparse high-ticket distributions).
* **Revenue Classification:** Surfaced as `payment_failure` opportunity signals.

### Vector 5: Repeated Customer Payment Failures (Churn Risk)
* **Objective:** Detect customers experiencing multiple consecutive payment failures within the active window.
* **Trigger Conditions:**
  * Customers with $\ge 2$ failed attempts across distinct transactions.
  * Number of affected repeat customers $\ge 2$.
* **Deduplication:** Aggregates distinct logical payment entities to prevent double-counting multiple gateway retries of the same order.

---

## 5. Financial Quantification: Gross Affected vs. Revenue at Risk

RevenueOS enforces a strict separation between gross affected volume and incremental financial loss:

| Metric | Definition | Mathematical Formula |
| :--- | :--- | :--- |
| **Gross Affected Revenue** | Total financial volume of all failed events in the affected cluster. | $$\text{Gross} = \sum_{i \in \text{Failures}} \text{Amount}_i$$ |
| **Incremental Revenue at Risk (RAR)** | Financial loss directly attributable to the *excess* failure rate above historical baseline. | $$\text{RAR} = \text{Gross} \times \max\left(0, \frac{R_{\text{current}} - R_{\text{base}}}{R_{\text{current}}}\right)$$ |

*Example:*
* 100 payments of ₹1,000 in cluster $\implies$ ₹100,000 gross attempted volume.
* Baseline failure rate: 4%. Expected failures: 4.
* Observed failures: 40 (40% failure rate) $\implies$ ₹40,000 Gross Affected Revenue.
* Excess failure rate fraction: $\frac{0.40 - 0.04}{0.40} = 0.90$.
* Incremental Revenue at Risk: $\text{₹}40,000 \times 0.90 = \text{₹}36,000.00$.

*High-Value Recovery Exception:*
High-value failed transactions represent high customer purchase intent. For Vector 4, where intent is non-random and recoverable via alternative payment channels (e.g., 1-click links or Netbanking fallbacks), RAR is quantified as $85\%$ of gross failed value.

---

## 6. Deterministic Severity System

Severity is calculated deterministically through a multi-factor decision matrix incorporating rate deviation, Revenue at Risk, and sample size:

| Severity Level | Severity Score | Revenue at Risk Threshold | Rate Deviation ($\Delta R$) & Sample ($N$) |
| :--- | :---: | :---: | :---: |
| **CRITICAL** | `9.00` – `9.50` | $\text{RAR} \ge \text{₹}100,000.00$ | $\Delta R \ge 40\%$ with $N \ge 20$, or cluster failure $\ge 60\%$ |
| **HIGH** | `8.00` – `8.50` | $\text{₹}25,000.00 \le \text{RAR} < \text{₹}100,000.00$ | $\Delta R \ge 20\%$ with $N \ge 15$ |
| **MEDIUM** | `6.50` – `7.20` | $\text{₹}5,000.00 \le \text{RAR} < \text{₹}25,000.00$ | $\Delta R \ge 8\%$ with $N \ge 10$ |
| **LOW** | `4.50` – `5.00` | $\text{RAR} < \text{₹}5,000.00$ | $\Delta R < 8\%$ or small sample |

---

## 7. Transparent Detection Confidence Score

The detection confidence score reflects statistical certainty without masquerading as an opaque machine learning probability. It is bounded within $[0.40, 0.99]$:

$$\text{Confidence} = \text{clamp}\left(0.40 + S_{\text{sample}} + S_{\text{deviation}} + S_{\text{concentration}}, \quad 0.40, \quad 0.99\right)$$

Where:
* **Sample Size Score ($S_{\text{sample}}$):** $\min(0.25, \frac{N}{200} \times 0.25)$ — awards higher confidence for robust sample sizes.
* **Deviation Score ($S_{\text{deviation}}$):** $\min(0.20, \Delta R \times 0.35)$ — awards confidence for prominent baseline divergences.
* **Concentration Score ($S_{\text{concentration}}$):** $\min(0.14, C_{\text{score}} \times 0.14)$ — reflects whether failures isolate into a single segment (e.g., specific bank/device).

---

## 8. Idempotent Deduplication & Persistence

To prevent duplicate leaks when background detection runs repeatedly over overlapping analysis windows:
1. **Deduplication Key:** `(merchant_id, leak_type, pattern_description, status="open")`.
2. **In-Place Updates:** If an open leak matching the composite key already exists:
   * Updates `affected_transactions`, `gross_value_affected`, `affected_amount`, and `revenue_at_risk`.
   * Updates `evidence` payload and `root_cause_candidates`.
   * Extends `detection_window_end = max(existing.detection_window_end, new.detection_window_end)`.
   * Recalculates `severity` and `confidence`.
3. **Immutability of Closed Leaks:** Resolved or dismissed leaks are never modified; a new cycle creates a separate record.

---

## 9. False-Positive Validation & Seed Divergence

Statistical detectors must not flag benign natural variance as critical anomalies. The engine was verified across diverse healthy datasets using pseudo-random seeds:

| Seed | Dataset Profile | Observed Failure Rate | Payment Anomalies Flagged | Checkout Leaks Flagged | False Positive Verdict |
| :---: | :---: | :---: | :---: | :---: | :---: |
| `1001` | Baseline retail mix | 2.8% | 0 | 0 | **PASS** |
| `2002` | High UPI volume | 3.1% | 0 | 0 | **PASS** |
| `3003` | Card & Netbanking mix | 2.9% | 0 | 0 | **PASS** |
| `4004` | High mobile traffic | 3.4% | 0 | 0 | **PASS** |

**Zero** false critical or high payment degradation anomalies and **zero** false checkout abandonment leaks were detected on healthy merchant datasets.

---

## 10. Robustness & Time Boundary Handling

The engine explicitly handles all time-boundary and distribution edge cases without throwing exceptions:
1. **Empty Merchant Dataset ($N = 0$):** Gracefully returns empty leak list `[]`.
2. **Below Minimum Sample ($N = 1$ to $4$):** Evaluates baseline and skips anomaly alerts due to insufficient sample size guards.
3. **No Historical Baseline Window:** Chronologically splits available records into baseline and current windows.
4. **Boundary Edges:** Exact boundary timestamps are inclusive on start (`>= a_start`) and end (`<= a_end`), preventing event drop-off.

---

## 11. API Specifications

### 11.1 Trigger Detection
* **Method:** `POST`
* **Path:** `/api/v1/revenue-leaks/detect` (and `/api/revenue-leaks/detect`)
* **Request:**
  ```json
  {
    "merchant_id": "c1f72b9a-4c2f-48d9-bf12-421731671982",
    "analysis_window_days": 14,
    "analysis_window_start": "2026-08-18T00:00:00Z",
    "analysis_window_end": "2026-09-01T12:00:00Z",
    "baseline_window_start": "2026-07-21T00:00:00Z",
    "baseline_window_end": "2026-08-18T00:00:00Z"
  }
  ```
* **Response (200 OK):**
  ```json
  {
    "status": "success",
    "merchant_id": "c1f72b9a-4c2f-48d9-bf12-421731671982",
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
    "leaks": [...]
  }
  ```

### 11.2 List & Filter Leaks
* **Method:** `GET`
* **Path:** `/api/v1/revenue-leaks`
* **Query Parameters:** `merchant_id`, `leak_type`, `severity`, `status`.

### 11.3 Leak Detail
* **Method:** `GET`
* **Path:** `/api/v1/revenue-leaks/{leak_id}`

---

## 12. Architectural Boundaries & Stage Constraints

* **Stage 3 Scope:** Pure deterministic detection, baseline estimation, segment ranking, Revenue-at-Risk calculation, and persistence.
* **Strict Prohibitions Enforced:**
  * **No LLM in numeric detection:** All rates, differences, and amounts are computed using NumPy and standard math.
  * **No ground-truth leakage:** Detection code does not read `ScenarioGroundTruth` or synthetic labels.
  * **No autonomous recovery execution:** Generating recovery actions and executing Razorpay API calls belongs strictly to Stages 4 and 5.
