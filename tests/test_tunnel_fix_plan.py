from __future__ import annotations

import os
from pathlib import Path

import pytest

from synology_site.commands.tunnel_fix_plan import generate_tunnel_fix_plan
from synology_site.errors import SynologySiteError


def test_generate_tunnel_fix_plan_writes_script_and_scheduler_examples(tmp_path: Path) -> None:
    result = generate_tunnel_fix_plan(output_dir=tmp_path, interval_minutes=10)

    assert result.output_dir == tmp_path
    filenames = {path.name for path in result.files}
    assert filenames == {
        "tunnel-fix.sh",
        "README.md",
        "crontab.example",
        "synology-task-command.txt",
    }

    script = result.output_dir / "tunnel-fix.sh"
    content = script.read_text(encoding="utf-8")
    assert 'CONTAINER_NAME="cloudflared"' in content
    assert "update --restart unless-stopped" in content
    assert os.access(script, os.X_OK)

    crontab = (result.output_dir / "crontab.example").read_text(encoding="utf-8")
    assert "*/10 * * * *" in crontab
    assert "tunnel-fix.sh" in crontab

    task = (result.output_dir / "synology-task-command.txt").read_text(encoding="utf-8")
    assert "tunnel-fix.sh" in task

    readme = (result.output_dir / "README.md").read_text(encoding="utf-8")
    assert "10 minutes" in readme


def test_generate_tunnel_fix_plan_rejects_invalid_interval(tmp_path: Path) -> None:
    with pytest.raises(SynologySiteError, match="interval-minutes"):
        generate_tunnel_fix_plan(output_dir=tmp_path, interval_minutes=0)


def test_generate_tunnel_fix_plan_rejects_empty_container_name(tmp_path: Path) -> None:
    with pytest.raises(SynologySiteError, match="container-name"):
        generate_tunnel_fix_plan(output_dir=tmp_path, container_name="  ")
