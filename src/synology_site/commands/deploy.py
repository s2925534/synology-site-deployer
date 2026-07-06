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

from synology_site import __version__
from synology_site.cloudflare.api import configure_cloudflare_route
from synology_site.cloudflare.manual_instructions import build_manual_instructions
from synology_site.commands.check_nas import default_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.docker_remote import (
    detect_compose_command,
    docker_command,
    ensure_remote_directory,
    require_docker,
)
from synology_site.errors import SynologySiteError
from synology_site.naming import domain_to_slug
from synology_site.output import console, next_step, ok, warn
from synology_site.port_allocator import find_available_port
from synology_site.ssh_client import SSHClient
from synology_site.upload_filter import build_ignore_matcher, load_dockerignore_patterns
from synology_site.validators import apply_default_site_domain, validate_domain

# Deploys a project that already has its own Dockerfile/Compose file (e.g. a
# Next.js or Node app built by CI), instead of scaffolding one from templates.
# This is the counterpart to `create`, which only knows how to scaffold Flask.


@dataclass(frozen=True)
class DeployResult:
    domain: str
    slug: str
    project_path: str
    compose_command: str
    compose_file: str
    uploaded_files: tuple[str, ...]
    port: int | None = None
    local_url: str | None = None
    health_url: str | None = None
    container_name: str | None = None


SSHFactory = Callable[[Settings, str | None], SSHClient]
HealthGetter = Callable[..., Any]


def deploy_existing_project(
    domain: str,
    *,
    compose_file: Path,
    settings: Settings,
    env_file: Path | None = None,
    remote_compose_name: str = "docker-compose.yml",
    source_dir: Path | None = None,
    port: int | None = None,
    container_name: str | None = None,
    pull: bool = True,
    build: bool = False,
    health_path: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    strict_cloudflare: bool = False,
    ssh_factory: SSHFactory = default_ssh_factory,
    health_get: HealthGetter = requests.get,
    prompted_password: str | None = None,
) -> DeployResult:
    if health_path and port is None:
        raise SynologySiteError("--health-path requires --port")
    domain = validate_domain(domain)
    if not compose_file.is_file():
        msg = f"Compose file not found: {compose_file}"
        raise SynologySiteError(msg)

    compose_rel_to_source: Path | None = None
    if source_dir is not None:
        if not source_dir.is_dir():
            msg = f"Source directory not found: {source_dir}"
            raise SynologySiteError(msg)
        try:
            compose_rel_to_source = compose_file.resolve().relative_to(source_dir.resolve())
        except ValueError as exc:
            msg = "--compose-file must be inside --source-dir"
            raise SynologySiteError(msg) from exc
        # Uploading source implies building it -- there's nothing to pull
        # that this upload would produce.
        build = True
        pull = False

    slug = domain_to_slug(domain)
    project_path = f"{settings.nas_docker_root.rstrip('/')}/{slug}"
    remote_compose_path = (
        f"repo/{compose_rel_to_source.as_posix()}"
        if source_dir is not None
        else remote_compose_name
    )
    uploaded = [remote_compose_path] + ([".env"] if env_file is not None else [])

    with ssh_factory(settings, prompted_password) as ssh:
        require_docker(ssh)
        compose = detect_compose_command(ssh)
        ensure_remote_directory(ssh, settings.nas_docker_root)

        selected_port = None
        resolved_local_url = None
        if port is not None:
            selected_port = find_available_port(
                ssh,
                start=settings.default_start_port,
                end=settings.default_end_port,
                requested=port,
            )
            resolved_local_url = f"http://{settings.local_base_url_host}:{selected_port}"

        if dry_run:
            return DeployResult(
                domain=domain,
                slug=slug,
                project_path=project_path,
                compose_command=compose,
                compose_file=remote_compose_path,
                uploaded_files=tuple(uploaded),
                port=selected_port,
                local_url=resolved_local_url,
                health_url=_health_url(resolved_local_url, health_path),
                container_name=container_name,
            )

        _prepare_remote_project(ssh, project_path, force=force)
        if source_dir is not None:
            # .env is force-excluded from the bulk source upload regardless
            # of .dockerignore -- it would otherwise land with default SFTP
            # permissions instead of the chmod 600 the explicit --env-file
            # upload below gets, and could contain unrelated local secrets.
            patterns = [*load_dockerignore_patterns(source_dir / ".dockerignore"), ".env"]
            ignore = build_ignore_matcher(patterns)
            uploaded_source = ssh.upload_directory(
                source_dir, f"{project_path}/repo", ignore=ignore
            )
            uploaded = [f"repo/{p}" for p in uploaded_source]
            env_dir = f"{project_path}/repo/{compose_rel_to_source.parent.as_posix()}"
        else:
            ssh.upload_text(
                f"{project_path}/{remote_compose_name}",
                compose_file.read_text(encoding="utf-8"),
            )
            env_dir = project_path

        if env_file is not None:
            remote_env_path = f"{env_dir}/.env"
            ssh.upload_text(remote_env_path, env_file.read_text(encoding="utf-8"))
            ssh.run(f"chmod 600 {shlex.quote(remote_env_path)}", check=True)
        _write_marker(ssh, project_path, domain, slug, selected_port, remote_compose_path)

        _start_compose(ssh, project_path, compose, remote_compose_path, pull=pull, build=build)
        if container_name:
            docker = docker_command(ssh)
            _confirm_container(ssh, container_name, docker)
        if health_path and resolved_local_url:
            _confirm_health(health_get, f"{resolved_local_url}{health_path}")

    return DeployResult(
        domain=domain,
        slug=slug,
        project_path=project_path,
        compose_command=compose,
        compose_file=remote_compose_path,
        uploaded_files=tuple(uploaded),
        port=selected_port,
        local_url=resolved_local_url,
        health_url=_health_url(resolved_local_url, health_path),
        container_name=container_name,
    )


def _health_url(local_url: str | None, health_path: str | None) -> str | None:
    if local_url and health_path:
        return f"{local_url}{health_path}"
    return None


def _prepare_remote_project(ssh: SSHClient, project_path: str, *, force: bool) -> None:
    quoted_project = shlex.quote(project_path)
    exists = ssh.run(f"test -e {quoted_project}")
    if exists.ok and not force:
        msg = f"Remote project folder already exists: {project_path}. Use --force to overwrite."
        raise SynologySiteError(msg)
    ssh.run(f"mkdir -p {quoted_project}", check=True)


def _write_marker(
    ssh: SSHClient,
    project_path: str,
    domain: str,
    slug: str,
    port: int | None,
    compose_file: str,
) -> None:
    marker = {
        "tool": "synology-site-deployer",
        "version": __version__,
        "domain": domain,
        "slug": slug,
        "framework": "existing",
        "mode": "deploy",
        "port": port,
        "compose_file": compose_file,
    }
    ssh.upload_text(f"{project_path}/.synology-site.json", json.dumps(marker, indent=2) + "\n")


def _start_compose(
    ssh: SSHClient,
    project_path: str,
    compose: str,
    compose_file: str,
    *,
    pull: bool,
    build: bool,
) -> None:
    quoted_project = shlex.quote(project_path)
    quoted_file = shlex.quote(compose_file)
    base = f"cd {quoted_project} && {compose} -f {quoted_file}"
    if pull and not build:
        pull_result = ssh.run(f"{base} pull")
        if not pull_result.ok:
            warn("docker compose pull failed; falling back to a local build")
            build = True
    up_flags = " up -d --build" if build else " up -d"
    result = ssh.run(f"{base}{up_flags}")
    if result.ok:
        return
    fallback_compose = "docker-compose" if compose != "docker-compose" else None
    if fallback_compose:
        fallback = ssh.run(
            f"cd {quoted_project} && {fallback_compose} -f {quoted_file}{up_flags}"
        )
        if fallback.ok:
            return
    raise SynologySiteError("Docker Compose failed to start the project")


def _confirm_container(ssh: SSHClient, name: str, docker: str = "docker") -> None:
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
    compose_file: Path = typer.Option(  # noqa: B008
        ..., "--compose-file", exists=True, dir_okay=False
    ),
    env_file: Path | None = typer.Option(  # noqa: B008
        None, "--env-file", exists=True, dir_okay=False
    ),
    remote_compose_name: str = typer.Option("docker-compose.yml", "--remote-compose-name"),
    source_dir: Path | None = typer.Option(  # noqa: B008
        None,
        "--source-dir",
        exists=True,
        file_okay=False,
        help="Upload this whole local directory (respecting its .dockerignore, plus .env "
        "always excluded) instead of just --compose-file, and build on the NAS -- for a "
        "Compose file whose build context needs more than itself (e.g. a monorepo). "
        "--compose-file must be inside this directory. Implies --build --no-pull.",
    ),
    port: int | None = typer.Option(
        None, "--port", help="Publish/route a host port for this service (omit for "
        "reverse-proxy-fronted deployments, e.g. behind Traefik)"
    ),
    container_name: str | None = typer.Option(
        None, "--container-name", help="Container name to verify is running after startup"
    ),
    pull: bool = typer.Option(True, "--pull/--no-pull"),
    build: bool = typer.Option(False, "--build/--no-build"),
    health_path: str | None = typer.Option(None, "--health-path"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    force: bool = typer.Option(False, "--force"),
    strict_cloudflare: bool = typer.Option(False, "--strict-cloudflare"),
    workspace: str | None = typer.Option(
        None, "--workspace", help="Force a specific Cloudflare workspace (see secrets/<name>/)"
    ),
) -> None:
    try:
        settings = load_config()
        domain = apply_default_site_domain(domain, settings.default_site_domain)
        prompted_password = None
        if not settings.nas_ssh_key_path and not settings.nas_ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        result = deploy_existing_project(
            domain,
            compose_file=compose_file,
            settings=settings,
            env_file=env_file,
            remote_compose_name=remote_compose_name,
            source_dir=source_dir,
            port=port,
            container_name=container_name,
            pull=pull,
            build=build,
            health_path=health_path,
            force=force or settings.allow_overwrite,
            dry_run=dry_run or settings.dry_run,
            strict_cloudflare=strict_cloudflare,
            prompted_password=prompted_password,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Result")
    ok(f"Domain: {result.domain}")
    ok(f"Project folder: {result.project_path}")
    if result.local_url:
        ok(f"Local URL: {result.local_url}")
    if result.health_url:
        ok(f"Health URL: {result.health_url}")

    if result.port is None:
        next_step(
            "No --port was given, so Cloudflare routing was skipped. This deployment is "
            "expected to be reachable through an existing reverse proxy/tunnel route "
            "(e.g. Traefik) already configured on the NAS."
        )
    else:
        account = settings.resolve_cloudflare(result.domain, workspace=workspace)
        if account.ready:
            try:
                configure_cloudflare_route(
                    account,
                    hostname=result.domain,
                    service_url=result.local_url,
                )
                ok(f"Cloudflare route configured: {result.domain} -> {result.local_url}")
            except SynologySiteError as exc:
                warn(str(exc))
                if strict_cloudflare:
                    raise typer.Exit(1) from exc
                console.print(
                    build_manual_instructions(
                        result.domain,
                        account.zone_domain,
                        settings.local_base_url_host,
                        result.port,
                        account.tunnel_name,
                    )
                )
        else:
            warn("Cloudflare API credentials are incomplete. Manual setup is required.")
            console.rule("Cloudflare")
            console.print(
                build_manual_instructions(
                    result.domain,
                    account.zone_domain,
                    settings.local_base_url_host,
                    result.port,
                    account.tunnel_name,
                )
            )
    next_step(f"Open {result.local_url or 'the domain via your existing reverse proxy route'}")
