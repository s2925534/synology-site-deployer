from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import typer

from synology_site.commands.allow_third_party_drives import (
    BACKUP_SUFFIX,
    STORAGE_DAEMON,
    SYNOINFO_PATHS,
)
from synology_site.errors import SynologySiteError
from synology_site.hdd_db import DEFAULT_CACHE_DIR, DEFAULT_HDD_DB_VERSION, fetch_hdd_db_files
from synology_site.output import console, next_step, ok


@dataclass(frozen=True)
class DriveCompatFixPlanResult:
    output_dir: Path
    files: tuple[Path, ...]


def generate_drive_compat_fix_plan(
    *,
    output_dir: Path = Path("drive-compat-fix-plan"),
    include_hdd_db: bool = False,
    hdd_db_version: str = DEFAULT_HDD_DB_VERSION,
    hdd_db_cache_dir: Path = DEFAULT_CACHE_DIR,
    http_session: Any = requests,
) -> DriveCompatFixPlanResult:
    output_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "drive-compat-fix.sh": _fix_script(),
        "README.md": _readme(include_hdd_db=include_hdd_db, hdd_db_version=hdd_db_version),
        "crontab.example": _crontab(output_dir, include_hdd_db=include_hdd_db),
        "synology-task-commands.txt": _synology_task_commands(
            output_dir, include_hdd_db=include_hdd_db
        ),
    }
    executable = {"drive-compat-fix.sh"}

    if include_hdd_db:
        fetched = fetch_hdd_db_files(
            hdd_db_version, cache_dir=hdd_db_cache_dir, session=http_session
        )
        files["syno_hdd_db.sh"] = fetched["syno_hdd_db.sh"]
        files["syno_hdd_vendor_ids.txt"] = fetched["syno_hdd_vendor_ids.txt"]
        files["run-hdd-db-fix.sh"] = _run_hdd_db_script()
        executable |= {"syno_hdd_db.sh", "run-hdd-db-fix.sh"}

    written: list[Path] = []
    for filename, content in files.items():
        path = output_dir / filename
        path.write_text(content, encoding="utf-8")
        written.append(path)
        if filename in executable:
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
      pattern='s/support_disk_compatibility="[^"]*"/support_disk_compatibility="'"$TARGET_FLAG"'"/'
      sed -i "$pattern" "$f"
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


def _run_hdd_db_script() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

# Runs the bundled, pinned syno_hdd_db.sh from https://github.com/007revad/Synology_HDD_db --
# see README.md for exactly which release is bundled and why. This is the fix that actually
# matters on 2025-series-or-later Plus models (confirmed on a real DS1525+): it adds the
# installed drives' own model+firmware as explicit "supported" entries in DSM's per-model
# compatibility database, which is what let Storage Manager create a volume, not just a pool,
# on third-party NVMe drives. It also re-enables support_disk_compatibility itself -- with
# correct per-drive entries in place, that's the right end state, not a global bypass.
#
# -s (--showedits) logs exactly what it changed; -n (--noupdate) stops DSM's own periodic
# compatible-drive-database refresh from silently overwriting these entries later, which is the
# actual reason this needs to be re-run on every boot rather than just once.

if [[ "$(id -u)" -ne 0 ]]; then
  echo "must run as root" >&2
  exit 1
fi

cd "$(dirname "$0")"
./syno_hdd_db.sh -s -n
"""


def _readme(*, include_hdd_db: bool, hdd_db_version: str) -> str:
    hdd_db_section = ""
    if include_hdd_db:
        hdd_db_section = f"""
## The real fix for 2025-series-or-later Plus models: `run-hdd-db-fix.sh`

Disabling `support_disk_compatibility` (what `drive-compat-fix.sh` does) is enough to let
Storage Manager *create a pool* from third-party drives. On 2025-series-or-later Plus models
(confirmed on a real DS1525+) it is **not** enough to create a *volume* on that pool -- DSM
separately checks each drive's exact model+firmware against a per-model compatibility database,
and an unlisted drive shows as "Unrecognized"/Critical and blocks volume creation, flag or no
flag. See Synology's own notes:
https://kb.synology.com/en-global/DSM/tutorial/Drive_compatibility_policies

`run-hdd-db-fix.sh` runs a bundled, pinned copy of
[`007revad/Synology_HDD_db`](https://github.com/007revad/Synology_HDD_db) (release
`{hdd_db_version}`, downloaded once when this plan was generated -- not fetched live from the
NAS at boot time) with `-s -n`: it adds your installed drives' model+firmware as explicit
supported entries in the compatibility database, then re-enables `support_disk_compatibility`
(with correct entries in place, that's the right end state, not a bypass). `-n` also stops DSM's
own periodic compatible-drive-database refresh from silently overwriting those entries later --
the actual reason this needs to run on every boot, not just once.

**This bundles third-party code.** Read `syno_hdd_db.sh` before trusting it on your NAS. To
bundle a different/newer pinned release, re-run `drive-compat-fix-plan --include-hdd-db
--hdd-db-version vX.Y.Z`.

With this bundled, schedule **`run-hdd-db-fix.sh`** on Boot-up instead of (not in addition to)
`drive-compat-fix.sh` -- running both would fight over the same flag on every boot.
`drive-compat-fix.sh` is still generated as a lighter fallback that doesn't require trusting
third-party code, but it won't fully resolve the "Unrecognized" volume-creation block on its own
on these models.
"""

    schedule_target = "run-hdd-db-fix.sh" if include_hdd_db else "drive-compat-fix.sh"
    return f"""# Drive Compatibility Fix Plan

`drive-compat-fix.sh` -- keeps DSM's `support_disk_compatibility` flag disabled across reboots
*and* DSM version updates, so a storage pool built from non-Synology-certified drives (see
`allow-third-party-drives`) doesn't get silently stranded.
{hdd_db_section}
## Why a scheduled script instead of just running `allow-third-party-drives` once

`allow-third-party-drives` fixes the flag right now, over SSH, on demand. But a DSM **version
update** (not a routine reboot) can regenerate `/etc/synoinfo.conf` from
`/etc.defaults/synoinfo.conf`, or refresh Synology's certified-drive database, and silently flip
the flag back -- which can make an existing pool built from those drives show as "missing" with
online assembly failing, not just a cosmetic warning. This re-applies the fix on every boot
(including the reboot every DSM update ends with), so that scenario is caught automatically
instead of requiring you to notice and SSH in.

## What `drive-compat-fix.sh` does

1. Backs up both `synoinfo.conf` copies (once, only if no backup already exists).
2. Sets `support_disk_compatibility="no"` in both, only if it isn't already.
3. Restarts {STORAGE_DAEMON} only if something actually changed -- a no-op boot costs nothing.

## Schedule it (DSM Task Scheduler -- recommended)

1. Copy `{schedule_target}`{" and syno_hdd_db.sh/syno_hdd_vendor_ids.txt" if include_hdd_db else ""}
   to the NAS, e.g. `/volume3/dockernvme/drive-compat-fix/`.
2. DSM > Control Panel > Task Scheduler > Create > Triggered Task > Boot-up.
3. User: `root`. Run command: see `synology-task-commands.txt`.
4. Save, then run it once manually (right-click > Run) to confirm it exits cleanly before relying
   on it at the next reboot/update.

## Alternative: crontab

See `crontab.example` for a `crontab -e` entry (as root) using `@reboot` instead of DSM Task
Scheduler.

## After any DSM update

Even with this scheduled, it's worth a quick manual check of Storage Manager after a DSM update
to confirm the pool/volume mounted correctly -- this removes the most common cause of it not
doing so, not every conceivable one.
"""


def _crontab(plan_dir: Path, *, include_hdd_db: bool) -> str:
    resolved = plan_dir.resolve()
    script = "run-hdd-db-fix.sh" if include_hdd_db else "drive-compat-fix.sh"
    return (
        "# As root (editing synoinfo.conf and restarting the storage daemon both need root).\n"
        f"@reboot {resolved}/{script} >> {resolved}/{script}.log 2>&1\n"
    )


def _synology_task_commands(plan_dir: Path, *, include_hdd_db: bool) -> str:
    resolved = plan_dir.resolve()
    script = "run-hdd-db-fix.sh" if include_hdd_db else "drive-compat-fix.sh"
    return f"# Boot-up triggered task (run {script}):\nbash {resolved}/{script}\n"


def app(
    output_dir: Path = typer.Option(Path("drive-compat-fix-plan"), "--output-dir"),  # noqa: B008
    include_hdd_db: bool = typer.Option(
        False,
        "--include-hdd-db",
        help="Also bundle a pinned copy of 007revad/Synology_HDD_db and generate "
        "run-hdd-db-fix.sh -- the fix that's actually needed for volume creation (not just pool "
        "creation) on 2025-series-or-later Plus models. Downloads third-party code; see "
        "README.md before trusting it.",
    ),
    hdd_db_version: str = typer.Option(
        DEFAULT_HDD_DB_VERSION,
        "--hdd-db-version",
        help="Pinned Synology_HDD_db release tag to bundle (only used with --include-hdd-db).",
    ),
) -> None:
    """Generates a boot-time script that keeps third-party drives allowed across DSM updates.

    Pair this with `allow-third-party-drives` (which fixes the flag right now) -- this is the
    unattended safety net so a future DSM update can't silently re-block the drives and strand a
    storage pool/volume built from them. Pass --include-hdd-db to also bundle the fix that's
    actually needed for volume creation on 2025-series-or-later Plus models.
    """
    try:
        result = generate_drive_compat_fix_plan(
            output_dir=output_dir, include_hdd_db=include_hdd_db, hdd_db_version=hdd_db_version
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Drive Compatibility Fix Plan")
    ok(f"Generated: {result.output_dir}")
    for path in result.files:
        ok(str(path))
    script_to_schedule = "run-hdd-db-fix.sh" if include_hdd_db else "drive-compat-fix.sh"
    next_step(
        f"Copy {script_to_schedule} to the NAS and schedule it with DSM Task Scheduler (Boot-up "
        "trigger, run as root) -- see README.md."
    )
