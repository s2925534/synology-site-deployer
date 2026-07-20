from __future__ import annotations

import shlex
from getpass import getpass

import typer

from synology_site.commands.check_nas import SSHFactory, smart_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.docker_remote import detect_compose_command
from synology_site.errors import SynologySiteError
from synology_site.naming import domain_to_slug
from synology_site.output import console, ok


def stop_site(
    domain: str,
    *,
    settings: Settings,
    remove_orphans: bool = False,
    ssh_factory: SSHFactory = smart_ssh_factory,
    prompted_password: str | None = None,
) -> None:
    slug = domain_to_slug(domain)
    project_path = f"{settings.nas_docker_root.rstrip('/')}/{slug}"
    with ssh_factory(settings, prompted_password) as ssh:
        compose = detect_compose_command(ssh)
        flags = " --remove-orphans" if remove_orphans else ""
        ssh.run(f"cd {shlex.quote(project_path)} && {compose} down{flags}", check=True)


def app(
    domain: str,
    remove_orphans: bool = typer.Option(
        False,
        "--remove-orphans",
        help="Also remove containers whose service name isn't in the current Compose file "
        "anymore. See `remove --help` for when this matters.",
    ),
) -> None:
    try:
        settings = load_config()
        prompted_password = None
        if not settings.nas_ssh_key_path and not settings.nas_ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        stop_site(
            domain,
            settings=settings,
            remove_orphans=remove_orphans,
            prompted_password=prompted_password,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc
    ok(f"Stopped {domain}")
