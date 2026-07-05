from __future__ import annotations

from typing import Any

import requests
import typer

from synology_site.cloudflare.api import CloudflareRouteResult, configure_cloudflare_route
from synology_site.config import Settings, load_config
from synology_site.errors import SynologySiteError
from synology_site.output import console, ok
from synology_site.validators import apply_default_site_domain, validate_domain

# Standalone counterpart to the Cloudflare automation embedded in `create`/
# `deploy`: points one hostname at a fixed NAS port without allocating a
# port or touching the NAS over SSH at all. Needed for reverse-proxy setups
# (Traefik, Nginx Proxy Manager) where several hostnames all route to the
# same fixed proxy port (e.g. 80), rather than one port per app.


def configure_route(
    hostname: str,
    *,
    port: int,
    settings: Settings,
    service_host: str | None = None,
    session: Any = requests,
) -> CloudflareRouteResult:
    hostname = validate_domain(hostname)
    host = service_host or settings.local_base_url_host
    service_url = f"http://{host}:{port}"
    return configure_cloudflare_route(
        settings, hostname=hostname, service_url=service_url, session=session
    )


def app(
    hostname: str,
    port: int = typer.Option(
        ..., "--port", help="Fixed NAS port to route this hostname to, e.g. Traefik's 80"
    ),
    service_host: str | None = typer.Option(
        None, "--service-host", help="Override the service host (defaults to LOCAL_BASE_URL_HOST)"
    ),
) -> None:
    try:
        settings = load_config()
        hostname = apply_default_site_domain(hostname, settings.default_site_domain)
        result = configure_route(
            hostname, port=port, settings=settings, service_host=service_host
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc
    ok(f"Cloudflare route configured: {result.hostname} -> {result.service_url}")
