# RevenueOS Machine Learning & Revenue Prediction Methodology

This document outlines the formal mathematical formulations, statistical learning algorithms, data hygiene protocols, and actuarial revenue definitions underpinning the RevenueOS ML layer.

---

## 1. Actuarial Revenue Formulation

To avoid ambiguous or inflated loss reporting, RevenueOS strictly distinguishes five distinct financial dimensions for every incident and recovery opportunity:

### 1.1. Gross Affected Revenue ($R_{\text{gross}}$)
The unadjusted nominal sum of transaction amounts or abandoned cart face values within the affected entity or cluster:
$$R_{\text{gross}} = \sum_{i \in \mathcal{E}} A_i$$
where $A_i$ is the face amount of transaction $i \in \mathcal{E}$.

### 1.2. Revenue at Risk ($R_{\text{risk}}$ or RAR)
The portion of gross affected revenue that would be permanently lost without active automated intervention. This accounts for natural, unassisted organic customer retries ($\alpha_{\text{organic}}$):
$$R_{\text{risk}} = R_{\text{gross}} \times (1 - \alpha_{\text{organic}})$$
- For checkout sessions, baseline organic return rate is empirically $\alpha_{\text{organic}} \approx 0.10$ ($R_{\text{risk}} = 0.90 \times R_{\text{gross}}$).
- For payment attempts, baseline customer retry rate is $\alpha_{\text{organic}} \approx 0.15$ ($R_{\text{risk}} = 0.85 \times R_{\text{gross}}$).

### 1.3. Potentially Recoverable Revenue ($R_{\text{potential}}$)
The upper bound of Revenue at Risk that can realistically be addressed by automated recovery rails (e.g. smart retries, WhatsApp payment links, dynamic fallback routing, mandate re-triggers):
$$R_{\text{potential}} = R_{\text{risk}} \times \beta_{\text{addressable}}$$
where $\beta_{\text{addressable}} = 0.85$ reflects technical gateway and channel addressability limits.

### 1.4. Expected Recovery ($E[R]$)
The actuarial expected return of an individual or clustered recovery action, parameterized by predicted recovery probability and model confidence:
$$E[R]_i = P(\text{recovery}_i \mid \mathbf{x}_i) \times R_{\text{potential}, i} \times C_i$$
where:
- $P(\text{recovery}_i \mid \mathbf{x}_i) \in [0, 1]$ is the calibrated inference output of **Model 1**.
- $C_i \in [0.5, 1.0]$ is the model confidence score based on feature density and decision margin.
- Total portfolio expected recovery is $E[R] = \sum_{i} E[R]_i$.

### 1.5. Actual Recovery ($R_{\text{actual}}$)
The ground-truth settled monetary amount recovered through completed recovery operations:
$$R_{\text{actual}} = \sum_{j \in \mathcal{R}} A_j$$
where $\mathcal{R}$ is the set of successfully settled transactions following recovery execution.

---

## 2. Model 1: Payment Recovery Probability

### 2.1. Problem Definition
Binary classification predicting whether an initially failed transaction will successfully settle upon subsequent automated intervention:
$$y_i \in \{0, 1\}, \quad y_i = 1 \iff \text{Status} \in \{\text{recovered}, \text{success after retry}\}$$

### 2.2. Feature Space ($\mathbf{x}_i$)
Features are strictly derived from prior context to prevent target and forward-looking leakage:
- Numerical Features:
  - $\log(1 + \text{amount})$: Scaled transaction value
  - $\text{attempt\_count}$: Cumulative attempts to date
  - $\text{customer\_ltv}$: Historical gross value of customer
  - $\text{hour\_of\_day} \in [0, 23]$, $\text{day\_of\_week} \in [0, 6]$
- Categorical Features (One-Hot Encoded):
  - $\text{payment\_method} \in \{\text{upi}, \text{card}, \text{netbanking}, \text{wallet}\}$
  - $\text{bank} \in \{\text{HDFC}, \text{ICICI}, \text{SBI}, \text{AXIS}, \text{KOTAK}, \dots\}$
  - $\text{device\_type} \in \{\text{android}, \text{ios}, \text{desktop}, \text{mobile\_web}\}$
  - $\text{customer\_risk\_segment} \in \{\text{low}, \text{medium}, \text{high}\}$
  - $\text{error\_code\_category} \in \{\text{TIMEOUT}, \text{INSUFFICIENT\_FUNDS}, \text{LIMIT\_EXCEEDED}, \text{AUTH\_FAILURE}, \text{OTHER}\}$

### 2.3. Zero Data Leakage Protocol & Temporal Splitting
In financial time-series, random $k$-fold cross validation induces substantial forward-looking data leakage (learning future gateway recovery behaviors to predict the past). 
Therefore, RevenueOS enforces:
1. **Chronological Splitting:**
   $$\mathcal{D}_{\text{train}} = \{(x_t, y_t) \mid t \le T_{\text{split}}\}, \quad \mathcal{D}_{\text{test}} = \{(x_t, y_t) \mid t > T_{\text{split}}\}$$
   where $T_{\text{split}}$ corresponds to the 75th percentile timestamp.
2. **Independent Preprocessing Fitting:**
   Standardization $(\mu_{\text{train}}, \sigma_{\text{train}})$ and categorical vocabulary mappings $\mathcal{V}_{\text{train}}$ are computed **strictly on $\mathcal{D}_{\text{train}}$** and transformed onto $\mathcal{D}_{\text{test}}$ with unknown value handling.

### 2.4. Baseline vs. Improved Production Model
- **Baseline Model:** $\ell_2$-regularized Logistic Regression with inverse class-frequency weighting:
  $$P_{\text{base}}(y=1 \mid \mathbf{x}) = \sigma(\mathbf{w}^T \mathbf{x} + b) = \frac{1}{1 + e^{-(\mathbf{w}^T \mathbf{x} + b)}}$$
- **Improved Production Model:** Histogram-based Gradient Boosted Decision Trees (`HistGradientBoostingClassifier`):
  Minimizes negative binomial log-likelihood across iterative tree ensembles:
  $$\mathcal{L}(y, F(\mathbf{x})) = \sum_{i=1}^N \log(1 + e^{-2 y_i F(\mathbf{x}_i)})$$
  Captures complex non-linear interactions between Issuer Bank downtime windows, payment routes, and device platforms.

### 2.5. Evaluation Metrics
Evaluated on the held-out temporal test set:
$$\text{Precision} = \frac{TP}{TP + FP}, \quad \text{Recall} = \frac{TP}{TP + FN}, \quad F_1 = 2 \cdot \frac{\text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}}$$
$$\text{ROC-AUC} = \int_{0}^1 \text{TPR}(\text{FPR}^{-1}(t)) \, dt$$

---

## 3. Model 2: Revenue Anomaly Detector

Detects systemic infrastructure or payment route degradations by evaluating time-bucketed metric tuples:
$$\mathbf{z}_t = [\text{Volume}_t, \text{FailureRate}_t, \text{GrossAmount}_t, \text{RAR}_t]$$

### 3.1. Isolation Forest Formulation
Recursively partitions data points via random hyperplane cuts:
$$s(\mathbf{z}, n) = 2^{-\frac{E(h(\mathbf{z}))}{c(n)}}$$
where $h(\mathbf{z})$ is tree path length, $c(n) = 2 \ln(n - 1) + 0.5772156649 - \frac{2(n-1)}{n}$ is average path length of unsuccessful searches. Anomalies isolate significantly closer to the root ($h(\mathbf{z}) \ll c(n)$).

### 3.2. Robust Rolling MAD Normalization
For real-time streaming buckets, anomalies are verified against the rolling Median Absolute Deviation (MAD):
$$\text{MAD} = \text{median}(|z_t - \text{median}(\mathbf{z})|), \quad Z_{\text{robust}} = \frac{z_t - \text{median}(\mathbf{z})}{1.4826 \times \text{MAD}}$$
Alerts are triggered when $s(\mathbf{z}, n) \ge \tau_{\text{iso}}$ and $Z_{\text{robust}} \ge 2.5$.

---

## 4. Model 3: Recovery Opportunity Ranking

Ranks candidate recovery operations by maximizing actuarial return subject to merchant operational budget and user contact limits:

$$\text{Rank Score}_i = E[R]_i = P(\text{recovery}_i) \times R_{\text{potential}, i} \times C_i$$

Opportunities are presented in strict monotonically decreasing order:
$$\mathcal{O}_{(1)} \ge \mathcal{O}_{(2)} \ge \dots \ge \mathcal{O}_{(K)}$$
Ensures engineering, operations, and policy agents focus automated budget on maximum-yield interventions.
