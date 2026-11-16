#!/usr/bin/env python3
"""Migrate a legacy CMS export into the new article model.

    python scripts/migrate.py samples/legacy_export.xml --dry-run
    python scripts/migrate.py samples/legacy_export.xml --report migration_report.json

For each legacy <doc>:  transform (XSLT) -> validate (XSD) -> upsert by legacy id.

Properties that make it safe to run against a customer's data:
  * Dry run:      --dry-run does everything except write, so you can review the report first.
  * Idempotent:   records are keyed on legacy id; a re-run updates changed rows and
                  skips unchanged ones (compared by checksum). Running it twice is harmless.
  * Isolated:     one bad record is reported and skipped; it doesn't abort the batch.
  * Batched:      commits every --batch-size records, so a crash loses at most one batch.
  * Reconciled:   the report shows source count = created + updated + unchanged + failed.
                  If that equation doesn't hold, something was lost and the run exits non-zero.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lxml import etree  # noqa: E402

from app import xml_pipeline  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import connect  # noqa: E402


@dataclass
class Report:
    source_file: str
    dry_run: bool
    source_count: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    failures: list[dict] = field(default_factory=list)

    @property
    def reconciled(self) -> bool:
        return self.source_count == self.created + self.updated + self.unchanged + self.failed


def migrate(source: Path, db_path: Path, dry_run: bool = False, batch_size: int = 100) -> Report:
    report = Report(source_file=str(source), dry_run=dry_run)
    export = xml_pipeline.read(source)
    docs = export.getroot().findall("doc")
    report.source_count = len(docs)

    with connect(db_path) as conn:
        for i, doc in enumerate(docs, start=1):
            legacy_id = doc.get("lid", f"<record {i}>")
            # deepcopy detaches the record so it becomes the document root the stylesheet expects
            article = xml_pipeline.transform(etree.ElementTree(copy.deepcopy(doc)), "legacy_to_article.xsl")
            result = xml_pipeline.validate(article)
            if not result.valid:
                report.failed += 1
                report.failures.append({"legacy_id": legacy_id, "errors": result.errors})
                continue

            root = article.getroot()
            digest = xml_pipeline.checksum(article)
            existing = conn.execute("SELECT checksum FROM articles WHERE legacy_id = ?", (legacy_id,)).fetchone()
            if existing and existing["checksum"] == digest:
                report.unchanged += 1
                continue
            report.updated += 1 if existing else 0
            report.created += 0 if existing else 1
            if not dry_run:
                conn.execute(
                    """INSERT INTO articles (id, legacy_id, title, status, xml, checksum)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(legacy_id) DO UPDATE SET id=excluded.id, title=excluded.title,
                         status=excluded.status, xml=excluded.xml, checksum=excluded.checksum,
                         updated_at=datetime('now')""",
                    (root.get("id"), legacy_id, root.findtext("title"), root.get("status"),
                     xml_pipeline.canonical_bytes(article).decode(), digest),
                )
                if i % batch_size == 0:
                    conn.commit()
        if dry_run:
            conn.rollback()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", type=Path, help="legacy export XML file")
    parser.add_argument("--dry-run", action="store_true", help="validate and report, write nothing")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--report", type=Path, help="write the JSON report here")
    parser.add_argument("--db", type=Path, help="SQLite path (default: DATA_DIR/kit.db)")
    args = parser.parse_args(argv)

    report = migrate(args.source, args.db or get_settings().db_path, args.dry_run, args.batch_size)
    payload = {**asdict(report), "reconciled": report.reconciled}
    text = json.dumps(payload, indent=2)
    print(text)
    if args.report:
        args.report.write_text(text + "\n")
    if not report.reconciled:
        print("ERROR: counts do not reconcile - records were lost", file=sys.stderr)
        return 2
    return 1 if report.failed else 0  # non-zero on failures so CI / schedulers notice


if __name__ == "__main__":
    raise SystemExit(main())
