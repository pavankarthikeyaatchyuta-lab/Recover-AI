"""
state.py — Step 6 of RecoverAI

Finite state machine for subscription recovery lifecycle.
Persisted in SQLite (recoverai.db).

States: FAILED → DIAGNOSING → DECIDING → ACTING → MONITORING →
        RECOVERED | STOPPED | ESCALATED
"""

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

VALID_STATES = {
    "FAILED",
    "DIAGNOSING",
    "DECIDING",
    "ACTING",
    "MONITORING",
    "RECOVERED",
    "STOPPED",
    "ESCALATED",
}

VALID_TRANSITIONS = {
    "FAILED":      {"DIAGNOSING"},
    "DIAGNOSING":  {"DECIDING", "STOPPED", "ESCALATED"},
    "DECIDING":    {"ACTING", "STOPPED", "ESCALATED"},
    "ACTING":      {"MONITORING"},
    "MONITORING":  {"RECOVERED", "STOPPED", "ESCALATED", "DECIDING"},
}


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
# Public interface
# ---------------------------------------------------------------------------
def init_db() -> None:
    """Create the subscriptions table if it does not exist."""
    conn = _connect()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            subscription_id TEXT PRIMARY KEY,
            current_state   TEXT NOT NULL,
            attempt_count   INTEGER DEFAULT 0,
            last_updated    TEXT NOT NULL,
            metadata        TEXT DEFAULT '{}'
        )
    """)
    conn.commit()
    conn.close()


def create_record(sub: dict) -> None:
    """Insert a new subscription with state = FAILED."""
    conn = _connect()
    conn.execute(
        """
        INSERT OR REPLACE INTO subscriptions
            (subscription_id, current_state, attempt_count, last_updated, metadata)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            sub["subscription_id"],
            "FAILED",
            sub.get("attempt_count", 0),
            _now(),
            json.dumps(sub, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()


def transition(
    subscription_id: str, new_state: str, metadata: dict | None = None
) -> None:
    """Transition a subscription to a new state.

    Raises ValueError if the transition is not valid.
    """
    if metadata is None:
        metadata = {}

    if new_state not in VALID_STATES:
        raise ValueError(f"Invalid state: {new_state}")

    conn = _connect()
    row = conn.execute(
        "SELECT current_state, metadata FROM subscriptions WHERE subscription_id = ?",
        (subscription_id,),
    ).fetchone()

    if row is None:
        conn.close()
        raise ValueError(f"Subscription {subscription_id} not found")

    current_state = row["current_state"]
    allowed = VALID_TRANSITIONS.get(current_state, set())

    if new_state not in allowed:
        conn.close()
        raise ValueError(
            f"Invalid transition: {current_state} -> {new_state}. "
            f"Allowed: {sorted(allowed)}"
        )

    # Merge metadata
    existing_meta = json.loads(row["metadata"] or "{}")
    existing_meta.update(metadata)

    conn.execute(
        """
        UPDATE subscriptions
        SET current_state = ?, last_updated = ?, metadata = ?
        WHERE subscription_id = ?
        """,
        (new_state, _now(), json.dumps(existing_meta, ensure_ascii=False), subscription_id),
    )
    conn.commit()
    conn.close()


def get(subscription_id: str) -> dict:
    """Return current record for a subscription."""
    conn = _connect()
    row = conn.execute(
        "SELECT * FROM subscriptions WHERE subscription_id = ?",
        (subscription_id,),
    ).fetchone()
    conn.close()

    if row is None:
        raise ValueError(f"Subscription {subscription_id} not found")

    return {
        "subscription_id": row["subscription_id"],
        "current_state": row["current_state"],
        "attempt_count": row["attempt_count"],
        "last_updated": row["last_updated"],
        "metadata": json.loads(row["metadata"] or "{}"),
    }


def get_all_by_state(state: str) -> list[dict]:
    """Return all records in a given state."""
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM subscriptions WHERE current_state = ?",
        (state,),
    ).fetchall()
    conn.close()

    return [
        {
            "subscription_id": r["subscription_id"],
            "current_state": r["current_state"],
            "attempt_count": r["attempt_count"],
            "last_updated": r["last_updated"],
            "metadata": json.loads(r["metadata"] or "{}"),
        }
        for r in rows
    ]
