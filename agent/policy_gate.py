"""
policy_gate.py — Step 4 of RecoverAI

Merchant policy gate between decision_agent and executor.
Checks whether the agent's chosen action is permitted under
merchant policy. Substitutes the closest permitted action if not.
"""

import json
import os

# ---------------------------------------------------------------------------
# Merchant policy (hardcoded defaults — merchant can override)
# ---------------------------------------------------------------------------
MERCHANT_POLICY = {
    "recovery_offers": {
        "Starter":  {"downgrade_to": "Starter Lite", "amount": 299},
        "Pro":      {"downgrade_to": "Pro Lite",     "amount": 999},
        "Business": {"downgrade_to": "Pro",          "amount": 1999},
    },
    "plan_downgrade_eligibility": {
        "min_failures": 2,
        "min_tenure_months": 6,
        "max_discount_pct": 50,
    },
    "allowed_channels": ["upi", "card", "sms", "whatsapp", "email"],
    "max_nudges_per_customer": 2,
    "require_human_review_above": 4999,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _check_downgrade_eligible(sub: dict) -> tuple[bool, str]:
    """Check if PLAN_DOWNGRADE is allowed under merchant policy."""
    elig = MERCHANT_POLICY["plan_downgrade_eligibility"]

    if sub["tenure_months"] < elig["min_tenure_months"]:
        return False, (
            f"PLAN_DOWNGRADE blocked: tenure_months={sub['tenure_months']} "
            f"< min {elig['min_tenure_months']}. Substituted PAYMENT_LINK."
        )

    if sub["previous_failures"] < elig["min_failures"]:
        return False, (
            f"PLAN_DOWNGRADE blocked: previous_failures={sub['previous_failures']} "
            f"< min {elig['min_failures']}. Substituted PAYMENT_LINK."
        )

    offers = MERCHANT_POLICY["recovery_offers"]
    plan = sub["plan_name"]
    if plan not in offers:
        return False, (
            f"PLAN_DOWNGRADE blocked: no downgrade offer configured "
            f"for plan '{plan}'. Substituted PAYMENT_LINK."
        )

    offer = offers[plan]
    original_amount = sub["amount"]
    if original_amount > 0:
        discount_pct = ((original_amount - offer["amount"]) / original_amount) * 100
        if discount_pct > elig["max_discount_pct"]:
            return False, (
                f"PLAN_DOWNGRADE blocked: discount {discount_pct:.0f}% exceeds "
                f"max {elig['max_discount_pct']}%. Substituted PAYMENT_LINK."
            )

    return True, "approved"


def _check_channel(decision: dict, sub: dict) -> tuple[str, str | None]:
    """Validate channel against allowed list. Return (channel, note_or_None)."""
    channel = decision["channel"]
    allowed = MERCHANT_POLICY["allowed_channels"]
    if channel in allowed:
        return channel, None
    fallback = sub["preferred_channel"]
    if fallback not in allowed:
        fallback = allowed[0]
    return fallback, (
        f"Channel '{channel}' not in allowed channels {allowed}. "
        f"Substituted '{fallback}'."
    )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def validate(decision: dict, sub: dict) -> dict:
    """Validate a recovery decision against merchant policy.

    Returns the decision dict with two additional fields:
      policy_approved: bool
      policy_note: str
    """
    result = dict(decision)
    modifications: list[str] = []

    # --- PLAN_DOWNGRADE eligibility ---
    if result["action"] == "PLAN_DOWNGRADE":
        eligible, note = _check_downgrade_eligible(sub)
        if not eligible:
            result["action"] = "PAYMENT_LINK"
            modifications.append(note)

    # --- Channel validation ---
    valid_channel, channel_note = _check_channel(result, sub)
    if channel_note:
        result["channel"] = valid_channel
        modifications.append(channel_note)

    # --- High-value human review override ---
    threshold = MERCHANT_POLICY["require_human_review_above"]
    if sub["amount"] > threshold:
        if not result.get("requires_human_review", False):
            result["requires_human_review"] = True
            modifications.append(
                f"Human review forced: amount={sub['amount']} > {threshold}."
            )

    # --- Set policy fields ---
    if modifications:
        result["policy_approved"] = False
        result["policy_note"] = " | ".join(modifications)
    else:
        result["policy_approved"] = True
        result["policy_note"] = "approved"

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Test 1: Valid PLAN_DOWNGRADE that should pass
    decision_1 = {
        "subscription_id": "sub_test_1",
        "action": "PLAN_DOWNGRADE",
        "timing_days": 1,
        "channel": "email",
        "evidence": {
            "failure_code": "INSUFFICIENT_FUNDS",
            "tenure_months": 18,
            "historical_recovery_rate": 0.85,
            "usual_payment_day": 5,
            "previous_recovery_days": [2, 3],
        },
        "risk_flags": ["repeated_failures"],
        "requires_human_review": False,
        "rationale": "Long-tenure customer with repeated failures. Offer downgrade.",
    }
    sub_1 = {
        "subscription_id": "sub_test_1",
        "customer_id": "cust_test_1",
        "plan_name": "Starter",
        "amount": 499,
        "failure_code": "INSUFFICIENT_FUNDS",
        "attempt_count": 1,
        "days_since_failure": 3,
        "tier": "regular",
        "tenure_months": 18,
        "lifetime_success_rate": 0.85,
        "billing_day": 1,
        "usual_payment_day": 5,
        "previous_failures": 3,
        "previous_recovery_days": [2, 3],
        "preferred_channel": "upi",
    }

    # Test 2: PLAN_DOWNGRADE blocked (tenure too short)
    decision_2 = {
        "subscription_id": "sub_test_2",
        "action": "PLAN_DOWNGRADE",
        "timing_days": 1,
        "channel": "sms",
        "evidence": {
            "failure_code": "INSUFFICIENT_FUNDS",
            "tenure_months": 3,
            "historical_recovery_rate": 0.60,
            "usual_payment_day": 10,
            "previous_recovery_days": [4],
        },
        "risk_flags": ["low_success_rate"],
        "requires_human_review": False,
        "rationale": "Offer downgrade to retain customer.",
    }
    sub_2 = {
        "subscription_id": "sub_test_2",
        "customer_id": "cust_test_2",
        "plan_name": "Business",
        "amount": 4999,
        "failure_code": "INSUFFICIENT_FUNDS",
        "attempt_count": 1,
        "days_since_failure": 2,
        "tier": "at_risk",
        "tenure_months": 3,
        "lifetime_success_rate": 0.60,
        "billing_day": 5,
        "usual_payment_day": 10,
        "previous_failures": 3,
        "previous_recovery_days": [4],
        "preferred_channel": "card",
    }

    # Test 3: High-value case triggering requires_human_review
    decision_3 = {
        "subscription_id": "sub_test_3",
        "action": "PAYDAY_RETRY",
        "timing_days": 2,
        "channel": "card",
        "evidence": {
            "failure_code": "INSUFFICIENT_FUNDS",
            "tenure_months": 12,
            "historical_recovery_rate": 0.90,
            "usual_payment_day": 15,
            "previous_recovery_days": [1],
        },
        "risk_flags": ["high_value"],
        "requires_human_review": False,
        "rationale": "Retry on payday.",
    }
    sub_3 = {
        "subscription_id": "sub_test_3",
        "customer_id": "cust_test_3",
        "plan_name": "Business",
        "amount": 9999,
        "failure_code": "INSUFFICIENT_FUNDS",
        "attempt_count": 0,
        "days_since_failure": 1,
        "tier": "high_value",
        "tenure_months": 12,
        "lifetime_success_rate": 0.90,
        "billing_day": 10,
        "usual_payment_day": 15,
        "previous_failures": 1,
        "previous_recovery_days": [1],
        "preferred_channel": "card",
    }

    tests = [
        ("Test 1: Valid PLAN_DOWNGRADE (should pass)", decision_1, sub_1),
        ("Test 2: PLAN_DOWNGRADE blocked (tenure too short)", decision_2, sub_2),
        ("Test 3: High-value human review override", decision_3, sub_3),
    ]

    for label, dec, sub in tests:
        print(f"\n{'='*60}")
        print(label)
        print(f"{'='*60}")
        result = validate(dec, sub)
        print(json.dumps(result, indent=2, ensure_ascii=False))
