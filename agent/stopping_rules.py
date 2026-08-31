"""
stopping_rules.py — Step 2 of RecoverAI

Hard safety gates that run BEFORE the LLM decision agent.
Deterministic, never overridable. First rule to fire wins.
"""

import json
import os
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Constants (all adjustable)
# ---------------------------------------------------------------------------
MAX_ATTEMPT_COUNT = 3
COOLDOWN_HOURS = 24
HIGH_VALUE_THRESHOLD = 4999
AT_RISK_MAX_ATTEMPTS = 2
CHRONIC_SUCCESS_THRESHOLD = 0.25


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------
@dataclass
class StoppingDecision:
    triggered: bool
    disposition: Optional[str]   # "STOPPED" | "ESCALATED" | None
    rule_name: Optional[str]
    reason: Optional[str]

    @classmethod
    def clear(cls) -> "StoppingDecision":
        return cls(triggered=False, disposition=None, rule_name=None, reason=None)


# ---------------------------------------------------------------------------
# Individual rules (priority order)
# ---------------------------------------------------------------------------
def rule_max_attempts(sub: dict) -> Optional[StoppingDecision]:
    if sub["attempt_count"] >= MAX_ATTEMPT_COUNT:
        return StoppingDecision(
            triggered=True,
            disposition="STOPPED",
            rule_name="rule_max_attempts",
            reason=(
                f"Hard cap reached: attempt_count={sub['attempt_count']} "
                f">= {MAX_ATTEMPT_COUNT}. No further auto-action."
            ),
        )
    return None


def rule_at_risk_cap(sub: dict) -> Optional[StoppingDecision]:
    if sub["tier"] == "at_risk" and sub["attempt_count"] >= AT_RISK_MAX_ATTEMPTS:
        return StoppingDecision(
            triggered=True,
            disposition="STOPPED",
            rule_name="rule_at_risk_cap",
            reason=(
                f"At-risk tier cap: attempt_count={sub['attempt_count']} "
                f">= {AT_RISK_MAX_ATTEMPTS}. Preventing over-contact."
            ),
        )
    return None


def rule_mandate_revoked(sub: dict) -> Optional[StoppingDecision]:
    if sub["failure_code"] == "MANDATE_REVOKED" and sub["attempt_count"] > 0:
        return StoppingDecision(
            triggered=True,
            disposition="ESCALATED",
            rule_name="rule_mandate_revoked",
            reason=(
                "Mandate revoked with prior attempt -- customer intent signal. "
                "Escalating to merchant."
            ),
        )
    return None


def rule_chronic_non_payer(sub: dict) -> Optional[StoppingDecision]:
    lsr = sub["lifetime_success_rate"]
    if (
        lsr is not None
        and lsr < CHRONIC_SUCCESS_THRESHOLD
        and sub["attempt_count"] >= 1
    ):
        return StoppingDecision(
            triggered=True,
            disposition="STOPPED",
            rule_name="rule_chronic_non_payer",
            reason=(
                f"Chronic non-payer: lifetime_success_rate={lsr} "
                f"< {CHRONIC_SUCCESS_THRESHOLD} with prior attempt. "
                "Stopping to prevent harassment."
            ),
        )
    return None


def rule_high_value_first_time(sub: dict) -> Optional[StoppingDecision]:
    if sub["amount"] >= HIGH_VALUE_THRESHOLD and (
        sub["tier"] == "first_time" or sub["tenure_months"] <= 2
    ):
        return StoppingDecision(
            triggered=True,
            disposition="ESCALATED",
            rule_name="rule_high_value_first_time",
            reason=(
                f"High-value amount (Rs.{sub['amount']}) with no established "
                f"relationship (tier={sub['tier']}, tenure={sub['tenure_months']}mo). "
                "Escalating to merchant for review."
            ),
        )
    return None


def rule_cooldown(sub: dict) -> Optional[StoppingDecision]:
    if sub["attempt_count"] > 0 and sub["days_since_failure"] == 0:
        return StoppingDecision(
            triggered=True,
            disposition="STOPPED",
            rule_name="rule_cooldown",
            reason=(
                "Within 24h cooldown window (days_since_failure=0 with "
                "prior attempt). Holding action."
            ),
        )
    return None


# Ordered rule chain — first to fire wins
# Stopping-safety rules run before escalation decisions to prevent
# over-contact of chronic non-payers on high-value plans.
_RULES = [
    rule_max_attempts,
    rule_at_risk_cap,
    rule_mandate_revoked,
    rule_chronic_non_payer,
    rule_high_value_first_time,
    rule_cooldown,
]


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def evaluate(sub: dict) -> StoppingDecision:
    """Run all rules in priority order. Return first that fires, or clear()."""
    for rule_fn in _RULES:
        decision = rule_fn(sub)
        if decision is not None:
            return decision
    return StoppingDecision.clear()


def evaluate_batch(subscriptions: list) -> dict:
    """Partition subscriptions into clear / stopped / escalated."""
    result = {"clear": [], "stopped": [], "escalated": []}
    for sub in subscriptions:
        decision = evaluate(sub)
        if not decision.triggered:
            result["clear"].append(sub)
        elif decision.disposition == "STOPPED":
            result["stopped"].append((sub, decision))
        elif decision.disposition == "ESCALATED":
            result["escalated"].append((sub, decision))
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    data_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "subscriptions.json"
    )
    with open(data_path, "r", encoding="utf-8") as f:
        subscriptions = json.load(f)

    batch = evaluate_batch(subscriptions)

    print(f"Clear (proceed to LLM): {len(batch['clear'])}")
    print(f"Stopped:                {len(batch['stopped'])}")
    print(f"Escalated:              {len(batch['escalated'])}")
    print()

    if batch["stopped"]:
        print("Stopped cases:")
        for sub, dec in batch["stopped"]:
            print(f"  {sub['subscription_id']} | {dec.rule_name} | {dec.reason}")
        print()

    if batch["escalated"]:
        print("Escalated cases:")
        for sub, dec in batch["escalated"]:
            print(f"  {sub['subscription_id']} | {dec.rule_name} | {dec.reason}")
        print()

    # Assertions
    for sub in batch["clear"]:
        assert not (
            sub["failure_code"] == "MANDATE_REVOKED" and sub["attempt_count"] > 0
        ), (
            f"{sub['subscription_id']}: MANDATE_REVOKED with "
            f"attempt_count={sub['attempt_count']} should not be in clear list"
        )
        assert sub["attempt_count"] < MAX_ATTEMPT_COUNT, (
            f"{sub['subscription_id']}: attempt_count={sub['attempt_count']} "
            f">= {MAX_ATTEMPT_COUNT} should not be in clear list"
        )

    print("All assertions passed.")
