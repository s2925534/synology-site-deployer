from __future__ import annotations

import os
from pathlib import Path

import pytest

from synology_site.commands.allow_third_party_drives import BACKUP_SUFFIX, STORAGE_DAEMON
from synology_site.commands.drive_compat_fix_plan import generate_drive_compat_fix_plan
from synology_site.errors import SynologySiteError
from synology_site.hdd_db import HDD_DB_REPO


def test_generate_drive_compat_fix_plan_writes_script_and_scheduler_examples(
    tmp_path: Path,
) -> None:
    result = generate_drive_compat_fix_plan(output_dir=tmp_path)

    assert result.output_dir == tmp_path
    filenames = {path.name for path in result.files}
    assert filenames == {
        "drive-compat-fix.sh",
        "README.md",
        "crontab.example",
        "synology-task-commands.txt",
    }

    script = result.output_dir / "drive-compat-fix.sh"
    content = script.read_text(encoding="utf-8")
    assert "/etc/synoinfo.conf" in content
    assert "/etc.defaults/synoinfo.conf" in content
    assert BACKUP_SUFFIX in content
    assert STORAGE_DAEMON in content
    assert "TARGET_FLAG='no'" in content
    assert os.access(script, os.X_OK)

    crontab = (result.output_dir / "crontab.example").read_text(encoding="utf-8")
    assert "@reboot" in crontab
    assert "drive-compat-fix.sh" in crontab

    tasks = (result.output_dir / "synology-task-commands.txt").read_text(encoding="utf-8")
    assert "drive-compat-fix.sh" in tasks

    readme = (result.output_dir / "README.md").read_text(encoding="utf-8")
    assert "DSM version update" in readme
    assert "Boot-up" in readme


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


class FakeSession:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files
        self.requested_urls: list[str] = []

    def get(self, url: str, timeout: int | None = None) -> FakeResponse:
        del timeout
        self.requested_urls.append(url)
        for filename, content in self.files.items():
            if url.endswith(filename):
                return FakeResponse(content)
        return FakeResponse("not found", status_code=404)


def test_include_hdd_db_bundles_pinned_script_and_generates_wrapper(tmp_path: Path) -> None:
    session = FakeSession(
        {
            "syno_hdd_db.sh": "#!/usr/bin/env bash\necho fake hdd db script\n",
            "syno_hdd_vendor_ids.txt": "vendor,id\n",
        }
    )

    result = generate_drive_compat_fix_plan(
        output_dir=tmp_path,
        include_hdd_db=True,
        hdd_db_version="v9.9.9",
        hdd_db_cache_dir=tmp_path / "vendor-cache",
        http_session=session,
    )

    filenames = {path.name for path in result.files}
    assert filenames == {
        "drive-compat-fix.sh",
        "README.md",
        "crontab.example",
        "synology-task-commands.txt",
        "syno_hdd_db.sh",
        "syno_hdd_vendor_ids.txt",
        "run-hdd-db-fix.sh",
    }
    assert all(f"{HDD_DB_REPO}/v9.9.9/" in url for url in session.requested_urls)

    bundled_script = (tmp_path / "syno_hdd_db.sh").read_text(encoding="utf-8")
    assert "fake hdd db script" in bundled_script
    assert os.access(tmp_path / "syno_hdd_db.sh", os.X_OK)

    wrapper = (tmp_path / "run-hdd-db-fix.sh").read_text(encoding="utf-8")
    assert "./syno_hdd_db.sh -s -n" in wrapper
    assert os.access(tmp_path / "run-hdd-db-fix.sh", os.X_OK)

    crontab = (tmp_path / "crontab.example").read_text(encoding="utf-8")
    assert "run-hdd-db-fix.sh" in crontab
    assert "drive-compat-fix.sh" not in crontab

    tasks = (tmp_path / "synology-task-commands.txt").read_text(encoding="utf-8")
    assert "run-hdd-db-fix.sh" in tasks

    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "v9.9.9" in readme
    assert "2025-series-or-later Plus models" in readme
    assert "This bundles third-party code" in readme


def test_include_hdd_db_raises_on_fetch_failure(tmp_path: Path) -> None:
    session = FakeSession({})  # every URL 404s

    with pytest.raises(SynologySiteError, match="Failed to fetch"):
        generate_drive_compat_fix_plan(
            output_dir=tmp_path,
            include_hdd_db=True,
            hdd_db_cache_dir=tmp_path / "vendor-cache",
            http_session=session,
        )
