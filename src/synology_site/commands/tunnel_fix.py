from __future__ import annotations

import typer

from synology_site.cloudflare.manual_instructions import build_manual_instructions
from synology_site.config import load_config
from synology_site.errors import SynologySiteError
from synology_site.output import console


def cloudflare_instructions(domain: str, port: int = typer.Option(..., "--port")) -> None:
    try:
        settings = load_config()
        instructions = build_manual_instructions(
            domain,
            settings.cf_zone_domain,
            settings.local_base_url_host,
            port,
            settings.cf_tunnel_name,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc
    console.print(instructions)


def tunnel_fix_autostart() -> None:
    typer.echo("Tunnel autostart")


def set_autostart(domain: str) -> None:
    typer.echo(f"Set autostart for {domain}")
