"""
generate_dataset.py — Step 1 of RecoverAI

Generates a reproducible 100-record synthetic dataset of failed
subscription payments and a separate outcome probability model.

Seed: 42 (deterministic — every run produces identical output).
"""

import json
import csv
import random
import os
from collections import Counter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SEED = 42
NUM_RECORDS = 100
DATA_DIR = os.path.dirname(os.path.abspath(__file__))

FAILURE_CODES = [
    "INSUFFICIENT_FUNDS",
    "CARD_EXPIRED",
    "MANDATE_REVOKED",
    "NETWORK_ERROR",
    "UPI_TIMEOUT",
]
FAILURE_WEIGHTS = [35, 20, 20, 15, 10]

TIERS = ["regular", "at_risk", "high_value", "first_time"]
TIER_WEIGHTS = [55, 20, 15, 10]

PLANS = [
    ("Starter", 499),
    ("Pro", 1999),
    ("Business", 4999),
]

BILLING_DAYS = [1, 5, 10, 15, 20, 25]
CHANNELS = ["upi", "card", "netbanking"]

# ---------------------------------------------------------------------------
# Outcome model (written to outcome_model.json, never applied to records)
# ---------------------------------------------------------------------------
OUTCOME_MODEL = {
    "base_probabilities": {
        "INSUFFICIENT_FUNDS": {
            "immediate_retry": 0.18,
            "payday_retry": 0.61,
            "payment_link": 0.44,
            "nudge": 0.31,
            "plan_downgrade": 0.52,
        },
        "CARD_EXPIRED": {
            "immediate_retry": 0.05,
            "payday_retry": 0.06,
            "payment_link": 0.55,
            "nudge": 0.28,
            "plan_downgrade": 0.20,
        },
        "MANDATE_REVOKED": {
            "immediate_retry": 0.03,
            "payday_retry": 0.04,
            "payment_link": 0.38,
            "nudge": 0.22,
            "plan_downgrade": 0.15,
        },
        "NETWORK_ERROR": {
            "immediate_retry": 0.58,
            "payday_retry": 0.60,
            "payment_link": 0.45,
            "nudge": 0.40,
            "plan_downgrade": 0.30,
        },
        "UPI_TIMEOUT": {
            "immediate_retry": 0.52,
            "payday_retry": 0.54,
            "payment_link": 0.42,
            "nudge": 0.38,
            "plan_downgrade": 0.25,
        },
    },
    "tier_multipliers": {
        "high_value": 1.15,
        "regular": 1.00,
        "at_risk": 0.70,
        "first_time": 0.85,
    },
    "seed": SEED,
    "note": (
        "Both naive_retry and RecoverAI use this same model. "
        "Only the action chosen differs between systems."
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _weighted_choice(rng: random.Random, population: list, weights: list):
    """random.choices with our seeded RNG instance."""
    return rng.choices(population, weights=weights, k=1)[0]


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _usual_payment_day(rng: random.Random, billing_day: int) -> int:
    """Payday signal logic per spec."""
    if billing_day <= 5:
        return rng.choice([1, 2, 3, 5, 7])
    offset = rng.randint(-2, 3)
    return _clamp(billing_day + offset, 1, 28)


def _round2(val: float) -> float:
    return round(val, 2)


# ---------------------------------------------------------------------------
# Record generator
# ---------------------------------------------------------------------------
def _generate_record(rng: random.Random, index: int) -> dict:
    sub_id = f"sub_{index:03d}"
    cust_id = f"cust_{index:03d}"

    plan_name, amount = rng.choice(PLANS)
    failure_code = _weighted_choice(rng, FAILURE_CODES, FAILURE_WEIGHTS)
    tier = _weighted_choice(rng, TIERS, TIER_WEIGHTS)

    days_since_failure = rng.randint(0, 6)
    billing_day = rng.choice(BILLING_DAYS)
    usual_pay_day = _usual_payment_day(rng, billing_day)
    preferred_channel = rng.choice(CHANNELS)

    # Tier-specific field ranges
    if tier == "first_time":
        tenure_months = rng.randint(0, 2)
        lifetime_success_rate = None
        attempt_count = 0
        previous_failures = 0
    elif tier == "at_risk":
        tenure_months = rng.randint(1, 8)
        lifetime_success_rate = _round2(rng.uniform(0.20, 0.72))
        attempt_count = rng.randint(0, 2)
        previous_failures = rng.randint(1, 3)
    elif tier == "high_value":
        tenure_months = rng.randint(6, 36)
        lifetime_success_rate = _round2(rng.uniform(0.78, 0.97))
        attempt_count = rng.randint(0, 1)
        previous_failures = rng.randint(0, 2)
    else:  # regular
        tenure_months = rng.randint(3, 24)
        lifetime_success_rate = _round2(rng.uniform(0.78, 0.97))
        attempt_count = rng.randint(0, 1)
        previous_failures = rng.randint(0, 2)

    # previous_recovery_days — one entry per past failure, each 1–5 days
    previous_recovery_days = [rng.randint(1, 5) for _ in range(previous_failures)]

    return {
        "subscription_id": sub_id,
        "customer_id": cust_id,
        "plan_name": plan_name,
        "amount": amount,
        "failure_code": failure_code,
        "attempt_count": attempt_count,
        "days_since_failure": days_since_failure,
        "tier": tier,
        "tenure_months": tenure_months,
        "lifetime_success_rate": lifetime_success_rate,
        "billing_day": billing_day,
        "usual_payment_day": usual_pay_day,
        "previous_failures": previous_failures,
        "previous_recovery_days": previous_recovery_days,
        "preferred_channel": preferred_channel,
    }


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
def _write_json(records: list, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def _write_csv(records: list, path: str) -> None:
    fieldnames = list(records[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            row = dict(rec)
            # Serialize list field for CSV readability
            row["previous_recovery_days"] = json.dumps(row["previous_recovery_days"])
            writer.writerow(row)


def _write_outcome_model(path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(OUTCOME_MODEL, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def generate():
    rng = random.Random(SEED)

    records = [_generate_record(rng, i + 1) for i in range(NUM_RECORDS)]

    json_path = os.path.join(DATA_DIR, "subscriptions.json")
    csv_path = os.path.join(DATA_DIR, "subscriptions.csv")
    model_path = os.path.join(DATA_DIR, "outcome_model.json")

    _write_json(records, json_path)
    _write_csv(records, csv_path)
    _write_outcome_model(model_path)

    return records, json_path, csv_path, model_path


if __name__ == "__main__":
    records, json_path, csv_path, model_path = generate()

    failure_counts = Counter(r["failure_code"] for r in records)
    tier_counts = Counter(r["tier"] for r in records)

    print(f"Total records generated: {len(records)}")
    print()
    print("Failure code distribution:")
    for code in FAILURE_CODES:
        print(f"  {code:<22s} {failure_counts[code]:>3d}")
    print()
    print("Customer tier distribution:")
    for tier in TIERS:
        print(f"  {tier:<14s} {tier_counts[tier]:>3d}")
    print()
    print("Files written:")
    print(f"  {json_path}")
    print(f"  {csv_path}")
    print(f"  {model_path}")
