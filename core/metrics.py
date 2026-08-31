"""
metrics.py — Step 9 of RecoverAI

Computes comprehensive performance and evaluation metrics from
RecoverAI results, baseline results, and audit log events.
"""

import json
import os
from collections import defaultdict


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def compute(
    recoverai_results: list[dict],
    baseline_results: list[dict] | dict,
    audit_events: list[dict] | None = None,
) -> dict:
    """Compute recovery, revenue, and efficiency metrics.

    Args:
        recoverai_results: List of per-subscription dicts from RecoverAI.
        baseline_results: List of per-subscription dicts or summary dict from naive retry.
        audit_events: List of event dicts from audit_log (optional).

    Returns:
        Dict matching the required metrics schema.
    """
    if audit_events is None:
        audit_events = []

    # Normalize baseline_results if passed as dict from run_baseline
    if isinstance(baseline_results, dict):
        b_list = baseline_results.get("per_subscription", [])
    else:
        b_list = baseline_results

    total = len(recoverai_results)
    if total == 0:
        return {}

    # RecoverAI subsets
    r_recovered = [r for r in recoverai_results if r.get("outcome") == "SUCCESS"]
    r_recovered_count = len(r_recovered)
    recovery_rate = round(r_recovered_count / total, 2)

    revenue_recovered = sum(r.get("amount", 0) for r in r_recovered)

    # Baseline subsets
    b_recovered = [b for b in b_list if b.get("outcome") == "SUCCESS"]
    b_failed = [b for b in b_list if b.get("outcome") != "SUCCESS"]
    b_recovered_count = len(b_recovered)
    baseline_recovery_rate = round(b_recovered_count / total, 2) if total > 0 else 0.0
    baseline_revenue_recovered = sum(b.get("amount", 0) for b in b_recovered)

    # Lift and incremental
    recovery_lift = round(recovery_rate - baseline_recovery_rate, 2)
    incremental_revenue = revenue_recovered - baseline_revenue_recovered

    # Actions and efficiency
    # Active interventions = actions taken excluding DO_NOT_ACT and NO_ACTION/STOPPED
    active_interventions = [
        r for r in recoverai_results
        if (r.get("action") or r.get("action_taken")) not in ("DO_NOT_ACT", "STOPPED", None)
        and r.get("outcome") not in ("NO_ACTION", None)
    ]
    total_actions_taken = len(active_interventions)
    intervention_efficiency = (
        round(r_recovered_count / total_actions_taken, 2)
        if total_actions_taken > 0
        else 0.0
    )

    # Attempts
    avg_attempts_per_recovery = (
        round(sum(r.get("attempts", 1) for r in r_recovered) / r_recovered_count, 1)
        if r_recovered_count > 0
        else 0.0
    )
    baseline_avg_attempts = (
        round(sum(b.get("attempts", 1) for b in b_recovered) / b_recovered_count, 1)
        if b_recovered_count > 0
        else 0.0
    )

    # Unnecessary actions
    unnecessary_actions = sum(
        1 for r in active_interventions if r.get("outcome") != "SUCCESS"
    )
    baseline_unnecessary_actions = sum(b.get("attempts", 0) for b in b_failed)

    # Proactive stops & escalations
    stopped_proactively = sum(
        1 for r in recoverai_results
        if (r.get("action") or r.get("action_taken")) in ("DO_NOT_ACT", "STOPPED")
        or r.get("outcome") == "NO_ACTION"
    )

    # Escalated count from audit events or results
    escalated_set = set()
    for evt in audit_events:
        data = evt.get("data", {})
        if (
            data.get("disposition") == "ESCALATED"
            or evt.get("event_type") == "ESCALATED"
            or "escalat" in str(data.get("reason", "")).lower()
        ):
            escalated_set.add(evt.get("subscription_id"))

    for r in recoverai_results:
        if r.get("disposition") == "ESCALATED" or r.get("outcome") == "ESCALATED":
            escalated_set.add(r.get("subscription_id"))

    escalated_count = len(escalated_set)

    # Cohort recovery by timing_days
    day_1_recovered = sum(1 for r in r_recovered if r.get("timing_days", 0) <= 1)
    day_3_recovered = sum(1 for r in r_recovered if r.get("timing_days", 0) <= 3)
    day_7_recovered = sum(1 for r in r_recovered if r.get("timing_days", 0) <= 7)

    cohort_recovery = {
        "day_1": round(day_1_recovered / total, 2),
        "day_3": round(day_3_recovered / total, 2),
        "day_7": round(day_7_recovered / total, 2),
    }

    # By failure code
    fc_groups = defaultdict(lambda: {"total": 0, "recovered": 0})
    for r in recoverai_results:
        fc = r.get("failure_code", "UNKNOWN")
        fc_groups[fc]["total"] += 1
        if r.get("outcome") == "SUCCESS":
            fc_groups[fc]["recovered"] += 1

    by_failure_code = {}
    for fc, stats in fc_groups.items():
        tot = stats["total"]
        rec = stats["recovered"]
        by_failure_code[fc] = {
            "total": tot,
            "recovered": rec,
            "rate": round(rec / tot, 2) if tot > 0 else 0.0,
        }

    # By tier
    tier_groups = defaultdict(lambda: {"total": 0, "recovered": 0})
    for r in recoverai_results:
        tier = r.get("tier", "UNKNOWN")
        tier_groups[tier]["total"] += 1
        if r.get("outcome") == "SUCCESS":
            tier_groups[tier]["recovered"] += 1

    by_tier = {}
    for tier, stats in tier_groups.items():
        tot = stats["total"]
        rec = stats["recovered"]
        by_tier[tier] = {
            "total": tot,
            "recovered": rec,
            "rate": round(rec / tot, 2) if tot > 0 else 0.0,
        }

    return {
        "recovery_rate": recovery_rate,
        "baseline_recovery_rate": baseline_recovery_rate,
        "recovery_lift": recovery_lift,
        "revenue_recovered": revenue_recovered,
        "baseline_revenue_recovered": baseline_revenue_recovered,
        "incremental_revenue": incremental_revenue,
        "intervention_efficiency": intervention_efficiency,
        "avg_attempts_per_recovery": avg_attempts_per_recovery,
        "baseline_avg_attempts": baseline_avg_attempts,
        "unnecessary_actions": unnecessary_actions,
        "baseline_unnecessary_actions": baseline_unnecessary_actions,
        "stopped_proactively": stopped_proactively,
        "escalated": escalated_count,
        "cohort_recovery": cohort_recovery,
        "by_failure_code": by_failure_code,
        "by_tier": by_tier,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

    from baseline.naive_retry import run_baseline
    from agent.stopping_rules import evaluate
    from agent.executor import _simulate_outcome

    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    with open(os.path.join(data_dir, "subscriptions.json"), "r", encoding="utf-8") as f:
        subscriptions = json.load(f)
    with open(os.path.join(data_dir, "outcome_model.json"), "r", encoding="utf-8") as f:
        outcome_model = json.load(f)

    # 1. Baseline
    baseline = run_baseline(subscriptions, outcome_model)

    # 2. RecoverAI Simulation
    action_map = {
        "INSUFFICIENT_FUNDS": "PAYDAY_RETRY",
        "CARD_EXPIRED": "PAYMENT_LINK",
        "MANDATE_REVOKED": "PAYMENT_LINK",
        "NETWORK_ERROR": "IMMEDIATE_RETRY",
        "UPI_TIMEOUT": "IMMEDIATE_RETRY",
    }

    recoverai_results = []
    audit_events = []

    for sub in subscriptions:
        sub_id = sub["subscription_id"]
        stopping = evaluate(sub)
        fc = sub["failure_code"]
        tier = sub["tier"]
        amount = sub["amount"]

        if stopping.triggered:
            audit_events.append({
                "subscription_id": sub_id,
                "event_type": "STOPPING_RULE_FIRED",
                "data": {
                    "rule": stopping.rule_name,
                    "disposition": stopping.disposition,
                    "reason": stopping.reason,
                },
            })
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
        outcome, prob = _simulate_outcome(act, fc, tier, sub_id)
        timing = 1 if act == "IMMEDIATE_RETRY" else (3 if act == "PAYDAY_RETRY" else 2)

        audit_events.append({
            "subscription_id": sub_id,
            "event_type": "ACTION_EXECUTED",
            "data": {"action": act, "outcome": outcome},
        })

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

    metrics = compute(recoverai_results, baseline, audit_events)

    print("=" * 60)
    print("RECOVERAI PERFORMANCE METRICS")
    print("=" * 60)
    print(json.dumps(metrics, indent=2))
