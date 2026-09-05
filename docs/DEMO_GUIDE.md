# RevenueOS — Demonstration Guide

This guide provides end-to-end instructions for running the RevenueOS demonstration via both the **Automated CLI Runner** and the **Interactive Web Dashboard**.

---

## 1. Quick Start: Automated CLI Demonstration

The CLI runner executes the full end-to-end pipeline, reseeds the database, executes leak detection and ML scoring, runs the Canonical Golden Scenario and Scenarios A–H, and outputs executive-ready formatted summary tables.

### Execution Command
```bash
# Run the full automated demonstration
python backend/scripts/run_demo.py

# Optional: Run in verbose mode with forensic logs
python backend/scripts/run_demo.py --verbose

# Optional: Seed with custom deterministic random seed
python backend/scripts/run_demo.py --seed 42
```

### Expected CLI Output
```
================================================================================
REVENUEOS - REVENUE LEAK DETECTION & AUTONOMOUS RECOVERY PLATFORM
STAGE 8 DEMONSTRATION RUNNER
================================================================================
[INFO] Resetting and reseeding synthetic test database...
[OK] Seeded 5 merchants and baseline telemetry across 1,000+ transactions.
[INFO] Executing Revenue Leak Detection Engine...
[OK] Detected 12 active revenue leaks. Gross Revenue at Risk: INR 184,500.00.
[INFO] Scoring Recovery Opportunities via ML Model...
[OK] Prioritized 8 high-confidence opportunities. Expected Value: INR 122,450.00.

--------------------------------------------------------------------------------
RUNNING CANONICAL GOLDEN SCENARIO (10-Step Full Pipeline)
--------------------------------------------------------------------------------
[STEP 1/10] Ingest Transaction & Failure ..................... [PASS]
[STEP 2/10] Detect Revenue Leak (UPI Route Degradation) ...... [PASS]
[STEP 3/10] Score ML Recovery Opportunity (P_rec = 91%) ..... [PASS]
[STEP 4/10] AI Agent Investigation & Recommendation ......... [PASS]
[STEP 5/10] Deterministic Policy Gate Evaluation (Rule 1-5) . [PASS]
[STEP 6/10] Dispatch Razorpay Test Mode Payment Link ........ [PASS]
[STEP 7/10] Ingest HMAC-SHA256 Payment Webhook .............. [PASS]
[STEP 8/10] Reconcile Transaction & Provider State .......... [PASS]
[STEP 9/10] Confirm Verified Recovery Status ................ [PASS]
[STEP 10/10] Calculate Transparent Financial ROI ............ [PASS]

GOLDEN SCENARIO RESULT:
  * Recovered Revenue: INR 9,500.00 (VERIFIED)
  * System Cost:       INR 15.00
  * Net ROI:           632.3x
...
================================================================================
DEMONSTRATION COMPLETE - ALL SCENARIOS PASSED
================================================================================
```

---

## 2. Interactive Web Dashboard Demonstration

### Step 1: Start the Backend Server
```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 2: Open the Dashboard
Navigate your browser to:
`http://localhost:8000/dashboard`

### Step 3: Executive Tour Navigation
1. **Overview Dashboard**:
   - Inspect the **9-Stage Recovery Funnel** showing drop-off and conversion at each phase.
   - Review the **18 Operational & Financial KPIs** (Gross RAR, Detection Rate, Provider Success Rate, Net ROI).
   - Inspect the **Revenue Leak Categories Breakdown** and **System Latency Benchmarks**.

2. **Forensic Investigation Drawer (4 Tabs)**:
   - Click on any opportunity or leak card in the list to trigger the slide-out drawer.
   - **Tab 1: Telemetry & Action**: Real-time transaction diagnostics, gateway error codes, and recommended action.
   - **Tab 2: 10 Diagnostic Q&As**: Answers the 10 critical operational questions (WHAT happened, WHY leak, HOW confident, WHY recommended, etc.).
   - **Tab 3: AI & Policy Rationale**: Displays the AI structured dossier (Problem, Evidence, Diagnosis, Confidence) alongside the Deterministic Policy Engine evaluation table.
   - **Tab 4: Timeline & Audit**: Chronological timeline of events with exact timestamps and causal audit trace IDs.

3. **Interactive Scenario Launcher**:
   - Click the **"Run Demo Scenarios"** button in the header.
   - Select any scenario card (**Golden Pipeline**, or **Scenarios A through H**).
   - Watch the live execution stream step-by-step with state verification and financial confirmation.

---

## 3. Detailed Talking Points for Demonstration Scenarios

| Scenario | Title | Key Talking Point for Evaluators |
| :--- | :--- | :--- |
| **Golden** | Canonical 10-Step Pipeline | Shows the complete lifecycle from transaction failure to verified INR 9,500 recovery with a 632.3x ROI. |
| **Scenario A** | Successful Recovery | Demonstrates UPI transient failure recovery via 1-click Razorpay payment link. |
| **Scenario B** | Policy Engine Rejection | **Safety First**: AI attempts to recover an unverified INR 650,000 transaction. Policy Rule 5 strictly denies execution; provider API is NEVER called. |
| **Scenario C** | Approval Required Gate | High-value INR 85,000 transaction pauses for human-in-the-loop sign-off before dispatch. |
| **Scenario D** | Provider Timeout & Fallback | Gateway returns 504 timeout; system safely catches the error, marks it failed, and routes to alternative rail (INR 3,499 recovered). |
| **Scenario E** | Duplicate Webhook Protection | Replayed webhook with identical event ID is recognized as an `idempotent_duplicate`. Zero duplicate mutations or double-credits occur. |
| **Scenario F** | Amount Mismatch Refusal | Provider reports INR 3,000 for an expected INR 5,000 transaction. Reconciliation engine flags `RECONCILIATION_REQUIRED` and refuses verification. |
| **Scenario G** | False Positive Suppression | Closed account with 8% ML probability is suppressed, protecting merchant messaging budget. |
| **Scenario H** | High-Value ARR Protection | Enterprise subscription mandate failure (INR 45,000) is restored via 1-click link, securing INR 540,000 annual ARR. |

---

## 4. Troubleshooting & FAQ

* **Q: Is real money moved during the demo?**
  * *A: Strictly NO.* RevenueOS runs in **Razorpay Test/Sandbox Mode** using `rzp_test_*` credentials. No live banking networks or cards are ever charged.
* **Q: Why are amounts formatted in INR?**
  * *A: RevenueOS is purpose-built for the Indian payments ecosystem (UPI, Netbanking, Cards, Mandates).*
* **Q: How is data reset between demos?**
  * *A: Click "Reset Demo Data" in the dashboard header or call `POST /api/v1/demo/reset` with a fixed seed.*
