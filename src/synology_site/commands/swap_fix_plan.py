from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

import typer

from synology_site.errors import SynologySiteError
from synology_site.output import console, next_step, ok


@dataclass(frozen=True)
class SwapFixPlanResult:
    output_dir: Path
    files: tuple[Path, ...]


def generate_swap_fix_plan(
    *,
    output_dir: Path = Path("swap-fix-plan"),
    swap_file_path: str = "/volume1/swapfile",
    swap_size_gb: int = 4,
    swappiness: int = 10,
    interval_hours: int = 24,
) -> SwapFixPlanResult:
    if swap_size_gb < 1:
        raise SynologySiteError("--swap-size-gb must be at least 1")
    if not (0 <= swappiness <= 100):
        raise SynologySiteError("--swappiness must be between 0 and 100")
    if interval_hours < 1:
        raise SynologySiteError("--interval-hours must be at least 1")
    if not swap_file_path.startswith("/"):
        raise SynologySiteError("--swap-file-path must be an absolute path")

    output_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "swap-setup.sh": _swap_setup_script(
            swap_file_path=swap_file_path, swap_size_gb=swap_size_gb, swappiness=swappiness
        ),
        "swap-release.sh": _swap_release_script(swap_file_path=swap_file_path),
        "README.md": _readme(
            swap_file_path=swap_file_path,
            swap_size_gb=swap_size_gb,
            swappiness=swappiness,
            interval_hours=interval_hours,
        ),
        "crontab.example": _crontab(output_dir, interval_hours=interval_hours),
        "synology-task-commands.txt": _synology_task_commands(output_dir),
    }
    written: list[Path] = []
    for filename, content in files.items():
        path = output_dir / filename
        path.write_text(content, encoding="utf-8")
        written.append(path)
        if filename in {"swap-setup.sh", "swap-release.sh"}:
            path.chmod(path.stat().st_mode | stat.S_IXUSR)

    return SwapFixPlanResult(output_dir=output_dir, files=tuple(written))


def _swap_setup_script(*, swap_file_path: str, swap_size_gb: int, swappiness: int) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Runs directly on the NAS (via DSM Task Scheduler Boot-up trigger or crontab @reboot) -- no SSH
# hop, no Python. Idempotent: safe to run on every boot even if the swap file already exists,
# is the right size, and is already active -- it only acts on what's actually missing/wrong.
#
# Deliberately uses a swap FILE, not a resized swap partition: Synology only sizes the swap
# partition at volume creation, and changing it means recreating the volume (destructive to
# existing data). A swap file on top of the existing volume needs no reformat.
#
# Btrfs (Synology's default volume filesystem) requires copy-on-write disabled on a swap file
# (`chattr +C`) before any data is written to it -- swapon fails with "Invalid argument"
# otherwise. `chattr +C` must be applied while the file is still empty; nodatacow only affects
# extents written after the attribute is set, not data already on disk. It's a no-op error on
# non-Btrfs filesystems (e.g. ext4 has no COW to disable), so it's safe to attempt unconditionally
# and ignore failure. `fallocate` is deliberately not used to write the data: on some Btrfs/kernel
# combinations it can produce extents swapon still rejects even with nodatacow set; a plain `dd`
# write is what's actually documented to work.

SWAP_FILE="{swap_file_path}"
SWAP_SIZE_GB={swap_size_gb}
SWAPPINESS={swappiness}

if [[ "$(id -u)" -ne 0 ]]; then
  echo "must run as root (needs mkswap/swapon)" >&2
  exit 1
fi

is_active() {{
  grep -q "^$SWAP_FILE " /proc/swaps
}}

target_size_bytes=$(( SWAP_SIZE_GB * 1024 * 1024 * 1024 ))
current_size_bytes=0
if [[ -f "$SWAP_FILE" ]]; then
  current_size_bytes=$(stat -c%s "$SWAP_FILE" 2>/dev/null || stat -f%z "$SWAP_FILE")
fi

if [[ "$current_size_bytes" -ne "$target_size_bytes" ]]; then
  if is_active; then
    swapoff "$SWAP_FILE"
  fi
  rm -f "$SWAP_FILE"
  touch "$SWAP_FILE"
  chattr +C "$SWAP_FILE" 2>/dev/null || true
  dd if=/dev/zero of="$SWAP_FILE" bs=1M count=$(( SWAP_SIZE_GB * 1024 )) status=none
  chmod 600 "$SWAP_FILE"
  mkswap "$SWAP_FILE" >/dev/null
  echo "Created ${{SWAP_SIZE_GB}}G swap file at $SWAP_FILE (replaced previous file/size)"
fi

if is_active; then
  echo "$SWAP_FILE already active"
else
  swapon "$SWAP_FILE"
  echo "Activated $SWAP_FILE"
fi

sysctl -w vm.swappiness="$SWAPPINESS" >/dev/null
echo "vm.swappiness set to $SWAPPINESS (resets on reboot -- rerun via Boot-up trigger to reapply)"
"""


def _swap_release_script(*, swap_file_path: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Runs directly on the NAS on a schedule (DSM Task Scheduler or crontab). Linux doesn't proactively
# move pages back from swap to RAM once memory pressure passes, so swap usage tends to stay high
# long after the spike that caused it. This reclaims it -- but only when there's enough free RAM to
# safely absorb what's in swap; swapoff under real memory pressure can hang the box or trigger an
# OOM instead of helping, so it's not safe to run unconditionally.

SWAP_FILE="{swap_file_path}"

free_mb=$(free -m | awk '/^Mem:/{{print $7}}')
swap_used_mb=$(free -m | awk '/^Swap:/{{print $3}}')

if [[ -z "$free_mb" || -z "$swap_used_mb" ]]; then
  echo "could not read memory stats from 'free -m'" >&2
  exit 1
fi

if [[ "$swap_used_mb" -eq 0 ]]; then
  echo "swap already at 0MB used, nothing to release"
  exit 0
fi

if [[ "$free_mb" -gt "$swap_used_mb" ]]; then
  swapoff -a
  # Re-enable explicitly rather than `swapon -a`: the swap file is activated directly by
  # swap-setup.sh, not registered in fstab (Synology can wipe fstab-style persistence on DSM
  # updates), so `swapon -a` alone would not bring it back.
  swapon "$SWAP_FILE"
  echo "released swap: ${{swap_used_mb}}MB was in swap, ${{free_mb}}MB RAM was free before release"
else
  echo "skipped: only ${{free_mb}}MB free but ${{swap_used_mb}}MB in swap -- not enough headroom"
fi
"""


def _readme(*, swap_file_path: str, swap_size_gb: int, swappiness: int, interval_hours: int) -> str:
    return f"""# Swap Fix Plan

Two generated scripts for managing NAS swap: `swap-setup.sh` (one-time capacity fix, safe to
rerun) and `swap-release.sh` (ongoing maintenance to reclaim swap that's stuck "used" after a
memory spike passes).

## `swap-setup.sh` -- increase swap size

Synology doesn't expose swap resizing in the DSM GUI; the swap partition is fixed at volume
creation. This script creates a **swap file** on top of the existing volume instead, so no
reformat/data loss risk:

1. Creates/replaces `{swap_file_path}` as a {swap_size_gb}G swap file if it doesn't already exist
   at that exact size.
2. Activates it if not already active.
3. Sets `vm.swappiness={swappiness}` (default is usually 60; lower makes the kernel prefer RAM
   over swap).

**Run it once, during a quiet/low-load window** -- not while swap is already near-full under
active load, since recreating the file involves briefly deactivating any existing swap file of
the wrong size.

### Schedule it (DSM Task Scheduler)

1. Copy `swap-setup.sh` to the NAS, e.g. `/volume1/docker/swap-fix/swap-setup.sh`.
2. DSM > Control Panel > Task Scheduler > Create > Triggered Task > Boot-up.
3. User: `root`. Run command: see `synology-task-commands.txt`.
4. Save, then run it once manually (right-click > Run) to confirm it exits cleanly before relying
   on it at the next reboot.

This re-applies `vm.swappiness` on every boot too, since that setting itself resets on reboot even
though the swap file persists.

## `swap-release.sh` -- automatic swap release

Reclaims swap on a schedule, but only when it's actually safe:

- Reads free RAM and swap-in-use from `free -m`.
- Only runs `swapoff`/`swapon` (which moves swapped pages back into RAM) if free RAM exceeds swap
  currently in use -- otherwise it skips and logs why, rather than risking a hang/OOM.

### Schedule it (DSM Task Scheduler)

1. Copy `swap-release.sh` to the NAS alongside `swap-setup.sh`.
2. DSM > Control Panel > Task Scheduler > Create > Scheduled Task > User-defined script.
3. Set it to run every {interval_hours} hours (or the closest interval your DSM version's
   scheduler UI supports).
4. User: `root`. Run command: see `synology-task-commands.txt`.

## Alternative: crontab

If you'd rather manage this over SSH than through the DSM GUI, see `crontab.example` for
`crontab -e` entries (as root, since both scripts need root) -- `@reboot` for the setup script,
every {interval_hours} hours for the release script.

## Notes

- A bigger swap file and scheduled release make an already-tight NAS more resilient, but they
  don't fix the underlying cause if the real problem is too many containers/workloads for the
  installed RAM -- treat this as a safety margin, not a substitute for right-sizing the fleet.
- Don't run `swap-release.sh` manually while swap is already critically full under active load;
  its own internal check should skip in that case, but there's no reason to force it.
- Neither script touches Docker, container state, or any deployed site -- they only manage the
  NAS's own swap file and kernel `vm.swappiness` setting.
"""


def _crontab(plan_dir: Path, *, interval_hours: int) -> str:
    resolved = plan_dir.resolve()
    release_line = (
        f"0 */{interval_hours} * * * {resolved}/swap-release.sh"
        f" >> {resolved}/swap-release.log 2>&1\n"
    )
    return (
        "# As root (both scripts need root for swapon/mkswap).\n"
        f"@reboot {resolved}/swap-setup.sh >> {resolved}/swap-setup.log 2>&1\n" + release_line
    )


def _synology_task_commands(plan_dir: Path) -> str:
    resolved = plan_dir.resolve()
    return (
        f"# Boot-up triggered task (run swap-setup.sh):\n"
        f"bash {resolved}/swap-setup.sh\n\n"
        f"# Scheduled task (run swap-release.sh):\n"
        f"bash {resolved}/swap-release.sh\n"
    )


def app(
    output_dir: Path = typer.Option(Path("swap-fix-plan"), "--output-dir"),  # noqa: B008
    swap_file_path: str = typer.Option("/volume1/swapfile", "--swap-file-path"),
    swap_size_gb: int = typer.Option(4, "--swap-size-gb"),
    swappiness: int = typer.Option(10, "--swappiness"),
    interval_hours: int = typer.Option(24, "--interval-hours"),
) -> None:
    try:
        result = generate_swap_fix_plan(
            output_dir=output_dir,
            swap_file_path=swap_file_path,
            swap_size_gb=swap_size_gb,
            swappiness=swappiness,
            interval_hours=interval_hours,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Swap Fix Plan")
    ok(f"Generated: {result.output_dir}")
    for path in result.files:
        ok(str(path))
    next_step(
        "Copy both scripts to the NAS and schedule them with DSM Task Scheduler or crontab -- "
        "see README.md. Run swap-setup.sh once manually first, during a quiet window."
    )
