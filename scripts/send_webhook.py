#!/usr/bin/env python3
"""Send a signed content.published webhook, to demo or test a receiver.

    WEBHOOK_SECRET=... python scripts/send_webhook.py https://<app>/webhooks/inbound samples/article.xml
    # run it twice with the same --event-id to see idempotency: second reply is "duplicate"
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.webhooks import deliver  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("url")
    p.add_argument("article", type=Path)
    p.add_argument("--event-id", default=f"evt_{uuid.uuid4().hex[:12]}")
    p.add_argument("--secret", default=os.getenv("WEBHOOK_SECRET", "dev-webhook-secret"))
    a = p.parse_args()

    r = deliver(a.url, a.event_id, "content.published", {"xml": a.article.read_text()}, a.secret, max_attempts=3)
    print(f"event_id={a.event_id} delivered={r.delivered} attempts={r.attempts} status={r.status_code}")
    for e in r.errors:
        print("  ", e)
    return 0 if r.delivered else 1


if __name__ == "__main__":
    raise SystemExit(main())
