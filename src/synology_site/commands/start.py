from __future__ import annotations

import typer


def app(domain: str) -> None:
    typer.echo(f"Start {domain}")
