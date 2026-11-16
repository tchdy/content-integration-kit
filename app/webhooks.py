"""Webhook security and delivery.

Inbound (we receive):
  1. Verify an HMAC-SHA256 signature over "<timestamp>.<raw body>".
  2. Reject timestamps outside a tolerance window (replay protection).
  3. Deduplicate on the sender's event id, so retries are safe (idempotency).

Outbound (we send):
  Sign each payload the same way and retry transient failures (timeouts,
  5xx, 429) with exponential backoff. Other 4xx responses are not retried,
  because sending the same bad request again cannot succeed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

SIGNATURE_HEADER = "X-Signature"
TIMESTAMP_HEADER = "X-Timestamp"
EVENT_ID_HEADER = "X-Event-Id"


class SignatureError(Exception):
    """Signature missing, malformed, wrong, or too old."""


def sign(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def verify(secret: str, timestamp: str | None, signature: str | None, body: bytes,
           tolerance_seconds: int, now: float | None = None) -> None:
    if not timestamp or not signature:
        raise SignatureError("missing signature or timestamp header")
    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise SignatureError("timestamp is not an integer") from exc
    now = time.time() if now is None else now
    if abs(now - ts) > tolerance_seconds:
        raise SignatureError("timestamp outside tolerance window (possible replay)")
    expected = sign(secret, timestamp, body)
    # Constant-time compare: a normal == leaks how many leading characters matched.
    if not hmac.compare_digest(expected, signature):
        raise SignatureError("signature mismatch")


def record_event_once(conn: sqlite3.Connection, event_id: str, event_type: str, payload: str) -> bool:
    """Store the event. Returns False if this event id was already processed.

    The PRIMARY KEY on event_id makes this atomic: two concurrent deliveries
    of the same event cannot both insert.
    """
    try:
        conn.execute(
            "INSERT INTO webhook_events (event_id, event_type, payload) VALUES (?, ?, ?)",
            (event_id, event_type, payload),
        )
        return True
    except sqlite3.IntegrityError:
        return False


@dataclass
class DeliveryResult:
    delivered: bool
    attempts: int
    status_code: int | None = None
    errors: list[str] = field(default_factory=list)


def _retryable(status: int) -> bool:
    return status == 429 or status >= 500


def deliver(url: str, event_id: str, event_type: str, data: dict, secret: str, *,
            client: httpx.Client | None = None, max_attempts: int = 5,
            base_delay: float = 0.5, sleep: Callable[[float], None] = time.sleep) -> DeliveryResult:
    """Send a signed webhook with retries. The event id stays the same across
    retries so the receiver can deduplicate."""
    body = json.dumps({"id": event_id, "type": event_type, "data": data}, separators=(",", ":")).encode()
    owns_client = client is None
    client = client or httpx.Client(timeout=10)
    result = DeliveryResult(delivered=False, attempts=0)
    try:
        for attempt in range(1, max_attempts + 1):
            result.attempts = attempt
            ts = str(int(time.time()))
            headers = {
                "Content-Type": "application/json",
                TIMESTAMP_HEADER: ts,
                SIGNATURE_HEADER: sign(secret, ts, body),  # re-signed: timestamp changes per attempt
                EVENT_ID_HEADER: event_id,
            }
            try:
                resp = client.post(url, content=body, headers=headers)
                result.status_code = resp.status_code
                if 200 <= resp.status_code < 300:
                    result.delivered = True
                    return result
                result.errors.append(f"attempt {attempt}: HTTP {resp.status_code}")
                if not _retryable(resp.status_code):
                    return result
            except httpx.TransportError as exc:  # timeouts, connection refused, DNS
                result.errors.append(f"attempt {attempt}: {type(exc).__name__}")
            if attempt < max_attempts:
                sleep(base_delay * 2 ** (attempt - 1))  # 0.5s, 1s, 2s, 4s ...
        return result
    finally:
        if owns_client:
            client.close()
