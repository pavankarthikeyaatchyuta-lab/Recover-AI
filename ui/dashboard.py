"""
dashboard.py — Step 10 of RecoverAI

Interactive Streamlit dashboard showing live recovery metrics,
counterfactual side-by-side analysis, and audit trails.
"""

import json
import os
import sys
import pandas as pd
import streamlit as st

# Setup import path for project root
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(BASE_DIR, "..")
sys.path.insert(0, ROOT_DIR)

from baseline.naive_retry import run_baseline
from agent.stopping_rules import evaluate
from agent.executor import _simulate_outcome
from evaluation.counterfactual import compare
from core.metrics import compute
from core import audit, state


# ---------------------------------------------------------------------------
# Data Loading & Pipeline
# ---------------------------------------------------------------------------
@st.cache_data
def load_and_run_pipeline():
    """Load data, run baseline and RecoverAI simulation, and calculate metrics."""
    data_dir = os.path.join(ROOT_DIR, "data")
    subs_file = os.path.join(data_dir, "subscriptions.json")
    model_file = os.path.join(data_dir, "outcome_model.json")

    with open(subs_file, "r", encoding="utf-8") as f:
        subscriptions = json.load(f)
    with open(model_file, "r", encoding="utf-8") as f:
        outcome_model = json.load(f)

    # 1. Baseline
    baseline_res = run_baseline(subscriptions, outcome_model)

    # 2. RecoverAI
    action_map = {
        "INSUFFICIENT_FUNDS": "PAYDAY_RETRY",
        "CARD_EXPIRED": "PAYMENT_LINK",
        "MANDATE_REVOKED": "PAYMENT_LINK",
        "NETWORK_ERROR": "IMMEDIATE_RETRY",
        "UPI_TIMEOUT": "IMMEDIATE_RETRY",
    }

    recoverai_results = []
    audit.init_db()

    for sub in subscriptions:
        sub_id = sub["subscription_id"]
        stopping = evaluate(sub)
        fc = sub["failure_code"]
        tier = sub["tier"]
        amount = sub["amount"]

        if stopping.triggered:
            recoverai_results.append({
                "subscription_id": sub_id,
                "amount": amount,
                "failure_code": fc,
                "tier": tier,
                "action": "DO_NOT_ACT",
                "timing_days": 0,
                "outcome": "NO_ACTION",
                "disposition": stopping.disposition,
                "rationale": stopping.reason,
            })
            continue

        act = action_map.get(fc, "PAYDAY_RETRY")
        outcome, _ = _simulate_outcome(act, fc, tier, sub_id)
        timing = 1 if act == "IMMEDIATE_RETRY" else (3 if act == "PAYDAY_RETRY" else 2)

        recoverai_results.append({
            "subscription_id": sub_id,
            "amount": amount,
            "failure_code": fc,
            "tier": tier,
            "action": act,
            "timing_days": timing,
            "outcome": outcome,
            "attempts": 1,
            "rationale": f"Intelligent {act} execution for {fc}",
        })

    # 3. Counterfactual & Metrics
    cf_data = compare(recoverai_results, baseline_res["per_subscription"])
    all_events = []
    for sub in subscriptions:
        all_events.extend(audit.get_events(sub["subscription_id"]))

    metrics_data = compute(recoverai_results, baseline_res, all_events)

    return subscriptions, baseline_res, recoverai_results, cf_data, metrics_data


# ---------------------------------------------------------------------------
# Dashboard Layout
# ---------------------------------------------------------------------------
def render_dashboard():
    st.set_page_config(
        page_title="RecoverAI — Subscription Revenue Recovery",
        page_icon="⚡",
        layout="wide",
    )

    st.title("⚡ RecoverAI — Autonomous Revenue Recovery Agent")
    st.markdown(
        "**Track 03:** AI Revenue Recovery | Real-time diagnostic & counterfactual evaluation"
    )
    st.markdown("---")

    subs, baseline_res, recoverai_results, cf_data, metrics = load_and_run_pipeline()
    summary = cf_data["summary"]

    # -----------------------------------------------------------------------
    # Row 1 — 4 Metric Cards
    # -----------------------------------------------------------------------
    col1, col2, col3, col4 = st.columns(4)

    avoided_actions = (
        summary["baseline_unnecessary_actions"] - summary["recoverai_unnecessary_actions"]
    )
    lift_pct = summary["recovery_lift_pct"]
    lift_sign = "+" if lift_pct >= 0 else ""

    with col1:
        st.metric(
            label="Recovery Rate",
            value=f"{metrics.get('recovery_rate', 0.0) * 100:.1f}%",
            delta=f"{lift_sign}{lift_pct:.1f}% vs Baseline",
        )
    with col2:
        st.metric(
            label="Revenue Recovered",
            value=f"₹{metrics.get('revenue_recovered', 0):,}",
            delta=f"₹{metrics.get('incremental_revenue', 0):,} Incremental",
        )
    with col3:
        st.metric(
            label="Recovery Lift",
            value=f"{lift_sign}{summary['recovery_lift']} Subs",
            delta=f"Baseline: {summary['baseline_recovered']}",
        )
    with col4:
        st.metric(
            label="Unnecessary Actions Avoided",
            value=f"{avoided_actions}",
            delta=f"{summary['recoverai_unnecessary_actions']} total wasted",
            delta_color="inverse",
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # -----------------------------------------------------------------------
    # Row 2 — Charts (Bar Chart & Cohort Recovery Curve)
    # -----------------------------------------------------------------------
    c_left, c_right = st.columns(2)

    with c_left:
        st.subheader("📊 Recovery by Failure Code (RecoverAI vs Baseline)")
        fc_data = []
        by_fc = metrics.get("by_failure_code", {})
        
        # Calculate baseline by failure code
        baseline_fc = {}
        for b in baseline_res["per_subscription"]:
            sub_id = b["subscription_id"]
            sub_match = next((s for s in subs if s["subscription_id"] == sub_id), None)
            if sub_match:
                code = sub_match["failure_code"]
                baseline_fc.setdefault(code, {"total": 0, "recovered": 0})
                baseline_fc[code]["total"] += 1
                if b["outcome"] == "SUCCESS":
                    baseline_fc[code]["recovered"] += 1

        for code, r_stats in by_fc.items():
            b_stats = baseline_fc.get(code, {"recovered": 0, "total": 1})
            fc_data.append({
                "Failure Code": code,
                "RecoverAI": r_stats["recovered"],
                "Baseline": b_stats["recovered"],
            })

        if fc_data:
            df_fc = pd.DataFrame(fc_data).set_index("Failure Code")
            st.bar_chart(df_fc, color=["#10B981", "#6B7280"])

    with c_right:
        st.subheader("📈 Cohort Recovery Curve")
        cohort = metrics.get("cohort_recovery", {"day_1": 0, "day_3": 0, "day_7": 0})
        df_cohort = pd.DataFrame({
            "Day Cohort": ["Day 1", "Day 3", "Day 7"],
            "Cumulative Recovery Rate (%)": [
                cohort["day_1"] * 100,
                cohort["day_3"] * 100,
                cohort["day_7"] * 100,
            ],
        }).set_index("Day Cohort")
        st.line_chart(df_cohort, color="#3B82F6")

    st.markdown("---")

    # -----------------------------------------------------------------------
    # Row 3 — Counterfactual Table
    # -----------------------------------------------------------------------
    st.subheader("⚖️ Per-Subscription Counterfactual Side-by-Side")

    cf_rows = []
    for item in cf_data["per_subscription"]:
        cf_rows.append({
            "subscription_id": item["subscription_id"],
            "amount": f"₹{item['amount']}",
            "failure_code": item["failure_code"],
            "tier": item["tier"],
            "baseline_action": item["baseline"]["action"],
            "baseline_outcome": item["baseline"]["outcome"],
            "recoverai_action": item["recoverai"]["action"],
            "recoverai_outcome": item["recoverai"]["outcome"],
            "delta": item["delta"],
        })

    df_table = pd.DataFrame(cf_rows)

    def highlight_delta(row):
        val = row["delta"]
        if val == "RECOVERAI_WON":
            return ["background-color: rgba(16, 185, 129, 0.2)"] * len(row)
        elif val == "BASELINE_WON":
            return ["background-color: rgba(239, 68, 68, 0.2)"] * len(row)
        elif val == "RECOVERAI_STOPPED":
            return ["background-color: rgba(107, 114, 128, 0.15)"] * len(row)
        return [""] * len(row)

    styled_df = df_table.style.apply(highlight_delta, axis=1)
    st.dataframe(styled_df, use_container_width=True, height=360)

    # -----------------------------------------------------------------------
    # Row 4 — Expandable Audit Trail
    # -----------------------------------------------------------------------
    with st.expander("🔍 Audit Trail & Lifecycle Inspector"):
        sub_list = [s["subscription_id"] for s in subs]
        selected_sub = st.selectbox("Select Subscription ID to inspect audit events:", sub_list)

        events = audit.get_events(selected_sub)
        if events:
            st.markdown(f"**Audit events for `{selected_sub}`:**")
            events_table = [
                {
                    "Event ID": e["id"],
                    "Event Type": e["event_type"],
                    "Timestamp": e["timestamp"],
                    "Data": json.dumps(e["data"]),
                }
                for e in events
            ]
            st.dataframe(pd.DataFrame(events_table), use_container_width=True)
        else:
            st.info(f"No audit events recorded for {selected_sub} yet.")


if __name__ == "__main__":
    render_dashboard()
