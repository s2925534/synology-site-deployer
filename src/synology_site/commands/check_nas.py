from __future__ import annotations

import socket
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
LanProbe = Callable[[str, int], bool]


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


def local_ssh_factory(settings: Settings, prompted_password: str | None = None) -> SSHClient:
    """Always connects to the plain NAS_HOST/NAS_PORT, ignoring any configured Tailscale/
    Cloudflare Access remote transport -- used when check-nas has determined the NAS is
    reachable directly on the LAN, so there's no reason to route through a remote proxy."""
    password = settings.nas_ssh_password or prompted_password
    return SSHClient(
        settings.nas_host,
        settings.nas_port,
        settings.nas_user,
        key_path=settings.nas_ssh_key_path,
        password=password,
    )


def probe_lan_reachable(host: str, port: int, *, timeout: float = 1.5) -> bool:
    """Cheap reachability check: can we open a raw TCP connection to host:port right now?

    No authentication attempted -- this only answers "is something listening here," which is
    enough to tell LAN from off-LAN without needing SSH credentials first.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def smart_ssh_factory(
    settings: Settings,
    prompted_password: str | None = None,
    *,
    lan_probe: LanProbe = probe_lan_reachable,
) -> SSHClient:
    """Auto-detects LAN vs remote before connecting, then delegates to the matching factory.

    This is the same "try the LAN first, only use Tailscale/Cloudflare Access if that
    fails" decision `check-nas` already makes for itself (see `resolve_remote_mode`) --
    but usable as a drop-in default `ssh_factory` for any command, not just check-nas's
    own explicit --remote handling. Without this, a command whose default `ssh_factory`
    is `default_ssh_factory` always goes through the configured remote transport whenever
    one is configured (e.g. TAILSCALE_ENABLED=true), even from right there on the LAN.

    Requires `settings.nas_host` to be the target's actual raw LAN host, not an
    already-resolved Tailscale/Cloudflare Access address -- see Settings.resolved_for().
    """
    if lan_probe(settings.nas_host, settings.nas_port):
        return local_ssh_factory(settings, prompted_password)
    return default_ssh_factory(settings, prompted_password)


def remote_transport_label(settings: Settings) -> str:
    if settings.ssh_access_hostname:
        return f"Cloudflare Access ({settings.ssh_access_hostname})"
    if settings.tailscale_enabled and settings.tailscale_host:
        return f"Tailscale ({settings.tailscale_host})"
    return "no remote transport configured -- falling back to NAS_HOST directly"


def resolve_remote_mode(
    settings: Settings,
    *,
    force_remote: bool = False,
    lan_probe: LanProbe = probe_lan_reachable,
) -> bool:
    """Decide whether check-nas should go through the remote path.

    --remote forces it (useful to test Tailscale/Cloudflare Access without leaving the LAN).
    Otherwise this auto-detects: a quick TCP probe against NAS_HOST:NAS_PORT decides whether
    we're actually on the NAS's LAN right now, so the remote path only kicks in when it's
    actually needed -- no flag required when working from an office network, for instance.
    """
    if force_remote:
        return True
    return not lan_probe(settings.nas_host, settings.nas_port)


def run_check_nas(
    settings: Settings,
    *,
    ssh_factory: SSHFactory = default_ssh_factory,
    prompted_password: str | None = None,
    remote_mode: bool = False,
) -> list[CheckResult]:
    if not remote_mode:
        connection_detail = f"Connected to {settings.nas_host}:{settings.nas_port} (local LAN)"
    elif settings.ssh_access_hostname:
        connection_detail = f"Connected via cloudflared proxy to {settings.ssh_access_hostname}"
    else:
        connection_detail = (
            f"Connected to {settings.nas_connection_host}:{settings.nas_port} (remote)"
        )
    results = [
        CheckResult("Configuration", True, ".env loaded"),
        CheckResult(
            "Network",
            True,
            f"remote via {remote_transport_label(settings)}" if remote_mode else "local LAN",
        ),
    ]
    with ssh_factory(settings, prompted_password) as ssh:
        results.append(CheckResult("SSH", True, connection_detail))

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


def app(
    remote: bool = typer.Option(
        False,
        "--remote",
        help="Force checking via the configured remote path (Tailscale/Cloudflare Access) "
        "even if the NAS is reachable on the LAN -- useful to verify remote access without "
        "leaving the LAN. Without this flag, the remote path is used automatically whenever "
        "the NAS isn't reachable directly, no flag needed.",
    ),
) -> None:
    try:
        settings = load_config()
        prompted_password = None
        if not settings.nas_ssh_key_path and not settings.nas_ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        remote_mode = resolve_remote_mode(settings, force_remote=remote)
        ssh_factory = default_ssh_factory if remote_mode else local_ssh_factory
        results = run_check_nas(
            settings,
            ssh_factory=ssh_factory,
            prompted_password=prompted_password,
            remote_mode=remote_mode,
        )
    except SynologySiteError as exc:
        error(str(exc))
        raise typer.Exit(1) from exc

    console.rule("Synology")
    for result in results:
        ok(f"{result.name}: {result.detail}")
