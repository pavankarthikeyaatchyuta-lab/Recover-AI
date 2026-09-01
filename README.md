# ⚡ RecoverAI — Autonomous Subscription Revenue Recovery Agent

> **Razorpay AI Buildathon 2026 — Track 03: AI Revenue Recovery**  
> Build-to-Hire Project | AI Builder Internship Candidate Track (₹75,000/month, Bangalore)

---

## 📌 Executive Summary

Recurring subscription payments fail for diverse reasons — **insufficient funds**, **expired cards**, **revoked mandates**, **network timeouts**, or **UPI failures**. Most existing payment systems either:
1. **Retry blindly** (spamming customers with 3 instant retries, burning trust, triggering interchange fees), or
2. **Give up prematurely** without understanding the customer's context or payment cadence.

**RecoverAI** is an intelligent, context-aware revenue recovery agent built specifically for Indian and global recurring payment ecosystems (Cards, UPI AutoPay, e-Mandates, Netbanking). It diagnoses **why** a payment failed, enriches the transaction with rich customer behavioral signals, applies deterministic safety gates, uses an LLM to formulate tailored recovery strategies, executes actions through Razorpay APIs, and honestly benchmarks its performance against a naive retry baseline.

> ℹ️ **Note on Razorpay Integration:** Razorpay test-mode API integration is fully implemented in `api/razorpay_client.py`. The batch runner uses simulated responses (`TEST_MODE=true`) since account verification requires PAN. The API wrapper is production-ready and can be activated by setting `TEST_MODE=false` with valid test-mode credentials.

---

## 🎯 Core Agent Loop

```
Failed Subscription
  │
  ▼
[1] Context Enrichment (tenure, historical recovery velocity, payday signals, tier, failure code)
  │
  ▼
[2] Hard Safety Gates (deterministic stopping rules — run BEFORE the AI)
  │   ├── STOPPED   ──> Prevents harassment & over-contact; logs reason
  │   ├── ESCALATED ──> Escalates high-value / intent-drop signals to merchant
  │   └── CLEAR     ──> Proceeds to AI strategy
  ▼
[3] AI Recovery Decision (LLM reasons over action, timing_days, channel & rationale)
  │
  ▼
[4] Merchant Policy Gate (verifies downgrade eligibility, discount caps & allowed channels)
  │
  ▼
[5] Action Execution (Razorpay Test-Mode APIs: Payment Links, Invoices, Orders)
  │
  ▼
[6] Outcome Monitoring & State Transitions (SQLite FSM + Append-Only Audit Trail)
  │
  ▼
[7] Counterfactual Evaluation & Reporting (Side-by-side vs Naive Retry baseline)
```

---

## 🧠 Key Design Principles

1. **Deterministic Rules Handle What Deterministic Rules Should Handle:**
   - Failure code classification, attempt count capping, cooldown enforcement, and merchant policy checks are **100% hardcoded**. The LLM is **never** used for safety-critical guardrails.
2. **Narrow & Focused LLM Scope:**
   - The LLM is strictly tasked with: **recovery strategy**, **timing offset**, **outreach channel selection**, and **plain-English rationale generation**.
3. **`DO_NOT_ACT` is a First-Class Output:**
   - The agent knows when *not* to contact a customer. Involuntary churn prevention means not badgering chronic non-payers or customers in a cooldown period.
4. **Honest Counterfactual Evaluation:**
   - Evaluated on the exact same 100-record dataset and identical probability outcome model as a **Naive 3-Attempt Immediate Retry Baseline**.
   - Side-by-side comparison honestly tracks **`BASELINE_WON`** alongside **`RECOVERAI_WON`**.
5. **Full Auditability:**
   - Every state transition, stopping rule trigger, LLM rationale, policy substitution, and API call is written to an append-only SQLite audit log and exportable to CSV.

---

## 📊 Comparison: RecoverAI vs. Naive Retry Baseline

| Feature | Naive Retry Baseline | RecoverAI |
| :--- | :--- | :--- |
| **Strategy** | Fixed 3x immediate retries for all failures | Context-aware strategy tailored to failure reason |
| **Payday Awareness** | ❌ None (retries regardless of customer payday) | ✅ Detects salary/payday window and delays retries accordingly |
| **Card Expiry Handling** | ❌ Blindly retries expired token | ✅ Issues Razorpay Payment Link for new card capture |
| **Mandate Revocations** | ❌ Re-attempts revoked mandate | ✅ Identifies intent signal and escalates to merchant review |
| **Customer Protection** | ❌ Spams at-risk and chronic non-payers | ✅ Enforces early stopping caps to protect brand reputation |
| **Wasted Retries** | ⚠️ High (198 failed contact attempts) | 📉 Low (78% reduction in unnecessary actions) |
| **Merchant Safety** | ❌ Uncontrolled actions | ✅ Enforces discount caps and plan downgrade eligibility |

---

## 📁 Repository Structure

```
recoverai/
├── data/
│   ├── generate_dataset.py       # Step 1: Deterministic 100-record dataset generator (Seed: 42)
│   ├── subscriptions.json        # Primary JSON dataset (100 failed subscriptions)
│   ├── subscriptions.csv         # Human-readable CSV export of subscriptions
│   └── outcome_model.json        # Base probabilities & tier multipliers
├── agent/
│   ├── stopping_rules.py         # Step 2: 6 Hard deterministic safety gates
│   ├── decision_agent.py         # Step 3: Gemini/Claude LLM recovery strategy agent
│   ├── policy_gate.py            # Step 4: Merchant policy & discount rule validation
│   └── executor.py               # Step 5: Test-mode simulation & Razorpay execution
├── api/
│   └── razorpay_client.py        # Step 5: Razorpay test-mode API integration
├── core/
│   ├── state.py                  # Step 6: Finite State Machine (SQLite persistence)
│   ├── audit.py                  # Step 6: Append-only audit log with CSV export
│   └── metrics.py                # Step 9: Recovery rates, efficiency, and cohort analysis
├── baseline/
│   └── naive_retry.py            # Step 7: Naive 3-attempt immediate retry engine
├── evaluation/
│   └── counterfactual.py         # Step 8: Side-by-side comparator (RECOVERAI_WON vs BASELINE_WON)
├── ui/
│   ├── dashboard.py              # Step 10: Streamlit interactive control center
│   └── report.py                 # Step 10: Merchant summary HTML report generator
├── reports/
│   ├── audit_log.csv             # Full event audit export
│   └── recovery_report.html      # Self-contained merchant HTML report
├── recoverai.db                  # SQLite database (State machine & Audit log)
├── main.py                       # End-to-end batch execution pipeline
├── .env.example                  # Environment configuration template
└── README.md                     # Complete project documentation
```

---

## 🧩 Deep Dive into Modules

### 1. Dataset & Outcome Model (`data/`)
- Generates 100 realistic subscription payment failures with a fixed random seed (`42`).
- **Failure Code Distribution**: `INSUFFICIENT_FUNDS` (35%), `CARD_EXPIRED` (20%), `MANDATE_REVOKED` (20%), `NETWORK_ERROR` (15%), `UPI_TIMEOUT` (10%).
- **Customer Tiers**: `regular` (55%), `at_risk` (20%), `high_value` (15%), `first_time` (10%).
- **Payday Signal**: Detects `usual_payment_day` correlated with billing date (e.g. 1st–5th for salary cycles).
- **Outcome Model**: Base recovery probabilities per failure code + action type, multiplied by customer tier weights (e.g. `high_value: 1.15x`, `at_risk: 0.70x`).

### 2. Stopping Rules (`agent/stopping_rules.py`)
Deterministic safety gates that run **before** the LLM. First rule to fire wins:
1. `rule_max_attempts`: Stops if `attempt_count >= 3`.
2. `rule_at_risk_cap`: Stops at-risk customers at `attempt_count >= 2` to prevent over-contact.
3. `rule_mandate_revoked`: Escalates to merchant if mandate revoked with prior attempt (strong churn signal).
4. `rule_chronic_non_payer`: Stops customers with low lifetime success rate (`< 0.70`) and prior attempts.
5. `rule_high_value_first_time`: Escalates high-value accounts (`₹4,999+`) with no established relationship (`tenure <= 2mo`).
6. `rule_cooldown`: Holds action if within 24h of a recent failure (`days_since_failure == 0`).

*Benchmark Result on 100 records:* **70 Clear (Proceed to AI) | 14 Proactively Stopped | 16 Escalated to Merchant**.

### 3. AI Decision Agent (`agent/decision_agent.py`)
- Powered by Google Gemini / Claude via the official `google-genai` SDK.
- Reasons over customer tenure, payment history, preferred channel, and payday signal.
- **Available Actions**:
  - `PAYDAY_RETRY`: Retries on customer's usual payment day (default for `INSUFFICIENT_FUNDS`).
  - `IMMEDIATE_RETRY`: Retries within 24h (restricted to `NETWORK_ERROR` & `UPI_TIMEOUT`).
  - `PAYMENT_LINK`: Issues Razorpay link (for `CARD_EXPIRED` & first-attempt `MANDATE_REVOKED`).
  - `NUDGE`: Sends SMS/WhatsApp reminder without taking payment.
  - `PLAN_DOWNGRADE`: Offers lower plan to retain long-term struggling subscribers.
  - `DO_NOT_ACT`: Intentionally holds action with an auditable justification.
- Includes automated validation guards and deterministic fallbacks.

### 4. Merchant Policy Gate (`agent/policy_gate.py`)
- Ensures the AI cannot violate merchant-configured rules.
- Enforces downgrade eligibility: minimum 6 months tenure, minimum 2 previous failures, maximum 50% discount.
- Automatically substitutes unapproved actions (e.g. invalid `PLAN_DOWNGRADE` becomes `PAYMENT_LINK`).
- Enforces allowed communication channels (`upi`, `card`, `sms`, `whatsapp`, `email`).
- Forces human review for amounts exceeding merchant thresholds (`₹4,999+`).

### 5. Razorpay Execution & Test Mode (`agent/executor.py` + `api/razorpay_client.py`)
- Test-mode outcome simulation powered by `outcome_model.json` with deterministic per-subscription MD5 seeding.
- Live-mode ready: creates test-mode **Razorpay Payment Links**, **Orders**, and **Payment Status Fetches** with paise conversion.

### 6. Finite State Machine & Audit Trail (`core/state.py` + `core/audit.py`)
- Persisted in SQLite with WAL mode (`recoverai.db`).
- Strict lifecycle states: `FAILED` ➔ `DIAGNOSING` ➔ `DECIDING` ➔ `ACTING` ➔ `MONITORING` ➔ `RECOVERED` | `STOPPED` | `ESCALATED`.
- Rejects illegal transitions with `ValueError`.
- Logs structured events: `STOPPING_RULE_FIRED`, `DECISION_MADE`, `POLICY_VALIDATED`, `ACTION_EXECUTED`, `OUTCOME_RECORDED`.

### 7. Evaluation & Metrics (`baseline/`, `evaluation/`, `core/metrics.py`)
- Runs side-by-side counterfactual comparisons against a 3-attempt naive baseline.
- Tracks granular deltas: `RECOVERAI_WON`, `BASELINE_WON`, `BOTH_RECOVERED`, `BOTH_FAILED`, `RECOVERAI_STOPPED`.
- Computes top-line recovery rate, revenue recovered, incremental revenue, intervention efficiency, cohort recovery curves (Day 1 / 3 / 7), and breakdowns by failure code and tier.

### 8. User Interface & Reports (`ui/`)
- **Streamlit Interactive Dashboard (`ui/dashboard.py`)**:
  - Row 1: 4 Top-line KPI Cards.
  - Row 2: Dual charts (Failure Code breakdown & Cohort Recovery Curve).
  - Row 3: Color-coded counterfactual comparison table.
  - Row 4: Expandable interactive Audit Trail inspector.
- **Merchant Summary HTML Report (`ui/report.py`)**:
  - Self-contained, dependency-free HTML report rendered with Jinja2 and inline CSS (`reports/recovery_report.html`).

---

## 🛠️ Installation & Setup

### 1. Clone & Set Up Virtual Environment
```bash
git clone https://github.com/your-username/recoverai.git
cd recoverai

python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate
```

### 2. Install Dependencies
```bash
pip install google-genai razorpay streamlit jinja2 pandas
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Populate your API keys:
```env
GEMINI_API_KEY=your_gemini_api_key_here
LLM_MODEL=gemini-1.5-pro
RAZORPAY_KEY_ID=rzp_test_your_key_id
RAZORPAY_KEY_SECRET=your_key_secret_here
TEST_MODE=true
```

---

## 🚀 Usage Guide

### 1. Run Dataset Generator (Step 1)
```bash
python data/generate_dataset.py
```

### 2. Run Individual Agent Step Tests
```bash
python agent/stopping_rules.py
python agent/decision_agent.py
python agent/policy_gate.py
python agent/executor.py
python core/state.py
python core/audit.py
python baseline/naive_retry.py
python evaluation/counterfactual.py
python core/metrics.py
```

### 3. Run the End-to-End Batch Pipeline
```bash
python main.py
```
*Outputs generated:*
- SQLite database: `recoverai.db`
- Audit log CSV: `reports/audit_log.csv`
- Merchant summary report: `reports/recovery_report.html`

### 4. Launch the Streamlit Dashboard
```bash
python -m streamlit run ui/dashboard.py
```

---

## 📈 Sample Benchmark Output (`main.py`)

```text
======================================================================
RECOVERAI - AUTONOMOUS SUBSCRIPTION REVENUE RECOVERY BATCH RUN
======================================================================
[+] State Machine & Audit Log databases initialized (recoverai.db)
[+] Loaded 100 subscription records and outcome model

--- Running Naive Retry Baseline ---
[+] Baseline finished: 34/100 recovered (Revenue: Rs. 84,466)

--- Running RecoverAI Agent Loop ---
[+] RecoverAI loop finished across 100 cases:
  - Actioned with AI Strategy: 70
  - Proactively Stopped:       14
  - Escalated to Merchant:     16

--- Computing Counterfactual Comparison & Metrics ---
[+] Exported complete audit trail to reports/audit_log.csv
[+] Generated merchant HTML report at reports/recovery_report.html

======================================================================
EXECUTIVE SUMMARY & VALUE DEMONSTRATION
======================================================================
  Total Subscriptions Evaluated:     100
  RecoverAI Recovered:               27 (27.0%)
  Baseline Recovered:                34 (34.0%)
  Net Recovery Lift:                 -7 (-7.0%)
  ------------------------------------------------------------------
  RecoverAI Revenue Recovered:       Rs. 59,973
  Baseline Revenue Recovered:        Rs. 84,466
  Incremental Revenue Created:       Rs. -24,493
  ------------------------------------------------------------------
  Baseline Wasted Retry Attempts:    198
  RecoverAI Wasted Actions:          43
  Spam/Wasted Contact Avoided:       155 attempts saved
  Safety-First Proactive Stops:      30
======================================================================
To view the interactive Streamlit dashboard, run:
  python -m streamlit run ui/dashboard.py
======================================================================
```

---

## 🏆 Razorpay AI Buildathon 2026 Submission

- **Track**: Track 03 — AI Revenue Recovery
- **Project**: RecoverAI (Autonomous Subscription Recovery Agent)
- **Author**: 3rd-Year B.Tech CSE (AI & ML) Student
- **Core Technology Stack**: Python 3.13, Google Gemini (`google-genai`), Razorpay Python SDK, SQLite3, Streamlit, Jinja2, Pandas
