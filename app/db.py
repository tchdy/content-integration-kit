"""SQLite storage. Small on purpose: two tables, created on first use."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id           TEXT PRIMARY KEY,          -- article id in the new content model
    legacy_id    TEXT UNIQUE,               -- id in the source system (migration key)
    title        TEXT NOT NULL,
    status       TEXT NOT NULL,
    xml          TEXT NOT NULL,             -- validated article XML
    checksum     TEXT NOT NULL,             -- sha256 of xml; lets re-runs skip unchanged rows
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS webhook_events (
    event_id     TEXT PRIMARY KEY,          -- sender's event id; PRIMARY KEY makes dedupe atomic
    event_type   TEXT NOT NULL,
    payload      TEXT NOT NULL,
    received_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
