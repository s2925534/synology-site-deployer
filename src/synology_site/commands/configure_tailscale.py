from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import typer
from dotenv import dotenv_values

from synology_site.errors import SynologySiteError
from synology_site.output import console, next_step, ok
from synology_site.tailscale import fetch_access_token, list_devices, select_nas_device

# Automates the manual "copy the NAS's 100.x.y.z address from the Tailscale admin console and
# paste it into .env" step from docs/remote-nas-access.md, using a Tailscale OAuth client
# (TAILSCALE_CLIENT_ID/TAILSCALE_CLIENT_SECRET) instead. Only touches TAILSCALE_ENABLED and
# TAILSCALE_NAS_HOST -- everything else in the env file is left exactly as it was.


@dataclass(frozen=True)
class ConfigureTailscaleResult:
    device_hostname: str
    tailscale_host: str
    env_path: str
    updated: bool


def _update_env_file(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0]
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            new_lines.append(line)
    for key, value in updates.items():
        if key not in seen:
            new_lines.append(f"{key}={value}")
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def configure_tailscale(
    *,
    env_path: Path = Path(".env"),
    device_name: str | None = None,
    dry_run: bool = False,
    session: Any = requests,
) -> ConfigureTailscaleResult:
    if not env_path.is_file():
        msg = f"No .env file found at {env_path}"
        raise SynologySiteError(msg)

    values = dotenv_values(env_path)
    client_id = (values.get("TAILSCALE_CLIENT_ID") or "").strip()
    client_secret = (values.get("TAILSCALE_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        msg = (
            "TAILSCALE_CLIENT_ID and TAILSCALE_CLIENT_SECRET must be set in "
            f"{env_path} first -- create an OAuth client with 'Devices: Read' scope in the "
            "Tailscale admin console (Settings -> OAuth clients)."
        )
        raise SynologySiteError(msg)

    token = fetch_access_token(client_id, client_secret, session=session)
    devices = list_devices(token, session=session)
    current_host = (values.get("TAILSCALE_NAS_HOST") or "").strip() or None
    device = select_nas_device(
        devices, device_name=device_name, current_tailscale_host=current_host
    )

    tailscale_ip = device.tailscale_ipv4
    if not tailscale_ip:
        msg = f"Tailscale device {device.hostname!r} has no 100.x.x.x address"
        raise SynologySiteError(msg)

    if not dry_run:
        _update_env_file(
            env_path, {"TAILSCALE_ENABLED": "true", "TAILSCALE_NAS_HOST": tailscale_ip}
        )

    return ConfigureTailscaleResult(
        device_hostname=device.hostname or device.name,
        tailscale_host=tailscale_ip,
        env_path=str(env_path),
        updated=not dry_run,
    )


def app(
    device_name: str | None = typer.Option(
        None,
        "--device-name",
        help="Tailscale device hostname to match (case-insensitive substring) when the "
        "tailnet has more than one device and none can be identified automatically.",
    ),
    env_file: Path = typer.Option(Path(".env"), "--env-file"),  # noqa: B008
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Look up the device but don't write to the env file"
    ),
) -> None:
    try:
        result = configure_tailscale(env_path=env_file, device_name=device_name, dry_run=dry_run)
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Result")
    ok(f"Tailscale device: {result.device_hostname}")
    ok(f"Tailscale address: {result.tailscale_host}")
    if result.updated:
        ok(
            f"Updated {result.env_path}: TAILSCALE_ENABLED=true, "
            f"TAILSCALE_NAS_HOST={result.tailscale_host}"
        )
        next_step("Run `synology-site check-nas --remote` to verify SSH over Tailscale works.")
    else:
        next_step("Dry run -- no changes written. Re-run without --dry-run to apply.")
