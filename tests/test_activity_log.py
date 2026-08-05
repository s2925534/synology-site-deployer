from __future__ import annotations

import json
from pathlib import Path

from synology_site.activity_log import record_activity


def test_record_activity_appends_jsonl_entry(tmp_path: Path) -> None:
    log_dir = tmp_path / "activity-log"

    record_activity("create", details={"domain": "demo.example.com"}, log_dir=log_dir)

    lines = (log_dir / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["action"] == "create"
    assert entry["domain"] == "demo.example.com"
    assert "timestamp" in entry


def test_record_activity_appends_multiple_entries(tmp_path: Path) -> None:
    log_dir = tmp_path / "activity-log"

    record_activity("create", details={"domain": "a.example.com"}, log_dir=log_dir)
    record_activity("deploy", details={"domain": "b.example.com"}, log_dir=log_dir)

    lines = (log_dir / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["action"] == "create"
    assert json.loads(lines[1])["action"] == "deploy"


def test_record_activity_creates_log_dir_if_missing(tmp_path: Path) -> None:
    log_dir = tmp_path / "nested" / "activity-log"

    record_activity("update", log_dir=log_dir)

    assert (log_dir / "history.jsonl").is_file()


def test_record_activity_works_with_no_details() -> None:
    # Must not raise -- details is optional.
    record_activity("create", log_dir=Path("/nonexistent-should-be-swallowed/activity-log"))


def test_record_activity_swallows_oserror_instead_of_raising() -> None:
    # A path that can never be created (root has no writable "\0" segment) should not raise --
    # logging failures must never break the calling command.
    record_activity("create", log_dir=Path("/dev/null/impossible/activity-log"))


def test_record_activity_uses_custom_log_filename(tmp_path: Path) -> None:
    log_dir = tmp_path / "activity-log"

    record_activity("create", log_dir=log_dir, log_filename="custom.jsonl")

    assert (log_dir / "custom.jsonl").is_file()
    assert not (log_dir / "history.jsonl").exists()
