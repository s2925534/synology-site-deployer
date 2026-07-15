from __future__ import annotations

import shlex
from dataclasses import replace
from getpass import getpass

import typer

from synology_site.commands.check_nas import SSHFactory, default_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.docker_remote import docker_command
from synology_site.errors import SynologySiteError
from synology_site.output import console, ok


def ensure_network(
    name: str,
    *,
    settings: Settings,
    workspace: str | None = None,
    ssh_factory: SSHFactory = default_ssh_factory,
    prompted_password: str | None = None,
) -> bool:
    """Creates a Docker network on the NAS if it doesn't already exist.

    Idempotent -- safe to call whether or not the network is already
    there. Exists because `docker compose up` refuses to start a project
    whose Compose file declares a network as `external: true` (the
    convention used for shared networks like `shared-services`/
    `supabase_default`) when that network hasn't actually been created on
    the NAS yet -- previously a manual one-time step documented
    per-project (e.g. au-address-lookup's own README), now a single
    sanctioned command any project can run instead of a hand-rolled
    `docker network create` over SSH.

    Returns True if the network was newly created, False if it already existed.
    """
    target = settings.resolve_target(workspace=workspace)
    connection_settings = replace(
        settings,
        nas_host=target.connection_host,
        nas_port=target.port,
        nas_user=target.user,
        nas_ssh_key_path=target.ssh_key_path,
        nas_ssh_password=target.ssh_password,
        ssh_access_hostname=target.ssh_access_hostname,
        ssh_access_local_port=target.ssh_access_local_port,
    )
    with ssh_factory(connection_settings, prompted_password) as ssh:
        docker = docker_command(ssh)
        existing = ssh.run(f"{docker} network inspect {shlex.quote(name)}")
        if existing.ok:
            return False
        ssh.run(f"{docker} network create {shlex.quote(name)}", check=True)
        return True


def app(
    name: str,
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        help="Force a specific workspace's NAS target (see secrets/<name>/)",
    ),
) -> None:
    try:
        settings = load_config()
        target = settings.resolve_target(workspace=workspace)
        prompted_password = None
        if not target.ssh_key_path and not target.ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        created = ensure_network(
            name,
            settings=settings,
            workspace=workspace,
            prompted_password=prompted_password,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc
    ok(f"Created network: {name}" if created else f"Network already exists: {name}")
