from __future__ import annotations

import json
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path
from typing import Any

import requests
import typer

from synology_site.commands.check_nas import smart_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.docker_remote import detect_compose_command, docker_command, require_docker
from synology_site.errors import SynologySiteError
from synology_site.naming import domain_to_slug
from synology_site.notifications import send_webhook_notification
from synology_site.output import console, ok, warn
from synology_site.ssh_client import SSHClient
from synology_site.validators import apply_default_site_domain, validate_domain


@dataclass(frozen=True)
class UpdateResult:
    domain: str
    slug: str
    project_path: str
    compose_file: str
    pulled: bool
    built: bool
    container_name: str | None
    health_url: str | None
    compose_uploaded: bool = False


SSHFactory = Callable[[Settings, str | None], SSHClient]
HealthGetter = Callable[..., Any]


def update_site(
    domain: str,
    *,
    settings: Settings,
    compose_file: Path | None = None,
    pull: bool = True,
    build: bool = False,
    health_path: str | None = None,
    container_name: str | None = None,
    dry_run: bool = False,
    workspace: str | None = None,
    ssh_factory: SSHFactory = smart_ssh_factory,
    health_get: HealthGetter = requests.get,
    prompted_password: str | None = None,
) -> UpdateResult:
    # `compose_file`, if given, is a *local* file re-uploaded to the same
    # remote path already recorded for this site (from `.synology-site.json`)
    # before pull/up -d run -- letting a compose-only change (e.g. a new
    # label) reach an already-running, port-bound site without going through
    # `deploy`'s create-style flow (which re-checks port availability and
    # rejects the site's own already-held port as a collision).
    if compose_file is not None and not compose_file.is_file():
        msg = f"Compose file not found: {compose_file}"
        raise SynologySiteError(msg)
    domain = validate_domain(domain)
    target = settings.resolve_target(workspace=workspace)
    connection_settings = settings.resolved_for(target)
    slug = domain_to_slug(domain)
    project_path = f"{target.docker_root.rstrip('/')}/{slug}"
    marker: dict[str, Any] = {}

    with ssh_factory(connection_settings, prompted_password) as ssh:
        require_docker(ssh)
        compose = detect_compose_command(ssh)
        quoted_project = shlex.quote(project_path)
        exists = ssh.run(f"test -d {quoted_project}")
        if not exists.ok:
            msg = f"Remote project folder not found: {project_path}"
            raise SynologySiteError(msg)

        marker_result = ssh.run(f"cat {quoted_project}/.synology-site.json")
        if marker_result.ok:
            marker = json.loads(marker_result.stdout)
        remote_compose_file = str(marker.get("compose_file") or "docker-compose.yml")
        resolved_container_name = container_name or marker.get("container")
        port = marker.get("port")
        resolved_health_path = health_path
        if resolved_health_path is None and marker.get("mode") != "deploy" and port:
            resolved_health_path = "/health"
        health_url = (
            f"http://{target.health_check_host}:{port}{resolved_health_path}"
            if port and resolved_health_path
            else None
        )

        if dry_run:
            return UpdateResult(
                domain=domain,
                slug=slug,
                project_path=project_path,
                compose_file=remote_compose_file,
                pulled=False,
                built=build,
                container_name=resolved_container_name,
                health_url=health_url,
                compose_uploaded=False,
            )

        compose_uploaded = False
        if compose_file is not None:
            # Overwrite the exact remote path this site already runs from --
            # same file, new content. Doesn't touch the marker (port/container
            # name/mode are unchanged), so no `deploy`-style port re-check.
            ssh.upload_text(
                f"{project_path}/{remote_compose_file}",
                compose_file.read_text(encoding="utf-8"),
            )
            compose_uploaded = True

        pulled = False
        quoted_file = shlex.quote(remote_compose_file)
        base = f"cd {quoted_project} && {compose} -f {quoted_file}"
        if pull and not build:
            pull_result = ssh.run(f"{base} pull")
            if pull_result.ok:
                pulled = True
            else:
                warn("docker compose pull failed; falling back to a local build")
                build = True
        up_flags = " up -d --build" if build else " up -d"
        result = ssh.run(f"{base}{up_flags}")
        if not result.ok and compose == "docker compose":
            result = ssh.run(f"cd {quoted_project} && docker-compose -f {quoted_file}{up_flags}")
        if not result.ok:
            raise SynologySiteError("Docker Compose failed to update the project")

        if resolved_container_name:
            _confirm_container(ssh, resolved_container_name, docker_command(ssh))
        if health_url:
            _confirm_health(health_get, health_url)

    return UpdateResult(
        domain=domain,
        slug=slug,
        project_path=project_path,
        compose_file=remote_compose_file,
        pulled=pulled,
        built=build,
        container_name=resolved_container_name,
        health_url=health_url,
        compose_uploaded=compose_uploaded,
    )


def _confirm_container(ssh: SSHClient, name: str, docker: str) -> None:
    result = ssh.run(f"{docker} inspect -f '{{{{.State.Running}}}}' {shlex.quote(name)}")
    if not result.ok or result.stdout.strip().lower() != "true":
        msg = f"Container is not running: {name}"
        raise SynologySiteError(msg)


def _confirm_health(health_get: HealthGetter, url: str) -> None:
    last_error: Exception | None = None
    last_status: int | None = None
    for attempt in range(1, 16):
        try:
            response = health_get(url, timeout=10)
            last_status = response.status_code
            if response.status_code == 200:
                return
        except requests.RequestException as exc:
            last_error = exc
        if attempt < 15:
            time.sleep(2)
    if last_status is not None:
        msg = f"Health check returned HTTP {last_status}: {url}"
        raise SynologySiteError(msg)
    msg = f"Health check failed: {url}"
    raise SynologySiteError(msg) from last_error


def app(
    domain: str,
    compose_file: Path | None = typer.Option(  # noqa: B008
        None,
        "--compose-file",
        exists=True,
        dir_okay=False,
        help="Local compose file to upload before pulling/restarting, overwriting the file at "
        "this site's already-recorded remote path (from .synology-site.json). Use this to apply "
        "a compose-only change (e.g. a new label) to a site that's already deployed and holding "
        "its port -- `deploy --force` can't do this in place, since it re-checks port "
        "availability and treats the site's own already-held port as a collision. Omit to just "
        "pull/restart with the compose file already on the NAS (existing behavior).",
    ),
    pull: bool = typer.Option(True, "--pull/--no-pull"),
    build: bool = typer.Option(False, "--build/--no-build"),
    health_path: str | None = typer.Option(
        None,
        "--health-path",
        help="Health path to check after update. create sites default to /health.",
    ),
    container_name: str | None = typer.Option(
        None,
        "--container-name",
        help="Container name to verify after update. create sites read this from the marker.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        help="Force a specific workspace/NAS target (see secrets/<name>/)",
    ),
) -> None:
    settings: Settings | None = None
    domain_for_notification = domain
    try:
        settings = load_config()
        domain = apply_default_site_domain(domain, settings.default_site_domain)
        domain_for_notification = domain
        target = settings.resolve_target(workspace=workspace)
        prompted_password = None
        if not target.ssh_key_path and not target.ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        result = update_site(
            domain,
            settings=settings,
            compose_file=compose_file,
            pull=pull,
            build=build,
            health_path=health_path,
            container_name=container_name,
            dry_run=dry_run or settings.dry_run,
            workspace=workspace,
            prompted_password=prompted_password,
        )
    except (SynologySiteError, json.JSONDecodeError) as exc:
        if settings is not None:
            send_webhook_notification(
                settings,
                event="failure",
                command="update",
                title=f"Update failed: {domain_for_notification}",
                detail=str(exc),
            )
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    ok(f"Updated {result.domain}")
    ok(f"Project folder: {result.project_path}")
    if result.compose_uploaded:
        ok(f"Uploaded new compose file: {result.compose_file}")
    if result.pulled:
        ok("Pulled latest images")
    if result.built:
        ok("Rebuilt images")
    if result.health_url:
        ok(f"Health URL: {result.health_url}")
    send_webhook_notification(
        settings,
        event="success",
        command="update",
        title=f"Update succeeded: {result.domain}",
        detail=f"Project folder: {result.project_path}",
    )
