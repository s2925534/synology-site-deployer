from __future__ import annotations

import typer


def app(
    domain: str,
    force: bool = typer.Option(False, "--force"),
    delete_files: bool = typer.Option(False, "--delete-files"),
    delete_volumes: bool = typer.Option(False, "--delete-volumes"),
) -> None:
    del force, delete_files, delete_volumes
    typer.echo(f"Remove {domain}")
