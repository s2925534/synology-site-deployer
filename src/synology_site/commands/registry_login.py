from __future__ import annotations

import os
import shlex
from collections.abc import Callable
from dataclasses import dataclass, replace
from getpass import getpass

import typer

from synology_site.commands.check_nas import default_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.docker_remote import require_docker
from synology_site.errors import SynologySiteError
from synology_site.output import console, ok
from synology_site.ssh_client import SSHClient

SSHFactory = Callable[[Settings, str | None], SSHClient]


@dataclass(frozen=True)
class RegistryLoginResult:
    registry: str
    username: str


def registry_login(
    username: str,
    token: str,
    *,
    settings: Settings,
    registry: str = "ghcr.io",
    workspace: str | None = None,
    ssh_factory: SSHFactory = default_ssh_factory,
    prompted_password: str | None = None,
) -> RegistryLoginResult:
    """Logs the NAS's Docker daemon in to a container registry.

    The token is piped straight into `docker login --password-stdin` over
    the SSH channel's own stdin (chained after the sudo password when the
    NAS's docker needs sudo) -- it is never passed as a command-line
    argument (so it can't leak through `ps` on the NAS) and never written
    to a file on the NAS at all.
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
        docker = require_docker(ssh)
        result = ssh.run(
            f"{docker} login {shlex.quote(registry)} -u {shlex.quote(username)} --password-stdin",
            stdin=token,
        )
        if not result.ok:
            detail = result.stderr.strip() or result.stdout.strip()
            msg = f"docker login to {registry} failed: {detail}"
            raise SynologySiteError(msg)
    return RegistryLoginResult(registry=registry, username=username)


def app(
    username: str = typer.Option(
        ..., "--username", "-u", help="Registry username (e.g. a GitHub username or org)"
    ),
    registry: str = typer.Option("ghcr.io", "--registry", help="Container registry hostname"),
    workspace: str | None = typer.Option(
        None, "--workspace", help="NAS target to log in on (see secrets/<name>/)"
    ),
) -> None:
    """One-time Docker login on the NAS so it can pull private registry images.

    The token is read from the SYNOLOGY_SITE_REGISTRY_TOKEN environment
    variable if set, otherwise prompted for interactively -- it is never
    accepted as a CLI argument, so it can't end up in shell history.
    """
    try:
        settings = load_config()
        target = settings.resolve_target(workspace=workspace)
        prompted_password = None
        if not target.ssh_key_path and not target.ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        token = os.environ.get("SYNOLOGY_SITE_REGISTRY_TOKEN") or getpass(
            f"Token/password for {username}@{registry}: "
        )
        result = registry_login(
            username,
            token,
            settings=settings,
            registry=registry,
            workspace=workspace,
            prompted_password=prompted_password,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    ok(f"Logged in to {result.registry} as {result.username} on the NAS")
