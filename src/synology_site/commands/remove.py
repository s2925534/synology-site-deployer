from __future__ import annotations

import shlex
from getpass import getpass

import typer
from rich.prompt import Confirm

from synology_site.commands.check_nas import smart_ssh_factory
from synology_site.config import load_config
from synology_site.docker_remote import detect_compose_command
from synology_site.errors import SynologySiteError
from synology_site.naming import domain_to_slug
from synology_site.output import console, ok, warn


def app(
    domain: str,
    force: bool = typer.Option(False, "--force"),
    delete_files: bool = typer.Option(False, "--delete-files"),
    delete_volumes: bool = typer.Option(False, "--delete-volumes"),
) -> None:
    if delete_volumes:
        warn("Database volumes will be deleted if this Compose project owns them.")
    if not force and not Confirm.ask(f"Remove Compose project for {domain}?", default=False):
        raise typer.Exit(0)
    try:
        settings = load_config()
        prompted_password = None
        if not settings.nas_ssh_key_path and not settings.nas_ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        slug = domain_to_slug(domain)
        project_path = f"{settings.nas_docker_root.rstrip('/')}/{slug}"
        with smart_ssh_factory(settings, prompted_password) as ssh:
            compose = detect_compose_command(ssh)
            volume_flag = " -v" if delete_volumes else ""
            ssh.run(f"cd {shlex.quote(project_path)} && {compose} down{volume_flag}", check=True)
            if delete_files:
                ssh.run(f"rm -rf {shlex.quote(project_path)}", check=True)
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc
    ok(f"Removed Compose project for {domain}")
