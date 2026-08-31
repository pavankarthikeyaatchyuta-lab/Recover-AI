"""
naive_retry.py — Step 7 of RecoverAI

Naive retry baseline that attempts IMMEDIATE_RETRY up to 3 times
with no intelligence, context, or payday awareness.
Uses the same outcome_model.json to ensure honest counterfactual comparison.
"""

import hashlib
import json
import os
import random


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _subscription_seed(subscription_id: str) -> int:
    """Deterministic seed derived from subscription_id."""
    return int(hashlib.md5(subscription_id.encode()).hexdigest(), 16) % (2**32)


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def run_baseline(subscriptions: list[dict], outcome_model: dict) -> dict:
    """Run the naive retry baseline on a list of subscription records.

    Strategy:
      Always attempt IMMEDIATE_RETRY, up to 3 times.
      Stop on first SUCCESS, or terminate after 3 failed attempts.

    Args:
        subscriptions: List of subscription dicts.
        outcome_model: Outcome probability model dict.

    Returns:
        Summary dict containing overall metrics and per_subscription breakdown.
    """
    per_subscription = []
    base_probs = outcome_model.get("base_probabilities", {})
    tier_mults = outcome_model.get("tier_multipliers", {})

    for sub in subscriptions:
        sub_id = sub["subscription_id"]
        fc = sub["failure_code"]
        tier = sub["tier"]
        amount = sub["amount"]

        base_p = base_probs.get(fc, {}).get("immediate_retry", 0.0)
        multiplier = tier_mults.get(tier, 1.0)
        final_p = min(base_p * multiplier, 0.95)

        rng = random.Random(_subscription_seed(sub_id))
        recovered = False
        attempts_taken = 0

        for attempt in range(1, 4):
            attempts_taken = attempt
            if rng.random() < final_p:
                recovered = True
                break

        outcome = "SUCCESS" if recovered else "FAILURE"
        per_subscription.append({
            "subscription_id": sub_id,
            "action_taken": "IMMEDIATE_RETRY",
            "attempts": attempts_taken,
            "outcome": outcome,
            "amount": amount,
        })

    recovered_subs = [s for s in per_subscription if s["outcome"] == "SUCCESS"]
    failed_subs = [s for s in per_subscription if s["outcome"] == "FAILURE"]

    total = len(subscriptions)
    recovered_count = len(recovered_subs)
    stopped_by_cap = len(failed_subs)
    revenue_recovered = sum(s["amount"] for s in recovered_subs)
    revenue_at_risk = sum(s["amount"] for s in subscriptions)

    avg_attempts_per_recovery = (
        round(sum(s["attempts"] for s in recovered_subs) / recovered_count, 2)
        if recovered_count > 0
        else 0.0
    )

    unnecessary_actions = sum(s["attempts"] for s in failed_subs)

    return {
        "total": total,
        "recovered": recovered_count,
        "stopped_by_cap": stopped_by_cap,
        "revenue_recovered": revenue_recovered,
        "revenue_at_risk": revenue_at_risk,
        "avg_attempts_per_recovery": avg_attempts_per_recovery,
        "unnecessary_actions": unnecessary_actions,
        "per_subscription": per_subscription,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    subs_path = os.path.join(base_dir, "..", "data", "subscriptions.json")
    model_path = os.path.join(base_dir, "..", "data", "outcome_model.json")

    with open(subs_path, "r", encoding="utf-8") as f:
        subscriptions = json.load(f)

    with open(model_path, "r", encoding="utf-8") as f:
        outcome_model = json.load(f)

    results = run_baseline(subscriptions, outcome_model)

    print("=" * 60)
    print("NAIVE RETRY BASELINE RESULTS")
    print("=" * 60)
    print(f"Total subscriptions:          {results['total']}")
    print(f"Recovered subscriptions:      {results['recovered']}")
    print(f"Stopped by cap (failed):      {results['stopped_by_cap']}")
    print(f"Revenue recovered:            Rs. {results['revenue_recovered']}")
    print(f"Revenue at risk:              Rs. {results['revenue_at_risk']}")
    print(f"Avg attempts per recovery:    {results['avg_attempts_per_recovery']}")
    print(f"Unnecessary actions:          {results['unnecessary_actions']}")
    print()
    print("Sample per-subscription results (first 5):")
    for item in results["per_subscription"][:5]:
        print(f"  {item['subscription_id']}: {item['action_taken']} | "
              f"Attempts: {item['attempts']} | {item['outcome']} | Rs. {item['amount']}")
