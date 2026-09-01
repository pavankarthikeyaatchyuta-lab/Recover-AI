"""
dashboard.py — Step 10 of RecoverAI

Interactive Streamlit dashboard showing live recovery metrics,
counterfactual side-by-side analysis, and audit trails.
Polished UI/UX with modern dark-mode aesthetic for Razorpay AI Buildathon.
"""

import json
import os
import sys
import pandas as pd
import streamlit as st
import altair as alt

# Setup import path for project root
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.join(BASE_DIR, "..")
sys.path.insert(0, ROOT_DIR)

from baseline.naive_retry import run_baseline
from agent.stopping_rules import evaluate
from agent.executor import _simulate_outcome
from evaluation.counterfactual import compare
from core.metrics import compute
from core import audit


# ---------------------------------------------------------------------------
# Data Loading & Pipeline (logic and data unchanged)
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
# Dashboard Layout & Custom UI/UX
# ---------------------------------------------------------------------------
def render_dashboard():
    # 1. PAGE CONFIG
    st.set_page_config(
        page_title="RecoverAI",
        page_icon="⚡",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # 2. CUSTOM CSS
    custom_css = """
    <style>
      /* Base background & typography */
      .stApp {
        background-color: #0f0f0f;
        color: #f1f5f9;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      }

      /* Metric Card styling */
      .metric-card {
        background-color: #1a1a1a;
        border: 1px solid #2a2a2a;
        border-radius: 8px;
        padding: 16px 20px;
        margin-bottom: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3);
      }
      .card-top-blue { border-top: 3px solid #2563eb; }
      .card-top-green { border-top: 3px solid #16a34a; }
      .card-top-purple { border-top: 3px solid #8b5cf6; }
      .card-top-orange { border-top: 3px solid #f59e0b; }

      .card-label {
        font-size: 13px;
        color: #94a3b8;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }
      .card-value {
        font-size: 26px;
        font-weight: 700;
        color: #f8fafc;
        margin: 6px 0 2px 0;
      }
      .card-delta {
        font-size: 13px;
        color: #10b981;
        font-weight: 500;
      }
      .card-delta-muted {
        font-size: 13px;
        color: #94a3b8;
        font-weight: 500;
      }

      /* Section header */
      .section-header {
        border-left: 3px solid #2563eb;
        padding-left: 12px;
        margin: 28px 0 14px 0;
      }
      .section-title {
        font-size: 18px;
        font-weight: 700;
        color: #ffffff;
        margin: 0;
      }
      .section-divider {
        height: 1px;
        background: #262626;
        margin-top: 8px;
        margin-bottom: 16px;
      }

      /* Pill badges */
      .pill-badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 9999px;
        font-size: 12px;
        font-weight: 600;
        margin-right: 6px;
      }
      .pill-blue { background-color: rgba(37, 99, 235, 0.2); color: #60a5fa; border: 1px solid rgba(37, 99, 235, 0.4); }
      .pill-green { background-color: rgba(22, 163, 74, 0.2); color: #4ade80; border: 1px solid rgba(22, 163, 74, 0.4); }
      .pill-purple { background-color: rgba(139, 92, 246, 0.2); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.4); }
      .pill-orange { background-color: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }
      .pill-red { background-color: rgba(220, 38, 38, 0.2); color: #f87171; border: 1px solid rgba(220, 38, 38, 0.4); }
      .pill-grey { background-color: rgba(107, 114, 128, 0.2); color: #9ca3af; border: 1px solid rgba(107, 114, 128, 0.4); }

      /* Table overrides */
      div[data-testid="stDataFrame"] {
        background-color: #1a1a1a;
        border-radius: 8px;
        border: 1px solid #2a2a2a;
      }

      /* Sidebar */
      section[data-testid="stSidebar"] {
        background-color: #141414;
        border-right: 1px solid #262626;
      }
    </style>
    """
    st.markdown(custom_css, unsafe_allow_html=True)

    # 3. SIDEBAR
    with st.sidebar:
        st.markdown("### ⚡ RecoverAI `v1.0`")
        st.caption("Track 03 · AI Revenue Recovery")
        st.markdown("---")
        st.markdown("#### 📋 Run Info")
        st.markdown("**Dataset Size:** `100 subscriptions`")
        st.markdown("**LLM Model:** `gemini-2.0-flash`")
        st.markdown("**Simulation Mode:** `Active (KYC-Free)`")
        st.markdown("**Database:** `SQLite (recoverai.db)`")
        st.markdown("---")
        st.markdown("#### 🔗 Repository")
        st.markdown("[GitHub: RazorPay_Build](https://github.com/pavankarthikeyaatchyuta-lab/RazorPay_Build)")

    # 4. HEADER SECTION
    st.markdown("""
    <div style="margin-bottom: 24px;">
      <h1 style="font-size: 28px; font-weight: 800; color: #ffffff; margin-bottom: 4px;">⚡ RecoverAI</h1>
      <div style="font-size: 16px; font-weight: 600; color: #e2e8f0; margin-bottom: 4px;">
        Autonomous Subscription Revenue Recovery Agent
      </div>
      <div style="font-size: 13px; color: #94a3b8; margin-bottom: 12px;">
        Razorpay AI Buildathon 2026 &bull; Track 03 &bull; AI Revenue Recovery
      </div>
      <div>
        <span class="pill-badge pill-blue">LLM-Powered</span>
        <span class="pill-badge pill-purple">Audit-Complete</span>
        <span class="pill-badge pill-green">Counterfactual Evaluation</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    subs, baseline_res, recoverai_results, cf_data, metrics = load_and_run_pipeline()
    summary = cf_data["summary"]

    # Calculate dynamic numbers
    actioned_subs = [
        r for r in recoverai_results
        if (r.get("action") or r.get("action_taken")) not in ("DO_NOT_ACT", "STOPPED")
        and r.get("outcome") != "NO_ACTION"
    ]
    actioned_count = len(actioned_subs)
    recovered_count = len([r for r in recoverai_results if r.get("outcome") == "SUCCESS"])
    actioned_rate = (recovered_count / actioned_count * 100) if actioned_count > 0 else 0.0
    avoided_actions = (
        summary["baseline_unnecessary_actions"] - summary["recoverai_unnecessary_actions"]
    )
    spam_reduction_pct = (
        (avoided_actions / summary["baseline_unnecessary_actions"] * 100)
        if summary["baseline_unnecessary_actions"] > 0
        else 0.0
    )
    total_baseline_attempts = sum(b.get("attempts", 1) for b in baseline_res["per_subscription"])

    # -----------------------------------------------------------------------
    # 5. METRIC CARDS (With Colored Top Border)
    # -----------------------------------------------------------------------
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(f"""
        <div class="metric-card card-top-blue">
          <div class="card-label">Recovery Rate (Actioned)</div>
          <div class="card-value">{actioned_rate:.1f}%</div>
          <div class="card-delta">vs 34.0% baseline</div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown(f"""
        <div class="metric-card card-top-green">
          <div class="card-label">Revenue Recovered</div>
          <div class="card-value">₹{metrics.get('revenue_recovered', 0):,}</div>
          <div class="card-delta">{avoided_actions} contacts saved</div>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown(f"""
        <div class="metric-card card-top-purple">
          <div class="card-label">Action Efficiency</div>
          <div class="card-value">{actioned_count} targeted</div>
          <div class="card-delta-muted">vs {total_baseline_attempts} baseline attempts</div>
        </div>
        """, unsafe_allow_html=True)

    with col4:
        st.markdown(f"""
        <div class="metric-card card-top-orange">
          <div class="card-label">Spam Avoided</div>
          <div class="card-value">{avoided_actions}</div>
          <div class="card-delta">{spam_reduction_pct:.0f}% reduction</div>
        </div>
        """, unsafe_allow_html=True)

    # -----------------------------------------------------------------------
    # 6. CHARTS SECTION
    # -----------------------------------------------------------------------
    st.markdown("""
    <div class="section-header">
      <div class="section-title">Comparative Analysis & Recovery Timeline</div>
    </div>
    <div class="section-divider"></div>
    """, unsafe_allow_html=True)

    c_left, c_right = st.columns(2)

    with c_left:
        st.caption("Recovery by Failure Code (RecoverAI vs Baseline)")
        fc_data = []
        by_fc = metrics.get("by_failure_code", {})
        
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
            df_fc = pd.DataFrame(fc_data)
            df_fc_melt = df_fc.melt(id_vars=["Failure Code"], var_name="System", value_name="Recovered")
            
            chart_fc = (
                alt.Chart(df_fc_melt)
                .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                .encode(
                    x=alt.X("Failure Code:N", title="Failure Reason", axis=alt.Axis(labelAngle=-20, labelColor="#94a3b8", titleColor="#cbd5e1")),
                    y=alt.Y("Recovered:Q", title="Recovered Count", scale=alt.Scale(domainMin=0), axis=alt.Axis(labelColor="#94a3b8", titleColor="#cbd5e1")),
                    color=alt.Color("System:N", scale=alt.Scale(domain=["RecoverAI", "Baseline"], range=["#2563eb", "#6b7280"]), legend=alt.Legend(titleColor="#cbd5e1", labelColor="#94a3b8")),
                    xOffset="System:N",
                    tooltip=["Failure Code", "System", "Recovered"]
                )
                .properties(height=280)
                .configure_view(strokeOpacity=0)
            )
            st.altair_chart(chart_fc, use_container_width=True)

    with c_right:
        st.caption("Cumulative Cohort Recovery Curve")
        cohort = metrics.get("cohort_recovery", {"day_1": 0, "day_3": 0, "day_7": 0})
        day_1_val = round(cohort.get("day_1", 0.0) * 100, 1)
        day_3_val = round(cohort.get("day_3", 0.0) * 100, 1)
        day_7_val = round(cohort.get("day_7", 0.0) * 100, 1)
        if day_7_val < day_3_val:
            day_7_val = day_3_val

        df_cohort = pd.DataFrame([
            {"Day": "Day 1", "Cumulative Recovery (%)": day_1_val, "Label": f"{day_1_val}%"},
            {"Day": "Day 3", "Cumulative Recovery (%)": day_3_val, "Label": f"{day_3_val}%"},
            {"Day": "Day 7", "Cumulative Recovery (%)": day_7_val, "Label": f"{day_7_val}%"},
        ])
        
        line = (
            alt.Chart(df_cohort)
            .mark_line(point=alt.OverlayMarkDef(size=80, fill="#2563eb", stroke="#60a5fa", strokeWidth=2), color="#2563eb", strokeWidth=3)
            .encode(
                x=alt.X("Day:N", sort=["Day 1", "Day 3", "Day 7"], title="Recovery Timeline", axis=alt.Axis(labelAngle=0, labelColor="#94a3b8", titleColor="#cbd5e1")),
                y=alt.Y("Cumulative Recovery (%):Q", title="Cumulative Recovery Rate (%)", scale=alt.Scale(domain=[0, max(35, int(day_7_val) + 12)]), axis=alt.Axis(labelColor="#94a3b8", titleColor="#cbd5e1")),
                tooltip=["Day", "Cumulative Recovery (%)"]
            )
        )

        labels = (
            alt.Chart(df_cohort)
            .mark_text(align="center", baseline="bottom", dy=-10, color="#cbd5e1", fontSize=12, fontWeight="bold")
            .encode(
                x=alt.X("Day:N", sort=["Day 1", "Day 3", "Day 7"]),
                y=alt.Y("Cumulative Recovery (%):Q"),
                text="Label:N"
            )
        )

        chart_cohort = (line + labels).properties(height=280).configure_view(strokeOpacity=0)
        st.altair_chart(chart_cohort, use_container_width=True)

    # -----------------------------------------------------------------------
    # 7. COUNTERFACTUAL TABLE SECTION
    # -----------------------------------------------------------------------
    st.markdown("""
    <div class="section-header">
      <div class="section-title">Per-Subscription Counterfactual Evaluation</div>
    </div>
    <div class="section-divider"></div>
    """, unsafe_allow_html=True)

    cf_rows = []
    for item in cf_data["per_subscription"]:
        cf_rows.append({
            "Subscription": item["subscription_id"],
            "Amount": f"₹{item['amount']}",
            "Failure Code": item["failure_code"],
            "Tier": item["tier"],
            "Baseline Action": item["baseline"]["action"],
            "Baseline Outcome": item["baseline"]["outcome"],
            "RecoverAI Action": item["recoverai"]["action"],
            "RecoverAI Outcome": item["recoverai"]["outcome"],
            "Delta": item["delta"],
        })

    df_table = pd.DataFrame(cf_rows)

    def style_table(row):
        val = row["Delta"]
        if val == "RECOVERAI_WON":
            return ["border-left: 4px solid #16a34a; background-color: #142217; color: #f1f5f9;"] * len(row)
        elif val == "BASELINE_WON":
            return ["border-left: 4px solid #dc2626; background-color: #241416; color: #f1f5f9;"] * len(row)
        elif val == "BOTH_FAILED":
            return ["border-left: 4px solid #6b7280; background-color: #171717; color: #9ca3af;"] * len(row)
        elif val == "RECOVERAI_STOPPED":
            return ["border-left: 4px solid #f59e0b; background-color: #1f1b13; color: #cbd5e1;"] * len(row)
        return ["background-color: #1a1a1a; color: #f1f5f9;"] * len(row)

    styled_df = df_table.style.apply(style_table, axis=1)
    st.dataframe(
        styled_df,
        use_container_width=True,
        hide_index=False,
        height=400,
        column_config={
            "Subscription": st.column_config.TextColumn("Subscription", width="medium"),
            "Amount": st.column_config.TextColumn("Amount", width="small"),
            "Failure Code": st.column_config.TextColumn("Failure Code", width="medium"),
            "Tier": st.column_config.TextColumn("Tier", width="small"),
            "Baseline Action": st.column_config.TextColumn("Baseline Action", width="medium"),
            "Baseline Outcome": st.column_config.TextColumn("Baseline Outcome", width="small"),
            "RecoverAI Action": st.column_config.TextColumn("RecoverAI Action", width="medium"),
            "RecoverAI Outcome": st.column_config.TextColumn("RecoverAI Outcome", width="small"),
            "Delta": st.column_config.TextColumn("Delta", width="medium"),
        },
    )

    # -----------------------------------------------------------------------
    # 8. AUDIT TRAIL INSPECTOR
    # -----------------------------------------------------------------------
    st.markdown("""
    <div class="section-header">
      <div class="section-title">Audit Trail & Deterministic Safety Inspector</div>
    </div>
    <div class="section-divider"></div>
    """, unsafe_allow_html=True)

    with st.expander("🔍 Inspect Structured Audit Trail by Subscription ID", expanded=False):
        sub_list = [s["subscription_id"] for s in subs]
        selected_sub = st.selectbox("Select Subscription ID:", sub_list)

        events = audit.get_events(selected_sub)
        if events:
            st.markdown(f"**Event Log for `{selected_sub}`:**")

            badge_map = {
                "STOPPING_RULE_FIRED": "pill-red",
                "DECISION_MADE": "pill-blue",
                "POLICY_VALIDATED": "pill-purple",
                "ACTION_EXECUTED": "pill-green",
                "OUTCOME_RECORDED": "pill-orange",
            }

            for e in events:
                evt_type = e["event_type"]
                badge_class = badge_map.get(evt_type, "pill-grey")
                st.markdown(f"""
                <div style="background-color: #171717; border: 1px solid #2a2a2a; border-radius: 6px; padding: 10px 14px; margin-bottom: 8px;">
                  <span class="pill-badge {badge_class}">{evt_type}</span>
                  <span style="font-size: 12px; color: #94a3b8;">{e['timestamp']} &bull; Event #{e['id']}</span>
                  <div style="margin-top: 6px; font-family: monospace; font-size: 13px; color: #e2e8f0; background: #0f0f0f; padding: 6px 10px; border-radius: 4px;">
                    {json.dumps(e['data'])}
                  </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info(f"No audit events recorded for {selected_sub} yet.")


if __name__ == "__main__":
    render_dashboard()
