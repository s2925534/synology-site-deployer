from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

import typer

from synology_site.errors import SynologySiteError
from synology_site.output import console, next_step, ok


@dataclass(frozen=True)
class TunnelFixPlanResult:
    output_dir: Path
    files: tuple[Path, ...]


def generate_tunnel_fix_plan(
    *,
    output_dir: Path = Path("tunnel-fix-plan"),
    container_name: str = "cloudflared",
    interval_minutes: int = 15,
) -> TunnelFixPlanResult:
    if interval_minutes < 1:
        raise SynologySiteError("--interval-minutes must be at least 1")
    if not container_name.strip():
        raise SynologySiteError("--container-name must not be empty")

    output_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "tunnel-fix.sh": _tunnel_fix_script(container_name=container_name),
        "README.md": _readme(container_name=container_name, interval_minutes=interval_minutes),
        "crontab.example": _crontab(output_dir, interval_minutes=interval_minutes),
        "synology-task-command.txt": _synology_task_command(output_dir),
    }
    written: list[Path] = []
    for filename, content in files.items():
        path = output_dir / filename
        path.write_text(content, encoding="utf-8")
        written.append(path)
        if filename == "tunnel-fix.sh":
            path.chmod(path.stat().st_mode | stat.S_IXUSR)

    return TunnelFixPlanResult(output_dir=output_dir, files=tuple(written))


def _tunnel_fix_script(*, container_name: str) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Runs directly on the NAS (via DSM Task Scheduler or crontab) -- no SSH hop, no Python.
# Keeps the cloudflared tunnel container alive: sets restart: unless-stopped so it survives
# crashes/reboots on its own, and starts it if something left it stopped between runs.

CONTAINER_NAME="{container_name}"

DOCKER_BIN="$(command -v docker || true)"
if [[ -z "$DOCKER_BIN" ]]; then
  for candidate in /usr/local/bin/docker /usr/bin/docker; do
    if [[ -x "$candidate" ]]; then
      DOCKER_BIN="$candidate"
      break
    fi
  done
fi
if [[ -z "$DOCKER_BIN" ]]; then
  echo "docker binary not found" >&2
  exit 1
fi

target=""
status=""
fallback_name=""
fallback_status=""
while IFS=$'\\t' read -r name container_status; do
  if [[ -z "$fallback_name" ]]; then
    fallback_name="$name"
    fallback_status="$container_status"
  fi
  if [[ "$name" == "$CONTAINER_NAME" ]]; then
    target="$name"
    status="$container_status"
  fi
done < <("$DOCKER_BIN" ps -a --filter ancestor=cloudflare/cloudflared \\
  --format '{{{{.Names}}}}\\t{{{{.Status}}}}')

if [[ -z "$fallback_name" ]]; then
  echo "No cloudflared containers found" >&2
  exit 0
fi

if [[ -z "$target" ]]; then
  target="$fallback_name"
  status="$fallback_status"
  echo "No container named $CONTAINER_NAME; using $target instead" >&2
fi

"$DOCKER_BIN" update --restart unless-stopped "$target" > /dev/null

if [[ "$status" == Up* ]]; then
  echo "$target already running; restart policy confirmed unless-stopped"
else
  "$DOCKER_BIN" start "$target" > /dev/null
  echo "$target was stopped; started it and set restart policy to unless-stopped"
fi
"""


def _readme(*, container_name: str, interval_minutes: int) -> str:
    return f"""# Tunnel Fix Safety Net

This folder contains a generated safety-net script that keeps the Cloudflare Tunnel connector
(`{container_name}`) container running on the NAS. It complements `synology-site
tunnel-fix-autostart`, which you run by hand from your machine over SSH; this script runs
unattended, directly on the NAS, on a schedule.

Each run:

1. Finds the `cloudflare/cloudflared` container (by image, in case it isn't named
   `{container_name}`).
2. Sets its restart policy to `unless-stopped`, so Docker restarts it after a crash or NAS
   reboot without any further help.
3. Starts it if it's currently stopped.

It does not rename containers -- that's a one-time cleanup step, better done deliberately with
`synology-site tunnel-fix-autostart` while you're watching, not inside an unattended job.

## Schedule it (recommended: DSM Task Scheduler)

1. Copy `tunnel-fix.sh` to the NAS, e.g. `/volume1/docker/tunnel-fix/tunnel-fix.sh`.
2. Open DSM > Control Panel > Task Scheduler.
3. Create > Scheduled Task > User-defined script.
4. Set the schedule to run every {interval_minutes} minutes (Task Scheduler's UI offers hourly
   granularity on some DSM versions; if {interval_minutes} minutes isn't selectable, use the
   closest supported interval or fall back to the crontab option below).
5. Under Task Settings > Run command, use the "root" user and paste the command from
   `synology-task-command.txt`.
6. Save, then run it once manually to confirm it exits cleanly.

## Alternative: crontab

If you'd rather manage this over SSH than through the DSM GUI, see `crontab.example` for a
`crontab -e` entry (as root, since it needs the Docker socket) that runs every {interval_minutes}
minutes.

## Notes

- This script never touches Cloudflare's API or DNS -- it only manages the local Docker
  container, so it needs no credentials and can't cause a Cloudflare-side outage.
- Cloudflare's own edge reconnect/backoff logic inside `cloudflared` is automatic already; this
  script only covers the case where the container itself stopped.
"""


def _crontab(plan_dir: Path, *, interval_minutes: int) -> str:
    resolved = plan_dir.resolve()
    return (
        f"# Every {interval_minutes} minutes, as root (needs the Docker socket).\n"
        f"*/{interval_minutes} * * * * {resolved}/tunnel-fix.sh >> {resolved}/tunnel-fix.log 2>&1\n"
    )


def _synology_task_command(plan_dir: Path) -> str:
    return f"bash {plan_dir.resolve()}/tunnel-fix.sh\n"


def app(
    output_dir: Path = typer.Option(Path("tunnel-fix-plan"), "--output-dir"),  # noqa: B008
    container_name: str = typer.Option("cloudflared", "--container-name"),
    interval_minutes: int = typer.Option(15, "--interval-minutes"),
) -> None:
    try:
        result = generate_tunnel_fix_plan(
            output_dir=output_dir,
            container_name=container_name,
            interval_minutes=interval_minutes,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Tunnel Fix Plan")
    ok(f"Generated: {result.output_dir}")
    for path in result.files:
        ok(str(path))
    next_step(
        "Copy tunnel-fix.sh to the NAS and schedule it with DSM Task Scheduler or crontab "
        "-- see README.md."
    )
