"""
main.py — End-to-End Batch Runner for RecoverAI

Executes the full agent lifecycle on subscriptions:
  Failed subscription
    → Context enrichment & stopping rules (deterministic)
    → AI recovery decision (LLM)
    → Merchant policy validation (deterministic)
    → Execution & outcome simulation
    → State transitions & append-only audit trail
    → Counterfactual comparison vs. Naive Retry baseline
    → Metrics computation, CSV export & HTML report generation
"""

import json
import os
import sys

# Ensure UTF-8 output encoding on Windows stdout
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from baseline.naive_retry import run_baseline
from agent.stopping_rules import evaluate
from agent.decision_agent import decide
from agent.policy_gate import validate
from agent.executor import execute
from evaluation.counterfactual import compare
from core.metrics import compute
from core import state, audit
from ui.report import generate_report


def run_batch(test_mode: bool = True):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    subs_path = os.path.join(base_dir, "data", "subscriptions.json")
    model_path = os.path.join(base_dir, "data", "outcome_model.json")
    reports_dir = os.path.join(base_dir, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    print("=" * 70)
    print("RECOVERAI - AUTONOMOUS SUBSCRIPTION REVENUE RECOVERY BATCH RUN")
    print("=" * 70)

    # 1. Initialize State and Audit DB
    state.init_db()
    audit.init_db()
    print("[+] State Machine & Audit Log databases initialized (recoverai.db)")

    # 2. Load Dataset & Model
    with open(subs_path, "r", encoding="utf-8") as f:
        subscriptions = json.load(f)
    with open(model_path, "r", encoding="utf-8") as f:
        outcome_model = json.load(f)
    print(f"[+] Loaded {len(subscriptions)} subscription records and outcome model")

    # 3. Run Naive Retry Baseline
    print("\n--- Running Naive Retry Baseline ---")
    baseline_results = run_baseline(subscriptions, outcome_model)
    print(f"[+] Baseline finished: {baseline_results['recovered']}/{len(subscriptions)} recovered "
          f"(Revenue: Rs. {baseline_results['revenue_recovered']:,})")

    # 4. Run RecoverAI Agent Loop
    print("\n--- Running RecoverAI Agent Loop ---")
    recoverai_results = []
    audit_events = []

    stopped_count = 0
    escalated_count = 0
    actioned_count = 0

    for sub in subscriptions:
        sub_id = sub["subscription_id"]
        fc = sub["failure_code"]
        tier = sub["tier"]
        amount = sub["amount"]

        # 4.1 State: FAILED
        state.create_record(sub)

        # 4.2 State: DIAGNOSING
        state.transition(sub_id, "DIAGNOSING", {"failure_code": fc})

        # 4.3 Safety Gate: Stopping Rules
        stopping = evaluate(sub)
        if stopping.triggered:
            audit.log(sub_id, "STOPPING_RULE_FIRED", {
                "rule": stopping.rule_name,
                "disposition": stopping.disposition,
                "reason": stopping.reason,
            })

            target_state = stopping.disposition if stopping.disposition in ("STOPPED", "ESCALATED") else "STOPPED"
            state.transition(sub_id, target_state, {"reason": stopping.reason})

            if target_state == "STOPPED":
                stopped_count += 1
            else:
                escalated_count += 1

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

        audit.log(sub_id, "STOPPING_RULE_FIRED", {"disposition": "clear"})

        # 4.4 State: DECIDING (LLM Decision)
        state.transition(sub_id, "DECIDING")
        decision = decide(sub)
        audit.log(sub_id, "DECISION_MADE", {
            "action": decision["action"],
            "timing_days": decision["timing_days"],
            "channel": decision["channel"],
            "rationale": decision["rationale"],
        })

        # 4.5 Policy Validation (Merchant Gate)
        validated = validate(decision, sub)
        audit.log(sub_id, "POLICY_VALIDATED", {
            "policy_approved": validated["policy_approved"],
            "policy_note": validated["policy_note"],
            "final_action": validated["action"],
        })

        # 4.6 State: ACTING (Execution)
        state.transition(sub_id, "ACTING", {"action": validated["action"]})
        exec_res = execute(validated, sub, test_mode=test_mode)
        audit.log(sub_id, "ACTION_EXECUTED", {
            "action_taken": exec_res["action_taken"],
            "simulated": exec_res["simulated"],
            "outcome_probability": exec_res["outcome_probability"],
        })

        # 4.7 State: MONITORING & Final Disposition
        state.transition(sub_id, "MONITORING")
        outcome = exec_res["outcome"]
        audit.log(sub_id, "OUTCOME_RECORDED", {
            "outcome": outcome,
            "probability": exec_res["outcome_probability"],
        })

        final_state = "RECOVERED" if outcome == "SUCCESS" else "STOPPED"
        state.transition(sub_id, final_state, {"outcome": outcome})
        actioned_count += 1

        recoverai_results.append({
            "subscription_id": sub_id,
            "amount": amount,
            "failure_code": fc,
            "tier": tier,
            "action": validated["action"],
            "timing_days": validated["timing_days"],
            "outcome": outcome,
            "attempts": 1,
            "rationale": validated["rationale"],
        })

    print(f"[+] RecoverAI loop finished across {len(subscriptions)} cases:")
    print(f"  - Actioned with AI Strategy: {actioned_count}")
    print(f"  - Proactively Stopped:       {stopped_count}")
    print(f"  - Escalated to Merchant:     {escalated_count}")

    # 5. Fetch Full Audit Events
    for sub in subscriptions:
        audit_events.extend(audit.get_events(sub["subscription_id"]))

    # 6. Counterfactual Evaluation
    print("\n--- Computing Counterfactual Comparison & Metrics ---")
    cf_data = compare(recoverai_results, baseline_results["per_subscription"])
    metrics_data = compute(recoverai_results, baseline_results, audit_events)

    # 7. Exports
    audit_csv = os.path.join(reports_dir, "audit_log.csv")
    audit.export_csv(audit_csv)
    print(f"[+] Exported complete audit trail to {audit_csv}")

    report_html = generate_report(os.path.join(reports_dir, "recovery_report.html"))
    print(f"[+] Generated merchant HTML report at {report_html}")

    # 8. Executive Summary Output
    s = cf_data["summary"]
    print("\n" + "=" * 70)
    print("EXECUTIVE SUMMARY & VALUE DEMONSTRATION")
    print("=" * 70)
    print(f"  Total Subscriptions Evaluated:     {s['total']}")
    print(f"  RecoverAI Recovered:               {s['recoverai_recovered']} ({metrics_data['recovery_rate']*100:.1f}%)")
    print(f"  Baseline Recovered:                {s['baseline_recovered']} ({metrics_data['baseline_recovery_rate']*100:.1f}%)")
    print(f"  Net Recovery Lift:                 {s['recovery_lift']:+d} ({s['recovery_lift_pct']:+.1f}%)")
    print("  ------------------------------------------------------------------")
    print(f"  RecoverAI Revenue Recovered:       Rs. {metrics_data['revenue_recovered']:,}")
    print(f"  Baseline Revenue Recovered:        Rs. {metrics_data['baseline_revenue_recovered']:,}")
    print(f"  Incremental Revenue Created:       Rs. {metrics_data['incremental_revenue']:,}")
    print("  ------------------------------------------------------------------")
    print(f"  Baseline Wasted Retry Attempts:    {s['baseline_unnecessary_actions']}")
    print(f"  RecoverAI Wasted Actions:          {s['recoverai_unnecessary_actions']}")
    print(f"  Spam/Wasted Contact Avoided:       {s['baseline_unnecessary_actions'] - s['recoverai_unnecessary_actions']} attempts saved")
    print(f"  Safety-First Proactive Stops:      {s['recoverai_stopped_proactively']}")
    print("=" * 70)
    print("To view the interactive Streamlit dashboard, run:")
    print("  streamlit run ui/dashboard.py")
    print("=" * 70)


if __name__ == "__main__":
    run_batch()
