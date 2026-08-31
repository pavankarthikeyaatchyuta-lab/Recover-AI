"""
decision_agent.py — Step 3 of RecoverAI

LLM-powered recovery decision agent. Reasons over customer context
to choose the best action, timing, channel, and rationale.

Deterministic logic (code): risk_flags, requires_human_review, subscription_id.
LLM logic: action, timing_days, channel, rationale.
"""

import json
import os
import re
from typing import Any

from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_MODEL = "gemini-2.0-flash"
MODEL = os.environ.get("LLM_MODEL", DEFAULT_MODEL)

VALID_ACTIONS = {
    "PAYDAY_RETRY",
    "IMMEDIATE_RETRY",
    "PAYMENT_LINK",
    "NUDGE",
    "PLAN_DOWNGRADE",
    "DO_NOT_ACT",
}

KNOWN_FAILURE_CODES = {
    "INSUFFICIENT_FUNDS",
    "CARD_EXPIRED",
    "MANDATE_REVOKED",
    "NETWORK_ERROR",
    "UPI_TIMEOUT",
}

SYSTEM_PROMPT = """\
You are RecoverAI, a subscription revenue recovery agent. You analyze \
failed subscription payments and decide the best recovery action.

AVAILABLE ACTIONS (choose exactly one):

PAYDAY_RETRY
  Retry on the customer's usual_payment_day. Use as default for \
INSUFFICIENT_FUNDS unless signals suggest otherwise.

IMMEDIATE_RETRY
  Retry within 24 hours. Use ONLY for NETWORK_ERROR or UPI_TIMEOUT \
where the failure is transient.

PAYMENT_LINK
  Send a payment link so the customer can pay with a new method. \
Good for CARD_EXPIRED or a first attempt at MANDATE_REVOKED.

NUDGE
  Send a reminder message without triggering a payment. Use when \
direct retry is unlikely to work but the customer may act on their own.

PLAN_DOWNGRADE
  Offer a lower-tier plan. Use ONLY when tenure_months >= 6 AND \
previous_failures >= 2. Never offer to first_time or very new customers.

DO_NOT_ACT
  Take no action and close the case. You MUST justify this in the \
rationale. Use when recovery is very unlikely or would harm the \
customer relationship.

RULES:
- Return ONLY valid JSON. No markdown fences, no preamble, no explanation.
- Your response must be a single JSON object with exactly these keys:
  "action", "timing_days", "channel", "rationale"
- action: one of the six action strings above
- timing_days: integer >= 0 (days to wait before executing the action)
- channel: one of "upi", "card", "netbanking", "email", "sms"
- rationale: one concise sentence explaining your decision
- For PAYDAY_RETRY: set timing_days to the number of days until \
usual_payment_day (if that day is soon) or a reasonable wait
- For IMMEDIATE_RETRY: timing_days should be 0 or 1
- For DO_NOT_ACT: timing_days should be 0
- Prefer the customer's preferred_channel when appropriate
- PAYDAY_RETRY is the default for INSUFFICIENT_FUNDS
"""


# ---------------------------------------------------------------------------
# Client (lazy singleton)
# ---------------------------------------------------------------------------
_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client()
    return _client


# ---------------------------------------------------------------------------
# Deterministic helpers (never LLM)
# ---------------------------------------------------------------------------
def _compute_risk_flags(sub: dict) -> list[str]:
    """Populate risk flags from signals — deterministic, no LLM."""
    flags: list[str] = []
    if sub["previous_failures"] >= 2:
        flags.append("repeated_failures")
    lsr = sub["lifetime_success_rate"]
    if lsr is not None and lsr < 0.70:
        flags.append("low_success_rate")
    if sub["amount"] >= 4999:
        flags.append("high_value")
    if sub["tier"] == "at_risk":
        flags.append("at_risk_customer")
    if sub["tier"] == "first_time":
        flags.append("first_time_customer")
    if sub["attempt_count"] >= 2:
        flags.append("multiple_attempts")
    return flags


def _compute_requires_human_review(sub: dict) -> bool:
    """Deterministic human-review flag — never LLM."""
    if sub["failure_code"] not in KNOWN_FAILURE_CODES:
        return True
    if sub["amount"] >= 4999 and sub["tenure_months"] < 3:
        return True
    if sub["lifetime_success_rate"] is None:
        return True
    return False


def _build_evidence(sub: dict) -> dict:
    """Extract evidence fields from the subscription record."""
    return {
        "failure_code": sub["failure_code"],
        "tenure_months": sub["tenure_months"],
        "historical_recovery_rate": sub["lifetime_success_rate"],
        "usual_payment_day": sub["usual_payment_day"],
        "previous_recovery_days": sub["previous_recovery_days"],
    }


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------
def _build_user_prompt(sub: dict, risk_flags: list[str]) -> str:
    """Build the user prompt with all context the LLM needs."""
    context = {
        "subscription_id": sub["subscription_id"],
        "plan_name": sub["plan_name"],
        "amount": sub["amount"],
        "failure_code": sub["failure_code"],
        "attempt_count": sub["attempt_count"],
        "days_since_failure": sub["days_since_failure"],
        "tier": sub["tier"],
        "tenure_months": sub["tenure_months"],
        "lifetime_success_rate": sub["lifetime_success_rate"],
        "billing_day": sub["billing_day"],
        "usual_payment_day": sub["usual_payment_day"],
        "previous_failures": sub["previous_failures"],
        "previous_recovery_days": sub["previous_recovery_days"],
        "preferred_channel": sub["preferred_channel"],
        "risk_flags": risk_flags,
    }
    return (
        "Analyze this failed subscription payment and decide the "
        "recovery action.\n\n"
        f"{json.dumps(context, indent=2)}\n\n"
        "Return ONLY a JSON object with keys: "
        '"action", "timing_days", "channel", "rationale"'
    )


def _parse_llm_response(raw: str) -> dict:
    """Extract the JSON object from the LLM response, stripping any
    markdown fences or preamble the model may have added."""
    text = raw.strip()
    # Strip markdown code fences
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    return json.loads(text)


def _validate_llm_output(parsed: dict, sub: dict) -> dict:
    """Clamp/validate the LLM output to the allowed schema."""
    action = parsed.get("action", "DO_NOT_ACT")
    if action not in VALID_ACTIONS:
        action = "DO_NOT_ACT"

    # Guard: IMMEDIATE_RETRY only for transient failures
    if action == "IMMEDIATE_RETRY" and sub["failure_code"] not in (
        "NETWORK_ERROR",
        "UPI_TIMEOUT",
    ):
        action = "PAYDAY_RETRY"

    # Guard: PLAN_DOWNGRADE eligibility
    if action == "PLAN_DOWNGRADE" and (
        sub["tenure_months"] < 6 or sub["previous_failures"] < 2
    ):
        action = "NUDGE"

    timing_days = parsed.get("timing_days", 0)
    if not isinstance(timing_days, int) or timing_days < 0:
        timing_days = 0

    channel = parsed.get("channel", sub["preferred_channel"])
    valid_channels = {"upi", "card", "netbanking", "email", "sms"}
    if channel not in valid_channels:
        channel = sub["preferred_channel"]

    rationale = parsed.get("rationale", "No rationale provided.")
    if not isinstance(rationale, str) or not rationale.strip():
        rationale = "No rationale provided."

    return {
        "action": action,
        "timing_days": timing_days,
        "channel": channel,
        "rationale": rationale,
    }


def _fallback_decision(sub: dict) -> dict:
    """Deterministic fallback when the LLM call fails."""
    fc = sub["failure_code"]
    if fc in ("NETWORK_ERROR", "UPI_TIMEOUT"):
        return {
            "action": "IMMEDIATE_RETRY",
            "timing_days": 0,
            "channel": sub["preferred_channel"],
            "rationale": f"LLM unavailable. Defaulting to immediate retry for {fc}.",
        }
    if fc == "CARD_EXPIRED":
        return {
            "action": "PAYMENT_LINK",
            "timing_days": 1,
            "channel": "email",
            "rationale": "LLM unavailable. Sending payment link for expired card.",
        }
    if fc == "MANDATE_REVOKED":
        return {
            "action": "PAYMENT_LINK",
            "timing_days": 1,
            "channel": "email",
            "rationale": "LLM unavailable. Sending payment link for revoked mandate.",
        }
    # Default: INSUFFICIENT_FUNDS or unknown
    return {
        "action": "PAYDAY_RETRY",
        "timing_days": max(0, sub["usual_payment_day"] - sub["billing_day"]),
        "channel": sub["preferred_channel"],
        "rationale": "LLM unavailable. Defaulting to payday retry.",
    }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def decide(sub: dict) -> dict:
    """Decide the recovery action for a failed subscription payment.

    Returns the strict output schema:
      subscription_id, action, timing_days, channel,
      evidence, risk_flags, requires_human_review, rationale
    """
    risk_flags = _compute_risk_flags(sub)
    requires_human_review = _compute_requires_human_review(sub)
    evidence = _build_evidence(sub)

    # Attempt LLM decision
    try:
        client = _get_client()
        user_prompt = _build_user_prompt(sub, risk_flags)
        response = client.models.generate_content(
            model=MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.2,
                max_output_tokens=256,
            ),
        )
        raw_text = response.text or ""
        parsed = _parse_llm_response(raw_text)
        llm_decision = _validate_llm_output(parsed, sub)
    except Exception:
        llm_decision = _fallback_decision(sub)

    return {
        "subscription_id": sub["subscription_id"],
        "action": llm_decision["action"],
        "timing_days": llm_decision["timing_days"],
        "channel": llm_decision["channel"],
        "evidence": evidence,
        "risk_flags": risk_flags,
        "requires_human_review": requires_human_review,
        "rationale": llm_decision["rationale"],
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

    test_indices = [0, 42, 99]
    for idx in test_indices:
        sub = subscriptions[idx]
        print(f"\n{'='*60}")
        print(f"Input: {sub['subscription_id']} | {sub['failure_code']} | "
              f"tier={sub['tier']} | amount={sub['amount']}")
        print(f"{'='*60}")
        result = decide(sub)
        print(json.dumps(result, indent=2, ensure_ascii=False))
