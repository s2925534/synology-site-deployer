from __future__ import annotations

import os
from pathlib import Path

import pytest

from synology_site.commands.backup_plan import generate_backup_plan
from synology_site.errors import SynologySiteError


def test_generate_backup_plan_writes_script_env_and_scheduler_examples(tmp_path: Path) -> None:
    result = generate_backup_plan(
        "app.example.com",
        output_dir=tmp_path,
        retention_days=30,
    )

    assert result.output_dir == tmp_path / "app-example-com"
    filenames = {path.name for path in result.files}
    assert filenames == {
        "backup.sh",
        "backup.env.example",
        "README.md",
        "crontab.example",
        "synology-task-command.txt",
    }

    env = (result.output_dir / "backup.env.example").read_text(encoding="utf-8")
    assert "DB_CONTAINER=app-example-com-db" in env
    assert "DB_NAME=app_example_com" in env
    assert "DB_USER=app_example_com_user" in env
    assert "RETENTION_DAYS=30" in env
    assert "S3_BUCKET=" in env

    script = result.output_dir / "backup.sh"
    content = script.read_text(encoding="utf-8")
    assert "mariadb-dump" in content
    assert "aws \"${endpoint_args[@]}\" s3 cp" in content
    assert os.access(script, os.X_OK)

    task = (result.output_dir / "synology-task-command.txt").read_text(encoding="utf-8")
    assert "backup.sh" in task
    assert "backup.env" in task


def test_generate_backup_plan_rejects_invalid_retention(tmp_path: Path) -> None:
    with pytest.raises(SynologySiteError, match="retention"):
        generate_backup_plan("app.example.com", output_dir=tmp_path, retention_days=0)
