from __future__ import annotations

import shlex
from getpass import getpass

import typer
from rich.prompt import Confirm

from synology_site.commands.check_nas import SSHFactory, smart_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.docker_remote import detect_compose_command
from synology_site.errors import SynologySiteError
from synology_site.naming import domain_to_slug
from synology_site.output import console, ok, warn


def remove_site(
    domain: str,
    *,
    settings: Settings,
    delete_files: bool = False,
    delete_volumes: bool = False,
    remove_orphans: bool = False,
    ssh_factory: SSHFactory = smart_ssh_factory,
    prompted_password: str | None = None,
) -> None:
    """`docker compose down` for a site's project, optionally deleting its files/volumes too.

    `remove_orphans` passes `--remove-orphans` through to `down` -- needed when a container
    still exists under a service name the current Compose file no longer defines (e.g. after
    replacing a placeholder's single `web` service with a real multi-service file); `down`
    otherwise leaves such containers running, since Compose treats them as out of scope rather
    than something to clean up by default.
    """
    slug = domain_to_slug(domain)
    project_path = f"{settings.nas_docker_root.rstrip('/')}/{slug}"
    with ssh_factory(settings, prompted_password) as ssh:
        compose = detect_compose_command(ssh)
        flags = ""
        if delete_volumes:
            flags += " -v"
        if remove_orphans:
            flags += " --remove-orphans"
        ssh.run(f"cd {shlex.quote(project_path)} && {compose} down{flags}", check=True)
        if delete_files:
            ssh.run(f"rm -rf {shlex.quote(project_path)}", check=True)


def app(
    domain: str,
    force: bool = typer.Option(False, "--force"),
    delete_files: bool = typer.Option(False, "--delete-files"),
    delete_volumes: bool = typer.Option(False, "--delete-volumes"),
    remove_orphans: bool = typer.Option(
        False,
        "--remove-orphans",
        help="Also remove containers whose service name isn't in the current Compose file "
        "anymore -- e.g. a leftover container from a placeholder's single `web` service after "
        "the project's real, multi-service Compose file replaced it. Without this, `down` "
        "leaves such containers running.",
    ),
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
        remove_site(
            domain,
            settings=settings,
            delete_files=delete_files,
            delete_volumes=delete_volumes,
            remove_orphans=remove_orphans,
            prompted_password=prompted_password,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc
    ok(f"Removed Compose project for {domain}")
