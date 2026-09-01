"""
audit.py — Step 6 of RecoverAI

Append-only event log. Every agent action writes one event.
Uses SQLite (same recoverai.db as state.py).

Event types: STOPPING_RULE_FIRED, DECISION_MADE, POLICY_VALIDATED,
             ACTION_EXECUTED, OUTCOME_RECORDED
"""

import csv
import json
import os
import sqlite3
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "recoverai.db"
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Init (called by state.init_db or standalone)
# ---------------------------------------------------------------------------
def init_db(reset: bool = False) -> None:
    """Create the audit_log table if it does not exist."""
    conn = _connect()
    if reset:
        conn.execute("DROP TABLE IF EXISTS audit_log")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            subscription_id TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            data            TEXT DEFAULT '{}'
        )
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def log(subscription_id: str, event_type: str, data: dict | None = None) -> None:
    """Append one event row to the audit log."""
    if data is None:
        data = {}
    conn = _connect()
    conn.execute(
        """
        INSERT INTO audit_log (subscription_id, event_type, timestamp, data)
        VALUES (?, ?, ?, ?)
        """,
        (
            subscription_id,
            event_type,
            _now(),
            json.dumps(data, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()


def get_events(subscription_id: str) -> list[dict]:
    """Return all events for a subscription in chronological order."""
    conn = _connect()
    rows = conn.execute(
        """
        SELECT id, subscription_id, event_type, timestamp, data
        FROM audit_log
        WHERE subscription_id = ?
        ORDER BY id ASC
        """,
        (subscription_id,),
    ).fetchall()
    conn.close()

    return [
        {
            "id": r["id"],
            "subscription_id": r["subscription_id"],
            "event_type": r["event_type"],
            "timestamp": r["timestamp"],
            "data": json.loads(r["data"] or "{}"),
        }
        for r in rows
    ]


def export_csv(output_path: str) -> None:
    """Export the full audit log to CSV."""
    conn = _connect()
    rows = conn.execute(
        """
        SELECT id, subscription_id, event_type, timestamp, data
        FROM audit_log
        ORDER BY id ASC
        """
    ).fetchall()
    conn.close()

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "subscription_id", "event_type", "timestamp", "data"])
        for r in rows:
            writer.writerow([
                r["id"],
                r["subscription_id"],
                r["event_type"],
                r["timestamp"],
                r["data"],
            ])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

    from core import state

    # Clean slate for testing
    test_db = DB_PATH
    if os.path.exists(test_db):
        os.remove(test_db)

    # 1. Init DB (both tables)
    state.init_db()
    init_db()
    print("DB initialized.\n")

    # 2. Create 2 test records
    sub_a = {
        "subscription_id": "sub_test_a",
        "customer_id": "cust_a",
        "plan_name": "Pro",
        "amount": 1999,
        "failure_code": "INSUFFICIENT_FUNDS",
        "attempt_count": 0,
        "days_since_failure": 2,
        "tier": "regular",
        "tenure_months": 12,
        "lifetime_success_rate": 0.90,
        "billing_day": 5,
        "usual_payment_day": 7,
        "previous_failures": 1,
        "previous_recovery_days": [3],
        "preferred_channel": "upi",
    }
    sub_b = {
        "subscription_id": "sub_test_b",
        "customer_id": "cust_b",
        "plan_name": "Business",
        "amount": 4999,
        "failure_code": "MANDATE_REVOKED",
        "attempt_count": 1,
        "days_since_failure": 1,
        "tier": "high_value",
        "tenure_months": 24,
        "lifetime_success_rate": 0.95,
        "billing_day": 10,
        "usual_payment_day": 12,
        "previous_failures": 0,
        "previous_recovery_days": [],
        "preferred_channel": "card",
    }

    state.create_record(sub_a)
    state.create_record(sub_b)
    print("Created 2 test records.")

    # 3. Transition sub_a: FAILED → DIAGNOSING → DECIDING → ACTING → MONITORING → RECOVERED
    state.transition("sub_test_a", "DIAGNOSING", {"step": "stopping_rules"})
    log("sub_test_a", "STOPPING_RULE_FIRED", {"rule": "none", "result": "clear"})

    state.transition("sub_test_a", "DECIDING", {"step": "decision_agent"})
    log("sub_test_a", "DECISION_MADE", {"action": "PAYDAY_RETRY", "timing_days": 2})

    state.transition("sub_test_a", "ACTING", {"step": "policy_gate"})
    log("sub_test_a", "POLICY_VALIDATED", {"policy_approved": True})
    log("sub_test_a", "ACTION_EXECUTED", {"action": "PAYDAY_RETRY", "simulated": True})

    state.transition("sub_test_a", "MONITORING")
    state.transition("sub_test_a", "RECOVERED", {"outcome": "SUCCESS"})
    log("sub_test_a", "OUTCOME_RECORDED", {"outcome": "SUCCESS", "probability": 0.61})

    # Transition sub_b: FAILED → DIAGNOSING → ESCALATED
    state.transition("sub_test_b", "DIAGNOSING", {"step": "stopping_rules"})
    log("sub_test_b", "STOPPING_RULE_FIRED", {
        "rule": "rule_mandate_revoked",
        "disposition": "ESCALATED",
    })
    state.transition("sub_test_b", "ESCALATED", {"reason": "mandate_revoked"})

    print("\nState after transitions:")
    print(f"  sub_test_a: {state.get('sub_test_a')['current_state']}")
    print(f"  sub_test_b: {state.get('sub_test_b')['current_state']}")

    # 4. Print events
    print(f"\nEvents for sub_test_a:")
    for evt in get_events("sub_test_a"):
        print(f"  [{evt['event_type']}] {evt['timestamp']} {json.dumps(evt['data'])}")

    print(f"\nEvents for sub_test_b:")
    for evt in get_events("sub_test_b"):
        print(f"  [{evt['event_type']}] {evt['timestamp']} {json.dumps(evt['data'])}")

    # 5. Export CSV and print first 5 rows
    reports_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "reports"
    )
    os.makedirs(reports_dir, exist_ok=True)
    csv_path = os.path.join(reports_dir, "audit_log.csv")
    export_csv(csv_path)

    print(f"\nAudit CSV exported to: {csv_path}")
    print("First 5 rows:")
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i > 5:
                break
            print(f"  {row}")

    # Validate invalid transition raises error
    print()
    try:
        state.transition("sub_test_a", "DIAGNOSING")
        print("ERROR: should have raised ValueError")
    except ValueError as e:
        print(f"Correctly rejected invalid transition: {e}")
