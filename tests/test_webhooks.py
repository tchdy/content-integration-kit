import json
import time
from pathlib import Path

import httpx
import pytest

from app import webhooks

SECRET = "test-secret"
ARTICLE = (Path(__file__).resolve().parent.parent / "samples" / "article.xml").read_text()


def signed_headers(body: bytes, event_id: str, ts: int | None = None, secret: str = SECRET) -> dict:
    ts_s = str(int(time.time()) if ts is None else ts)
    return {
        "Content-Type": "application/json",
        webhooks.TIMESTAMP_HEADER: ts_s,
        webhooks.SIGNATURE_HEADER: webhooks.sign(secret, ts_s, body),
        webhooks.EVENT_ID_HEADER: event_id,
    }


def event(event_id="evt_1", xml=ARTICLE) -> bytes:
    return json.dumps({"id": event_id, "type": "content.published", "data": {"xml": xml}}).encode()


# ---- inbound

def test_valid_webhook_is_processed_and_article_stored(client):
    body = event()
    r = client.post("/webhooks/inbound", content=body, headers=signed_headers(body, "evt_1"))
    assert r.status_code == 200 and r.json()["status"] == "processed"
    assert client.get("/articles").json()[0]["id"] == "quarterly-print-costs"
    assert "<h1>Why Print Costs" in client.get("/articles/quarterly-print-costs.html").text


def test_duplicate_delivery_is_acknowledged_not_reprocessed(client):
    body = event()
    client.post("/webhooks/inbound", content=body, headers=signed_headers(body, "evt_1"))
    r = client.post("/webhooks/inbound", content=body, headers=signed_headers(body, "evt_1"))
    assert r.status_code == 200 and r.json()["status"] == "duplicate"


def test_wrong_secret_rejected(client):
    body = event()
    r = client.post("/webhooks/inbound", content=body, headers=signed_headers(body, "evt_1", secret="nope"))
    assert r.status_code == 401 and "mismatch" in r.json()["reason"]


def test_tampered_body_rejected(client):
    body = event()
    headers = signed_headers(body, "evt_1")
    r = client.post("/webhooks/inbound", content=body.replace(b"Print", b"Paint"), headers=headers)
    assert r.status_code == 401


def test_old_timestamp_rejected_as_replay(client):
    body = event()
    r = client.post("/webhooks/inbound", content=body, headers=signed_headers(body, "evt_1", ts=int(time.time()) - 3600))
    assert r.status_code == 401 and "replay" in r.json()["reason"]


def test_invalid_article_rejected_and_can_be_resent_with_same_id(client):
    bad = event(xml=ARTICLE.replace('status="published"', 'status="live"'))
    assert client.post("/webhooks/inbound", content=bad, headers=signed_headers(bad, "evt_9")).status_code == 422
    good = event()
    r = client.post("/webhooks/inbound", content=good, headers=signed_headers(good, "evt_9"))
    assert r.json()["status"] == "processed"  # the failed attempt was not recorded


# ---- outbound

def _client(responses: list):
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return httpx.Response(item)
    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_outbound_retries_transient_errors_then_succeeds():
    c, calls = _client([503, httpx.ConnectTimeout("slow"), 200])
    sleeps = []
    r = webhooks.deliver("https://x.test/hook", "evt_1", "content.published", {}, SECRET, client=c, sleep=sleeps.append)
    assert r.delivered and r.attempts == 3
    assert sleeps == [0.5, 1.0]  # exponential backoff
    assert {req.headers[webhooks.EVENT_ID_HEADER] for req in calls} == {"evt_1"}  # same id every retry


def test_outbound_does_not_retry_client_errors():
    c, calls = _client([400])
    r = webhooks.deliver("https://x.test/hook", "evt_1", "t", {}, SECRET, client=c, sleep=lambda s: None)
    assert not r.delivered and r.attempts == 1


def test_outbound_gives_up_after_max_attempts():
    c, _ = _client([500] * 3)
    r = webhooks.deliver("https://x.test/hook", "evt_1", "t", {}, SECRET, client=c, max_attempts=3, sleep=lambda s: None)
    assert not r.delivered and r.attempts == 3 and len(r.errors) == 3


def test_outbound_signature_verifies_on_receiver_side():
    c, calls = _client([200])
    webhooks.deliver("https://x.test/hook", "evt_1", "t", {"a": 1}, SECRET, client=c)
    req = calls[0]
    webhooks.verify(SECRET, req.headers[webhooks.TIMESTAMP_HEADER], req.headers[webhooks.SIGNATURE_HEADER],
                    req.content, tolerance_seconds=300)  # raises if wrong


@pytest.mark.parametrize("ts,sig", [(None, "x"), ("1", None), ("abc", "x")])
def test_verify_rejects_missing_or_malformed_headers(ts, sig):
    with pytest.raises(webhooks.SignatureError):
        webhooks.verify(SECRET, ts, sig, b"{}", 300)
