from __future__ import annotations

import shlex
from collections.abc import Callable
from getpass import getpass

import typer

from synology_site.commands.check_nas import smart_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.docker_remote import detect_compose_command, docker_command
from synology_site.errors import SynologySiteError
from synology_site.output import console, ok
from synology_site.ssh_client import SSHClient

SSHFactory = Callable[[Settings, str | None], SSHClient]

SUPABASE_WORKING_DIR = "supabase"
RESILINKED_API_CONTAINER = "resilinked-api"


def run_start_resilinked_api(
    settings: Settings,
    *,
    ssh_factory: SSHFactory = smart_ssh_factory,
    prompted_password: str | None = None,
) -> None:
    """resilinked-api depends on supabase-db (Prisma connects to `supabase-db:5433`), and its
    container name collides with a stale duplicate compose project -- `compose up -d` in its own
    directory refuses to adopt the existing stopped container and errors instead. So: bring up
    just the `db` service (not the whole Supabase stack), then `docker start` the existing
    resilinked-api container directly rather than recreating it via compose.
    """
    with ssh_factory(settings, prompted_password) as ssh:
        compose = detect_compose_command(ssh)
        docker = docker_command(ssh)
        working_dir = f"{settings.nas_docker_root.rstrip('/')}/{SUPABASE_WORKING_DIR}"
        quoted_dir = shlex.quote(working_dir)
        ssh.run(f"cd {quoted_dir} && {compose} up -d db", check=True)
        ssh.run(f"{docker} start {shlex.quote(RESILINKED_API_CONTAINER)}", check=True)


def app() -> None:
    try:
        settings = load_config()
        prompted_password = None
        if not settings.nas_ssh_key_path and not settings.nas_ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        run_start_resilinked_api(settings, prompted_password=prompted_password)
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc
    ok("Started supabase-db and resilinked-api")
