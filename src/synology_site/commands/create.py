from __future__ import annotations

import typer


def app(
    domain: str,
    framework: str = typer.Option("flask", "--framework"),
    port: int | None = typer.Option(None, "--port"),
    with_db: bool = typer.Option(False, "--with-db"),
    db_mode: str = typer.Option("none", "--db-mode"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    force: bool = typer.Option(False, "--force"),
    strict_cloudflare: bool = typer.Option(False, "--strict-cloudflare"),
) -> None:
    del port, with_db, db_mode, dry_run, force, strict_cloudflare
    typer.echo(f"Create {framework} site for {domain}")
