from __future__ import annotations

import typer

from synology_site.cloudflare.api import CloudflareAPI
from synology_site.config import load_config
from synology_site.errors import SynologySiteError
from synology_site.output import console


def app(
    workspace: str | None = typer.Option(
        None, "--workspace", help="Force a specific workspace (see secrets/<name>/)"
    ),
) -> None:
    """Read-only: print every hostname currently configured in this workspace's Cloudflare
    Tunnel ingress list.

    The tunnel is commonly shared across several workspaces/zones (one Cloudflare account,
    several domains, one NAS) -- this prints the *whole* ingress list, not just entries for
    the current workspace's own zone, since that's the actual unit `cloudflare-route` reads
    and writes. Never modifies anything.
    """
    try:
        settings = load_config()
        account = settings.resolve_cloudflare("", workspace=workspace)
        ingress = CloudflareAPI(account).get_tunnel_ingress()
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc
    for entry in ingress:
        hostname = entry.get("hostname", "(catch-all)")
        service = entry.get("service", "")
        console.print(f"{hostname} -> {service}")
