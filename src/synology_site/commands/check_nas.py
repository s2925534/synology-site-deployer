from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass

import typer

from synology_site.config import Settings, load_config
from synology_site.docker_remote import (
    detect_compose_command,
    ensure_remote_directory,
    list_containers,
    list_published_ports,
    require_docker,
)
from synology_site.errors import SynologySiteError
from synology_site.output import console, error, ok
from synology_site.ssh_client import CloudflareAccessSSHClient, SSHClient


@dataclass(frozen=True)
class CheckResult:
    name: str
    success: bool
    detail: str


SSHFactory = Callable[[Settings, str | None], SSHClient]


def default_ssh_factory(settings: Settings, prompted_password: str | None = None) -> SSHClient:
    password = settings.nas_ssh_password or prompted_password
    if settings.ssh_access_hostname:
        return CloudflareAccessSSHClient(
            settings.ssh_access_hostname,
            settings.ssh_access_local_port,
            settings.nas_user,
            key_path=settings.nas_ssh_key_path,
            password=password,
        )
    return SSHClient(
        settings.nas_connection_host,
        settings.nas_port,
        settings.nas_user,
        key_path=settings.nas_ssh_key_path,
        password=password,
    )


def run_check_nas(
    settings: Settings,
    *,
    ssh_factory: SSHFactory = default_ssh_factory,
    prompted_password: str | None = None,
) -> list[CheckResult]:
    results = [
        CheckResult("Configuration", True, ".env loaded"),
    ]
    with ssh_factory(settings, prompted_password) as ssh:
        results.append(
            CheckResult(
                "SSH", True, f"Connected to {settings.nas_connection_host}:{settings.nas_port}"
            )
        )

        require_docker(ssh)
        results.append(CheckResult("Docker", True, "docker command found"))

        compose = detect_compose_command(ssh)
        results.append(CheckResult("Docker Compose", True, f"{compose} available"))

        ensure_remote_directory(ssh, settings.nas_docker_root)
        results.append(CheckResult("Docker root", True, settings.nas_docker_root))

        containers = list_containers(ssh)
        detail = "containers can be listed"
        if containers.strip():
            detail = f"{len(containers.strip().splitlines())} running container(s) visible"
        results.append(CheckResult("Containers", True, detail))

        list_published_ports(ssh)
        results.append(CheckResult("Ports", True, "published ports can be inspected"))
    return results


def app() -> None:
    try:
        settings = load_config()
        prompted_password = None
        if not settings.nas_ssh_key_path and not settings.nas_ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        results = run_check_nas(settings, prompted_password=prompted_password)
    except SynologySiteError as exc:
        error(str(exc))
        raise typer.Exit(1) from exc

    console.rule("Synology")
    for result in results:
        ok(f"{result.name}: {result.detail}")
