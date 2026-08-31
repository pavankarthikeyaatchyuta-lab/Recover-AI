"""
razorpay_client.py — Step 5 of RecoverAI

Razorpay test-mode API wrapper.
Credentials: RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET from environment.
All amounts passed to this module are in rupees — converted to paise internally.
"""

import os
import razorpay


# ---------------------------------------------------------------------------
# Custom error
# ---------------------------------------------------------------------------
class RazorpayClientError(Exception):
    """Raised when a Razorpay SDK call fails."""
    pass


# ---------------------------------------------------------------------------
# Client (lazy singleton)
# ---------------------------------------------------------------------------
_client: razorpay.Client | None = None


def _get_client() -> razorpay.Client:
    global _client
    if _client is None:
        key_id = os.environ.get("RAZORPAY_KEY_ID", "")
        key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
        if not key_id or not key_secret:
            raise RazorpayClientError(
                "RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be set in environment."
            )
        _client = razorpay.Client(auth=(key_id, key_secret))
    return _client


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------
def create_payment_link(
    amount: int,
    customer_id: str,
    subscription_id: str,
    description: str,
) -> dict:
    """Create a Razorpay Payment Link via test-mode API.

    Args:
        amount: Amount in rupees.
        customer_id: Customer identifier.
        subscription_id: Subscription identifier.
        description: Payment description.

    Returns:
        {"payment_link_id": "...", "short_url": "...", "status": "created"}
    """
    try:
        client = _get_client()
        payload = {
            "amount": amount * 100,  # rupees to paise
            "currency": "INR",
            "description": description,
            "reference_id": subscription_id,
            "customer": {
                "contact": customer_id,
            },
            "notes": {
                "subscription_id": subscription_id,
                "customer_id": customer_id,
            },
        }
        result = client.payment_link.create(payload)
        return {
            "payment_link_id": result.get("id", ""),
            "short_url": result.get("short_url", ""),
            "status": result.get("status", "created"),
        }
    except Exception as e:
        raise RazorpayClientError(f"create_payment_link failed: {e}") from e


def fetch_payment_status(payment_id: str) -> dict:
    """Fetch payment status from Razorpay.

    Args:
        payment_id: The Razorpay payment ID.

    Returns:
        {"payment_id": "...", "status": "...", "amount": ...}
    """
    try:
        client = _get_client()
        result = client.payment.fetch(payment_id)
        return {
            "payment_id": result.get("id", payment_id),
            "status": result.get("status", "unknown"),
            "amount": result.get("amount", 0),
        }
    except Exception as e:
        raise RazorpayClientError(f"fetch_payment_status failed: {e}") from e


def create_order(amount: int, subscription_id: str) -> dict:
    """Create a Razorpay Order.

    Args:
        amount: Amount in rupees.
        subscription_id: Subscription identifier.

    Returns:
        {"order_id": "...", "status": "created", "amount": ...}
    """
    try:
        client = _get_client()
        payload = {
            "amount": amount * 100,  # rupees to paise
            "currency": "INR",
            "notes": {
                "subscription_id": subscription_id,
            },
        }
        result = client.order.create(payload)
        return {
            "order_id": result.get("id", ""),
            "status": result.get("status", "created"),
            "amount": result.get("amount", amount * 100),
        }
    except Exception as e:
        raise RazorpayClientError(f"create_order failed: {e}") from e
