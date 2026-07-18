from __future__ import annotations

from getpass import getpass

import typer

from synology_site.commands.check_nas import smart_ssh_factory
from synology_site.config import load_config
from synology_site.docker_remote import container_logs, list_containers
from synology_site.errors import SynologySiteError
from synology_site.output import console


def ps_app(
    all_containers: bool = typer.Option(
        True,
        "--all/--running-only",
        help="Include stopped/exited containers too (default) or only running ones",
    ),
    workspace: str | None = typer.Option(
        None, "--workspace", help="Force a specific workspace's NAS target"
    ),
) -> None:
    """Read-only: list every container on the NAS (name, image, status). Never writes anything."""
    try:
        settings = load_config()
        target = settings.resolve_target(workspace=workspace)
        prompted_password = None
        if not target.ssh_key_path and not target.ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        with smart_ssh_factory(settings, prompted_password) as ssh:
            output = list_containers(ssh, all_containers=all_containers)
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc
    console.print(output.strip() or "(no containers)")


def logs_app(
    name: str,
    tail: int = typer.Option(100, "--tail", help="Number of trailing log lines to show"),
    workspace: str | None = typer.Option(
        None, "--workspace", help="Force a specific workspace's NAS target"
    ),
) -> None:
    """Read-only: print a container's recent logs. Never writes anything."""
    try:
        settings = load_config()
        target = settings.resolve_target(workspace=workspace)
        prompted_password = None
        if not target.ssh_key_path and not target.ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        with smart_ssh_factory(settings, prompted_password) as ssh:
            output = container_logs(ssh, name, tail=tail)
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc
    console.print(output.strip() or "(no logs)")
