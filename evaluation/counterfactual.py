"""
counterfactual.py — Step 8 of RecoverAI

Per-subscription side-by-side comparison: naive retry baseline vs RecoverAI.
Honest evaluation — reports BASELINE_WON cases alongside RECOVERAI_WON.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _compute_delta(baseline_outcome: str, recoverai_outcome: str, recoverai_action: str) -> str:
    """Compute the per-subscription delta label."""
    if recoverai_action in ("DO_NOT_ACT",) or recoverai_outcome == "NO_ACTION":
        return "RECOVERAI_STOPPED"

    b_ok = baseline_outcome == "SUCCESS"
    r_ok = recoverai_outcome == "SUCCESS"

    if r_ok and not b_ok:
        return "RECOVERAI_WON"
    if b_ok and not r_ok:
        return "BASELINE_WON"
    if r_ok and b_ok:
        return "BOTH_RECOVERED"
    return "BOTH_FAILED"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def compare(
    recoverai_results: list[dict],
    baseline_results: list[dict],
) -> dict:
    """Compare RecoverAI results against naive retry baseline.

    Args:
        recoverai_results: List of per-subscription result dicts from RecoverAI.
            Each must have: subscription_id, action (or action_taken), timing_days,
            outcome, amount, failure_code, tier, rationale (optional).
        baseline_results: List of per-subscription result dicts from naive retry.
            Each must have: subscription_id, action_taken, attempts, outcome, amount.

    Returns:
        Dict with summary metrics and per_subscription breakdown.
    """
    # Index baseline by subscription_id
    baseline_idx = {r["subscription_id"]: r for r in baseline_results}

    per_subscription = []
    baseline_recovered_count = 0
    recoverai_recovered_count = 0
    baseline_revenue = 0
    recoverai_revenue = 0
    recoverai_unnecessary = 0
    baseline_unnecessary = 0
    recoverai_stopped = 0

    for r in recoverai_results:
        sub_id = r["subscription_id"]
        b = baseline_idx.get(sub_id, {})

        # Normalize action field name
        r_action = r.get("action") or r.get("action_taken", "UNKNOWN")
        r_outcome = r.get("outcome", "FAILURE")
        r_timing = r.get("timing_days", 0)
        r_rationale = r.get("rationale", "")
        r_amount = r.get("amount", 0)
        r_failure_code = r.get("failure_code", "")
        r_tier = r.get("tier", "")

        b_action = b.get("action_taken", "IMMEDIATE_RETRY")
        b_attempts = b.get("attempts", 0)
        b_outcome = b.get("outcome", "FAILURE")
        b_amount = b.get("amount", r_amount)

        delta = _compute_delta(b_outcome, r_outcome, r_action)

        # Counts
        if b_outcome == "SUCCESS":
            baseline_recovered_count += 1
            baseline_revenue += b_amount
        if r_outcome == "SUCCESS":
            recoverai_recovered_count += 1
            recoverai_revenue += r_amount

        # Unnecessary actions: attempts that did not lead to recovery
        if b_outcome == "FAILURE":
            baseline_unnecessary += b_attempts
        if r_outcome == "FAILURE" and r_action not in ("DO_NOT_ACT",) and r_outcome != "NO_ACTION":
            recoverai_unnecessary += 1

        if delta == "RECOVERAI_STOPPED":
            recoverai_stopped += 1

        per_subscription.append({
            "subscription_id": sub_id,
            "amount": r_amount,
            "failure_code": r_failure_code,
            "tier": r_tier,
            "baseline": {
                "action": b_action,
                "attempts": b_attempts,
                "outcome": b_outcome,
            },
            "recoverai": {
                "action": r_action,
                "timing_days": r_timing,
                "outcome": r_outcome,
                "rationale": r_rationale,
            },
            "delta": delta,
        })

    total = len(recoverai_results)
    recovery_lift = recoverai_recovered_count - baseline_recovered_count
    recovery_lift_pct = round(
        (recovery_lift / total) * 100, 1
    ) if total > 0 else 0.0

    summary = {
        "total": total,
        "baseline_recovered": baseline_recovered_count,
        "recoverai_recovered": recoverai_recovered_count,
        "recovery_lift": recovery_lift,
        "recovery_lift_pct": recovery_lift_pct,
        "baseline_revenue": baseline_revenue,
        "recoverai_revenue": recoverai_revenue,
        "incremental_revenue": recoverai_revenue - baseline_revenue,
        "recoverai_unnecessary_actions": recoverai_unnecessary,
        "baseline_unnecessary_actions": baseline_unnecessary,
        "recoverai_stopped_proactively": recoverai_stopped,
    }

    return {
        "summary": summary,
        "per_subscription": per_subscription,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import hashlib
    import random

    from baseline.naive_retry import run_baseline
    from agent.executor import _simulate_outcome

    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    with open(os.path.join(data_dir, "subscriptions.json"), "r", encoding="utf-8") as f:
        subscriptions = json.load(f)
    with open(os.path.join(data_dir, "outcome_model.json"), "r", encoding="utf-8") as f:
        outcome_model = json.load(f)

    # --- Run naive baseline ---
    baseline = run_baseline(subscriptions, outcome_model)
    baseline_per_sub = baseline["per_subscription"]

    # --- Simulate RecoverAI results ---
    # Use stopping rules to partition, then simulate with smarter actions
    from agent.stopping_rules import evaluate

    ACTION_MAP = {
        "INSUFFICIENT_FUNDS": "PAYDAY_RETRY",
        "CARD_EXPIRED": "PAYMENT_LINK",
        "MANDATE_REVOKED": "PAYMENT_LINK",
        "NETWORK_ERROR": "IMMEDIATE_RETRY",
        "UPI_TIMEOUT": "IMMEDIATE_RETRY",
    }

    recoverai_per_sub = []
    for sub in subscriptions:
        stopping = evaluate(sub)
        fc = sub["failure_code"]
        tier = sub["tier"]
        sub_id = sub["subscription_id"]
        amount = sub["amount"]

        if stopping.triggered:
            recoverai_per_sub.append({
                "subscription_id": sub_id,
                "amount": amount,
                "failure_code": fc,
                "tier": tier,
                "action": "DO_NOT_ACT" if stopping.disposition == "STOPPED" else "DO_NOT_ACT",
                "timing_days": 0,
                "outcome": "NO_ACTION",
                "rationale": stopping.reason or "",
            })
            continue

        action = ACTION_MAP.get(fc, "PAYDAY_RETRY")
        outcome, prob = _simulate_outcome(action, fc, tier, sub_id)

        recoverai_per_sub.append({
            "subscription_id": sub_id,
            "amount": amount,
            "failure_code": fc,
            "tier": tier,
            "action": action,
            "timing_days": 2,
            "outcome": outcome,
            "rationale": f"Smart action {action} for {fc}.",
        })

    # --- Compare ---
    result = compare(recoverai_per_sub, baseline_per_sub)
    s = result["summary"]

    print("=" * 60)
    print("COUNTERFACTUAL COMPARISON: RecoverAI vs Naive Retry")
    print("=" * 60)
    print(f"Total subscriptions:          {s['total']}")
    print()
    print(f"Baseline recovered:           {s['baseline_recovered']}")
    print(f"RecoverAI recovered:          {s['recoverai_recovered']}")
    print(f"Recovery lift:                +{s['recovery_lift']} ({s['recovery_lift_pct']}%)")
    print()
    print(f"Baseline revenue:             Rs. {s['baseline_revenue']}")
    print(f"RecoverAI revenue:            Rs. {s['recoverai_revenue']}")
    print(f"Incremental revenue:          Rs. {s['incremental_revenue']}")
    print()
    print(f"Baseline unnecessary actions: {s['baseline_unnecessary_actions']}")
    print(f"RecoverAI unnecessary actions:{s['recoverai_unnecessary_actions']}")
    print(f"RecoverAI stopped proactively:{s['recoverai_stopped_proactively']}")

    # Delta breakdown
    from collections import Counter
    deltas = Counter(r["delta"] for r in result["per_subscription"])
    print()
    print("Delta breakdown:")
    for delta_type in ["RECOVERAI_WON", "BASELINE_WON", "BOTH_RECOVERED",
                       "BOTH_FAILED", "RECOVERAI_STOPPED"]:
        print(f"  {delta_type:<22s} {deltas.get(delta_type, 0):>3d}")

    # Show a few RECOVERAI_WON cases
    wins = [r for r in result["per_subscription"] if r["delta"] == "RECOVERAI_WON"]
    if wins:
        print()
        print("Sample RECOVERAI_WON cases (first 3):")
        for w in wins[:3]:
            print(f"  {w['subscription_id']} | {w['failure_code']} | "
                  f"Baseline: {w['baseline']['outcome']} | "
                  f"RecoverAI: {w['recoverai']['action']} -> {w['recoverai']['outcome']}")

    # Show BASELINE_WON cases (honest evaluation)
    losses = [r for r in result["per_subscription"] if r["delta"] == "BASELINE_WON"]
    if losses:
        print()
        print("BASELINE_WON cases (honest — baseline beat us):")
        for l in losses[:3]:
            print(f"  {l['subscription_id']} | {l['failure_code']} | "
                  f"Baseline: {l['baseline']['outcome']} | "
                  f"RecoverAI: {l['recoverai']['action']} -> {l['recoverai']['outcome']}")
