import json
from pathlib import Path

from scripts.migrate import main, migrate

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "legacy_export.xml"


def test_first_run_creates_and_reports_failures(isolated_db):
    r = migrate(SAMPLE, isolated_db)
    assert (r.source_count, r.created, r.unchanged, r.failed) == (4, 3, 0, 1)
    assert r.failures[0]["legacy_id"] == "L-1004"
    assert r.reconciled


def test_second_run_is_idempotent(isolated_db):
    migrate(SAMPLE, isolated_db)
    r = migrate(SAMPLE, isolated_db)
    assert (r.created, r.updated, r.unchanged) == (0, 0, 3)


def test_changed_source_record_is_updated(isolated_db, tmp_path):
    migrate(SAMPLE, isolated_db)
    changed = tmp_path / "changed.xml"
    changed.write_text(SAMPLE.read_text().replace("Spell out numbers one to nine", "Spell out one to ten"))
    r = migrate(changed, isolated_db)
    assert (r.updated, r.unchanged) == (1, 2)


def test_dry_run_writes_nothing(isolated_db):
    r = migrate(SAMPLE, isolated_db, dry_run=True)
    assert r.created == 3
    assert migrate(SAMPLE, isolated_db).created == 3  # still 3: the dry run stored nothing


def test_cli_writes_report_and_exits_nonzero_on_failures(isolated_db, tmp_path):
    report = tmp_path / "report.json"
    code = main([str(SAMPLE), "--db", str(isolated_db), "--report", str(report)])
    assert code == 1
    assert json.loads(report.read_text())["reconciled"] is True
