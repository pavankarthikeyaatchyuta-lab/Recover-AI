"""
executor.py — Step 5 of RecoverAI

Executes the validated policy decision.
In TEST_MODE (default), simulates outcomes using outcome_model.json
instead of making real Razorpay API calls.
"""

import hashlib
import json
import os
import random
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from api.razorpay_client import (
    create_payment_link,
    create_order,
    RazorpayClientError,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ACTION_KEY_MAP = {
    "PAYDAY_RETRY": "payday_retry",
    "IMMEDIATE_RETRY": "immediate_retry",
    "PAYMENT_LINK": "payment_link",
    "NUDGE": "nudge",
    "PLAN_DOWNGRADE": "plan_downgrade",
}

_outcome_model: dict | None = None


def _load_outcome_model() -> dict:
    global _outcome_model
    if _outcome_model is None:
        model_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", "data", "outcome_model.json",
        )
        with open(model_path, "r", encoding="utf-8") as f:
            _outcome_model = json.load(f)
    return _outcome_model


# ---------------------------------------------------------------------------
# Outcome simulation
# ---------------------------------------------------------------------------
def _subscription_seed(subscription_id: str) -> int:
    """Deterministic seed derived from subscription_id."""
    return int(hashlib.md5(subscription_id.encode()).hexdigest(), 16) % (2**32)


def _simulate_outcome(
    action: str, failure_code: str, tier: str, subscription_id: str
) -> tuple[str, float]:
    """Simulate whether a recovery action succeeds using outcome_model.json.

    Returns (outcome, final_probability).
    """
    model = _load_outcome_model()

    action_key = ACTION_KEY_MAP.get(action)
    if action_key is None:
        return "NO_ACTION", 0.0

    base_probs = model["base_probabilities"].get(failure_code, {})
    base_p = base_probs.get(action_key, 0.0)

    multiplier = model["tier_multipliers"].get(tier, 1.0)
    final_p = min(base_p * multiplier, 0.95)

    rng = random.Random(_subscription_seed(subscription_id))
    outcome = "SUCCESS" if rng.random() < final_p else "FAILURE"

    return outcome, round(final_p, 4)


# ---------------------------------------------------------------------------
# Simulated API responses
# ---------------------------------------------------------------------------
def _simulated_api_response(action: str, sub: dict) -> dict:
    """Generate a plausible simulated API response for test mode."""
    sid = sub["subscription_id"]

    if action in ("PAYDAY_RETRY", "IMMEDIATE_RETRY"):
        return {
            "order_id": f"order_sim_{sid}",
            "status": "created",
            "amount": sub["amount"] * 100,
        }
    if action == "PAYMENT_LINK":
        return {
            "payment_link_id": f"plink_sim_{sid}",
            "short_url": f"https://rzp.io/test/{sid}",
            "status": "created",
        }
    if action == "NUDGE":
        return {
            "notification_id": f"notif_sim_{sid}",
            "channel": "sms",
            "status": "sent",
        }
    if action == "PLAN_DOWNGRADE":
        return {
            "downgrade_id": f"dg_sim_{sid}",
            "new_plan": "downgraded",
            "status": "offered",
        }
    return {}


# ---------------------------------------------------------------------------
# Real API execution
# ---------------------------------------------------------------------------
def _real_api_call(action: str, decision: dict, sub: dict) -> dict:
    """Execute a real Razorpay API call based on action type."""
    if action in ("PAYDAY_RETRY", "IMMEDIATE_RETRY"):
        return create_order(sub["amount"], sub["subscription_id"])

    if action == "PAYMENT_LINK":
        return create_payment_link(
            amount=sub["amount"],
            customer_id=sub["customer_id"],
            subscription_id=sub["subscription_id"],
            description=f"Recovery payment for {sub['subscription_id']}",
        )

    if action == "NUDGE":
        return {
            "notification_id": f"notif_{sub['subscription_id']}",
            "channel": decision.get("channel", "sms"),
            "status": "sent",
        }

    if action == "PLAN_DOWNGRADE":
        return create_payment_link(
            amount=sub["amount"],
            customer_id=sub["customer_id"],
            subscription_id=sub["subscription_id"],
            description=f"Plan downgrade offer for {sub['subscription_id']}",
        )

    return {}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def execute(decision: dict, sub: dict, test_mode: bool = True) -> dict:
    """Execute a recovery decision.

    Args:
        decision: Output from policy_gate.validate().
        sub: Original subscription record.
        test_mode: If True, simulate outcome without real API calls.

    Returns:
        Execution result dict with outcome simulation.
    """
    action = decision["action"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # DO_NOT_ACT: no execution needed
    if action == "DO_NOT_ACT":
        return {
            "subscription_id": sub["subscription_id"],
            "action_taken": "DO_NOT_ACT",
            "executed_at": now,
            "api_response": {},
            "simulated": test_mode,
            "outcome": "NO_ACTION",
            "outcome_probability": 0.0,
        }

    # Simulate or execute
    if test_mode:
        api_response = _simulated_api_response(action, sub)
    else:
        try:
            api_response = _real_api_call(action, decision, sub)
        except RazorpayClientError as e:
            return {
                "subscription_id": sub["subscription_id"],
                "action_taken": action,
                "executed_at": now,
                "api_response": {"error": str(e)},
                "simulated": False,
                "outcome": "FAILURE",
                "outcome_probability": 0.0,
            }

    # Outcome simulation (always uses the model, even in real mode,
    # because we can't know real-world outcome instantly)
    outcome, outcome_probability = _simulate_outcome(
        action, sub["failure_code"], sub["tier"], sub["subscription_id"]
    )

    return {
        "subscription_id": sub["subscription_id"],
        "action_taken": action,
        "executed_at": now,
        "api_response": api_response,
        "simulated": test_mode,
        "outcome": outcome,
        "outcome_probability": outcome_probability,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    data_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "subscriptions.json"
    )
    with open(data_path, "r", encoding="utf-8") as f:
        subscriptions = json.load(f)

    # Three test records with different actions
    test_cases = [
        {
            "sub_idx": 1,
            "decision": {
                "subscription_id": "sub_002",
                "action": "PAYDAY_RETRY",
                "timing_days": 3,
                "channel": "card",
                "evidence": {},
                "risk_flags": [],
                "requires_human_review": False,
                "rationale": "Test payday retry.",
                "policy_approved": True,
                "policy_note": "approved",
            },
        },
        {
            "sub_idx": 3,
            "decision": {
                "subscription_id": "sub_004",
                "action": "PAYMENT_LINK",
                "timing_days": 1,
                "channel": "email",
                "evidence": {},
                "risk_flags": [],
                "requires_human_review": False,
                "rationale": "Test payment link.",
                "policy_approved": True,
                "policy_note": "approved",
            },
        },
        {
            "sub_idx": 6,
            "decision": {
                "subscription_id": "sub_007",
                "action": "DO_NOT_ACT",
                "timing_days": 0,
                "channel": "sms",
                "evidence": {},
                "risk_flags": [],
                "requires_human_review": False,
                "rationale": "Test do not act.",
                "policy_approved": True,
                "policy_note": "approved",
            },
        },
    ]

    for tc in test_cases:
        sub = subscriptions[tc["sub_idx"]]
        dec = tc["decision"]
        print(f"\n{'='*60}")
        print(f"Action: {dec['action']} | Sub: {sub['subscription_id']} | "
              f"Failure: {sub['failure_code']} | Tier: {sub['tier']}")
        print(f"{'='*60}")
        result = execute(dec, sub, test_mode=True)
        print(json.dumps(result, indent=2, ensure_ascii=False))
