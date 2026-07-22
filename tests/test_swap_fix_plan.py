from __future__ import annotations

import os
from pathlib import Path

import pytest

from synology_site.commands.swap_fix_plan import generate_swap_fix_plan
from synology_site.errors import SynologySiteError


def test_generate_swap_fix_plan_writes_scripts_and_scheduler_examples(tmp_path: Path) -> None:
    result = generate_swap_fix_plan(output_dir=tmp_path, swap_size_gb=8, interval_hours=6)

    assert result.output_dir == tmp_path
    filenames = {path.name for path in result.files}
    assert filenames == {
        "swap-setup.sh",
        "swap-release.sh",
        "README.md",
        "crontab.example",
        "synology-task-commands.txt",
    }

    setup_script = result.output_dir / "swap-setup.sh"
    setup_content = setup_script.read_text(encoding="utf-8")
    assert 'SWAP_FILE="/volume1/swapfile"' in setup_content
    assert "SWAP_SIZE_GB=8" in setup_content
    assert "SWAPPINESS=10" in setup_content
    assert os.access(setup_script, os.X_OK)

    release_script = result.output_dir / "swap-release.sh"
    release_content = release_script.read_text(encoding="utf-8")
    assert 'SWAP_FILE="/volume1/swapfile"' in release_content
    assert "swapoff -a" in release_content
    assert os.access(release_script, os.X_OK)

    crontab = (result.output_dir / "crontab.example").read_text(encoding="utf-8")
    assert "@reboot" in crontab
    assert "0 */6 * * *" in crontab

    tasks = (result.output_dir / "synology-task-commands.txt").read_text(encoding="utf-8")
    assert "swap-setup.sh" in tasks
    assert "swap-release.sh" in tasks

    readme = (result.output_dir / "README.md").read_text(encoding="utf-8")
    assert "8G swap file" in readme
    assert "6 hours" in readme


def test_generate_swap_fix_plan_rejects_invalid_swap_size(tmp_path: Path) -> None:
    with pytest.raises(SynologySiteError, match="swap-size-gb"):
        generate_swap_fix_plan(output_dir=tmp_path, swap_size_gb=0)


def test_generate_swap_fix_plan_rejects_invalid_swappiness(tmp_path: Path) -> None:
    with pytest.raises(SynologySiteError, match="swappiness"):
        generate_swap_fix_plan(output_dir=tmp_path, swappiness=101)


def test_generate_swap_fix_plan_rejects_invalid_interval(tmp_path: Path) -> None:
    with pytest.raises(SynologySiteError, match="interval-hours"):
        generate_swap_fix_plan(output_dir=tmp_path, interval_hours=0)


def test_generate_swap_fix_plan_rejects_relative_swap_file_path(tmp_path: Path) -> None:
    with pytest.raises(SynologySiteError, match="swap-file-path"):
        generate_swap_fix_plan(output_dir=tmp_path, swap_file_path="swapfile")
