from __future__ import annotations

import typer


def cloudflare_instructions(domain: str, port: int = typer.Option(..., "--port")) -> None:
    typer.echo(f"Cloudflare instructions for {domain} on port {port}")


def tunnel_fix_autostart() -> None:
    typer.echo("Tunnel autostart")


def set_autostart(domain: str) -> None:
    typer.echo(f"Set autostart for {domain}")
