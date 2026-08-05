from __future__ import annotations

import os
from pathlib import Path

from synology_site.commands.allow_third_party_drives import BACKUP_SUFFIX, STORAGE_DAEMON
from synology_site.commands.drive_compat_fix_plan import generate_drive_compat_fix_plan


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
