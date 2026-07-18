from __future__ import annotations

import typer

from synology_site.config import load_config
from synology_site.errors import SynologySiteError
from synology_site.output import console
from synology_site.validators import apply_default_site_domain, validate_domain


def build_uptime_kuma_monitor_instructions(
    domain: str,
    *,
    kuma_url: str | None,
    interval_seconds: int,
    retries: int,
) -> str:
    kuma_line = kuma_url or "http://<NAS host>:<Uptime Kuma port -- see `synology-site list`>"
    return (
        "Uptime Kuma monitor setup\n\n"
        "If Uptime Kuma isn't deployed yet:\n\n"
        "synology-site bootstrap-uptime-kuma\n\n"
        f"1. Open Uptime Kuma: {kuma_line}\n"
        "2. Add New Monitor.\n"
        "3. Monitor Type: HTTP(s).\n"
        f"4. Friendly Name: {domain} (via Cloudflare Tunnel)\n"
        f"5. URL: https://{domain}\n"
        f"6. Heartbeat Interval: {interval_seconds} seconds\n"
        f"7. Retries: {retries}\n"
        "8. Save.\n\n"
        "This HTTPS check is the best single signal for tunnel health: it only turns green when "
        "DNS, Cloudflare's edge, the tunnel connector, and the origin container are all working "
        "-- the same path tunnel-fix-plan can't see from inside the NAS.\n\n"
        "Optional second monitor -- direct cloudflared container status:\n\n"
        "1. Add New Monitor.\n"
        "2. Monitor Type: Docker Container.\n"
        "3. Container Name: cloudflared\n"
        "4. Docker Host: add one pointing at unix:///var/run/docker.sock\n\n"
        "This needs the Docker socket mounted into the Uptime Kuma container "
        "(`/var/run/docker.sock:/var/run/docker.sock:ro` in its compose file), which gives "
        "Uptime Kuma root-equivalent access to the NAS's Docker daemon -- it's a real tradeoff, "
        "so it's opt-in and not done automatically. Skip it if the HTTPS monitor above is "
        "enough.\n\n"
        "Either way, set a notification channel (Settings > Notifications in Uptime Kuma) so a "
        "failing check pages you instead of sitting silent in the dashboard.\n"
    )


def app(
    domain: str = typer.Argument(
        ..., help="Hostname reachable through the Cloudflare Tunnel to monitor"
    ),
    kuma_port: int | None = typer.Option(
        None,
        "--kuma-port",
        help="Local port Uptime Kuma is published on, if known (see `synology-site list`)",
    ),
    interval_seconds: int = typer.Option(60, "--interval-seconds"),
    retries: int = typer.Option(3, "--retries"),
) -> None:
    try:
        settings = load_config()
        domain = apply_default_site_domain(domain, settings.default_site_domain)
        domain = validate_domain(domain)
        if interval_seconds < 1:
            raise SynologySiteError("--interval-seconds must be at least 1")
        if retries < 0:
            raise SynologySiteError("--retries must not be negative")
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    kuma_url = (
        f"http://{settings.local_base_url_host}:{kuma_port}" if kuma_port is not None else None
    )
    instructions = build_uptime_kuma_monitor_instructions(
        domain,
        kuma_url=kuma_url,
        interval_seconds=interval_seconds,
        retries=retries,
    )
    console.print(instructions)
