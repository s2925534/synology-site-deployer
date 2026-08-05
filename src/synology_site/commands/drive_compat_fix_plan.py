from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

import typer

from synology_site.commands.allow_third_party_drives import (
    BACKUP_SUFFIX,
    STORAGE_DAEMON,
    SYNOINFO_PATHS,
)
from synology_site.errors import SynologySiteError
from synology_site.output import console, next_step, ok


@dataclass(frozen=True)
class DriveCompatFixPlanResult:
    output_dir: Path
    files: tuple[Path, ...]


def generate_drive_compat_fix_plan(
    *, output_dir: Path = Path("drive-compat-fix-plan")
) -> DriveCompatFixPlanResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "drive-compat-fix.sh": _fix_script(),
        "README.md": _readme(),
        "crontab.example": _crontab(output_dir),
        "synology-task-commands.txt": _synology_task_commands(output_dir),
    }
    written: list[Path] = []
    for filename, content in files.items():
        path = output_dir / filename
        path.write_text(content, encoding="utf-8")
        written.append(path)
        if filename == "drive-compat-fix.sh":
            path.chmod(path.stat().st_mode | stat.S_IXUSR)

    return DriveCompatFixPlanResult(output_dir=output_dir, files=tuple(written))


def _fix_script() -> str:
    paths_literal = " ".join(f'"{path}"' for path in SYNOINFO_PATHS)
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Runs directly on the NAS (DSM Task Scheduler Boot-up trigger or crontab @reboot) -- no SSH hop,
# no Python. Idempotent and a no-op once the flag is already correct, so it's safe to run on
# every single boot indefinitely.
#
# Why this exists: a DSM *version update* (not a routine reboot) can regenerate
# /etc/synoinfo.conf from /etc.defaults/synoinfo.conf, or refresh Synology's certified-drive
# database, silently re-enabling support_disk_compatibility and re-blocking third-party drives --
# which can make an existing storage pool built from them show as "missing" with online assemble
# failing, not just a cosmetic warning in Storage Manager. This re-applies the fix before Storage
# Manager gets a chance to act on that stale state.

if [[ "$(id -u)" -ne 0 ]]; then
  echo "must run as root (needs to edit synoinfo.conf and restart {STORAGE_DAEMON})" >&2
  exit 1
fi

TARGET_FLAG='no'
CHANGED=0

for f in {paths_literal}; do
  if [[ -f "$f" ]]; then
    [[ -f "${{f}}{BACKUP_SUFFIX}" ]] || cp "$f" "${{f}}{BACKUP_SUFFIX}"
    if ! grep -q "support_disk_compatibility=\\"$TARGET_FLAG\\"" "$f"; then
      sed -i "s/support_disk_compatibility=\\"[^\\"]*\\"/support_disk_compatibility=\\"$TARGET_FLAG\\"/" "$f"
      CHANGED=1
    fi
  fi
done

if [[ "$CHANGED" -eq 1 ]]; then
  if command -v /usr/syno/bin/synosystemctl >/dev/null 2>&1; then
    /usr/syno/bin/synosystemctl restart {STORAGE_DAEMON}
  elif command -v /usr/syno/bin/synoservicectl >/dev/null 2>&1; then
    /usr/syno/bin/synoservicectl --restart {STORAGE_DAEMON}
  fi
  echo "support_disk_compatibility reset to \\"$TARGET_FLAG\\" and {STORAGE_DAEMON} restarted"
else
  echo "support_disk_compatibility already \\"$TARGET_FLAG\\" -- nothing to do"
fi
"""


def _readme() -> str:
    return f"""# Drive Compatibility Fix Plan

`drive-compat-fix.sh` -- keeps DSM's `support_disk_compatibility` flag disabled across reboots
*and* DSM version updates, so a storage pool built from non-Synology-certified drives (see
`allow-third-party-drives`) doesn't get silently stranded.

## Why a scheduled script instead of just running `allow-third-party-drives` once

`allow-third-party-drives` fixes the flag right now, over SSH, on demand. But a DSM **version
update** (not a routine reboot) can regenerate `/etc/synoinfo.conf` from
`/etc.defaults/synoinfo.conf`, or refresh Synology's certified-drive database, and silently flip
the flag back -- which can make an existing pool built from those drives show as "missing" with
online assembly failing, not just a cosmetic warning. This script re-applies the fix on every
boot (including the reboot every DSM update ends with), so that scenario is caught automatically
instead of requiring you to notice and SSH in.

## What it does

1. Backs up both `synoinfo.conf` copies (once, only if no backup already exists).
2. Sets `support_disk_compatibility="no"` in both, only if it isn't already.
3. Restarts {STORAGE_DAEMON} only if something actually changed -- a no-op boot costs nothing.

## Schedule it (DSM Task Scheduler -- recommended)

1. Copy `drive-compat-fix.sh` to the NAS, e.g. `/volume1/docker/drive-compat-fix/drive-compat-fix.sh`.
2. DSM > Control Panel > Task Scheduler > Create > Triggered Task > Boot-up.
3. User: `root`. Run command: see `synology-task-commands.txt`.
4. Save, then run it once manually (right-click > Run) to confirm it exits cleanly before relying
   on it at the next reboot/update.

## Alternative: crontab

See `crontab.example` for a `crontab -e` entry (as root) using `@reboot` instead of DSM Task
Scheduler.

## After any DSM update

Even with this scheduled, it's worth a quick manual check of Storage Manager after a DSM update
to confirm the pool/volume mounted correctly -- this script removes the most common cause of it
not doing so, not every conceivable one.
"""


def _crontab(plan_dir: Path) -> str:
    resolved = plan_dir.resolve()
    return (
        "# As root (editing synoinfo.conf and restarting the storage daemon both need root).\n"
        f"@reboot {resolved}/drive-compat-fix.sh >> {resolved}/drive-compat-fix.log 2>&1\n"
    )


def _synology_task_commands(plan_dir: Path) -> str:
    resolved = plan_dir.resolve()
    return f"# Boot-up triggered task (run drive-compat-fix.sh):\nbash {resolved}/drive-compat-fix.sh\n"


def app(
    output_dir: Path = typer.Option(Path("drive-compat-fix-plan"), "--output-dir"),  # noqa: B008
) -> None:
    """Generates a boot-time script that keeps third-party drives allowed across DSM updates.

    Pair this with `allow-third-party-drives` (which fixes the flag right now) -- this is the
    unattended safety net so a future DSM update can't silently re-block the drives and strand a
    storage pool/volume built from them.
    """
    try:
        result = generate_drive_compat_fix_plan(output_dir=output_dir)
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Drive Compatibility Fix Plan")
    ok(f"Generated: {result.output_dir}")
    for path in result.files:
        ok(str(path))
    next_step(
        "Copy drive-compat-fix.sh to the NAS and schedule it with DSM Task Scheduler (Boot-up "
        "trigger, run as root) -- see README.md. It's a no-op once the flag is already correct, "
        "so it's safe to run on every boot indefinitely."
    )
