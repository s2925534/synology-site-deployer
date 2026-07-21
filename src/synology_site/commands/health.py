from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests
import typer

from synology_site.commands.list_sites import list_markers_for_target
from synology_site.config import Settings, load_config
from synology_site.errors import SynologySiteError
from synology_site.nas.target import NasTarget
from synology_site.output import console, ok, warn
from synology_site.ssh_client import SSHClient

SSHFactory = Callable[[Settings, str | None], SSHClient]
HealthGetter = Callable[..., Any]


@dataclass(frozen=True)
class SiteHealth:
    target_name: str
    domain: str
    url: str | None
    ok: bool
    status: int | None = None
    error: str | None = None


PasswordPrompt = Callable[[NasTarget], "str | None"]


def check_health_for_targets(
    settings: Settings,
    targets: tuple[NasTarget, ...],
    *,
    path: str = "/health",
    ssh_factory: SSHFactory,
    health_get: HealthGetter = requests.get,
    password_prompt: PasswordPrompt = lambda _target: None,
    proxy_port: int | None = None,
) -> list[SiteHealth]:
    """`proxy_port`, when given, is a fallback for markers with no port of their own -- sites
    routed through a shared reverse proxy (e.g. Traefik) rather than published on their own host
    port. Instead of reporting "no port in marker" outright, this probes the proxy port with a
    `Host:` header matching the site's domain, the same way an external request would actually
    reach it. Without `proxy_port`, behavior is unchanged."""
    results: list[SiteHealth] = []
    for target in targets:
        target_password = None
        if not target.ssh_key_path and not target.ssh_password:
            target_password = password_prompt(target)
        try:
            markers = list_markers_for_target(
                settings,
                target,
                ssh_factory=ssh_factory,
                prompted_password=target_password,
            )
        except SynologySiteError as exc:
            results.append(
                SiteHealth(
                    target_name=target.name,
                    domain="*",
                    url=None,
                    ok=False,
                    error=f"target unreachable: {exc}",
                )
            )
            continue

        for marker in markers:
            domain = str(marker.get("domain") or marker.get("slug") or "unknown")
            port = marker.get("port")
            headers: dict[str, str] | None = None
            if not port:
                if proxy_port is None:
                    results.append(
                        SiteHealth(
                            target_name=target.name,
                            domain=domain,
                            url=None,
                            ok=False,
                            error="no port in marker",
                        )
                    )
                    continue
                port = proxy_port
                headers = {"Host": domain}
            url = f"http://{target.health_check_host}:{port}{path}"
            try:
                response = (
                    health_get(url, timeout=10, headers=headers)
                    if headers is not None
                    else health_get(url, timeout=10)
                )
            except requests.RequestException as exc:
                results.append(
                    SiteHealth(
                        target_name=target.name,
                        domain=domain,
                        url=url,
                        ok=False,
                        error=str(exc),
                    )
                )
                continue
            results.append(
                SiteHealth(
                    target_name=target.name,
                    domain=domain,
                    url=url,
                    ok=response.status_code == 200,
                    status=response.status_code,
                )
            )
    return results


def app(
    all_targets: bool = typer.Option(
        False, "--all-targets", help="Check health across every configured NAS target"
    ),
    workspace: str | None = typer.Option(
        None, "--workspace", help="Check health on a specific NAS target only"
    ),
    path: str = typer.Option("/health", "--path", help="Health path to request"),
    proxy_port: int | None = typer.Option(
        None,
        "--proxy-port",
        help="Check markers with no port of their own via this shared reverse-proxy port "
        "instead, using a Host header matching the site's domain (e.g. Traefik on 8080)",
    ),
) -> None:
    from getpass import getpass

    from synology_site.commands.check_nas import smart_ssh_factory

    try:
        settings = load_config()
        targets = (
            (settings.default_nas_target, *settings.nas_targets)
            if all_targets
            else (settings.resolve_target(workspace=workspace),)
        )
        results = check_health_for_targets(
            settings,
            targets,
            path=path,
            ssh_factory=smart_ssh_factory,
            password_prompt=lambda target: getpass(f"NAS SSH password ({target.name}): "),
            proxy_port=proxy_port,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Health")
    if not results:
        warn("No sites found")
        return
    show_target_prefix = len({result.target_name for result in results}) > 1
    for result in results:
        prefix = f"[{result.target_name}] " if show_target_prefix else ""
        if result.ok:
            ok(f"{prefix}{result.domain} {result.status} {result.url}")
        else:
            detail = f"HTTP {result.status}" if result.status is not None else result.error
            warn(f"{prefix}{result.domain} {detail}")
