from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass
from typing import Any

import requests
import typer

from synology_site.cloudflare.domain_split import split_domain_for_zone
from synology_site.cloudflare.manual_instructions import build_manual_instructions
from synology_site.commands.check_nas import default_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.database.naming import database_name, database_user
from synology_site.database.passwords import generate_password
from synology_site.docker_remote import (
    detect_compose_command,
    ensure_remote_directory,
    require_docker,
)
from synology_site.errors import SynologySiteError
from synology_site.naming import db_container_name, domain_to_slug
from synology_site.output import console, next_step, ok, warn
from synology_site.port_allocator import find_available_port
from synology_site.scaffold import FRAMEWORKS
from synology_site.scaffold.base import GeneratedFile, ScaffoldContext
from synology_site.ssh_client import SSHClient
from synology_site.validators import validate_domain


@dataclass(frozen=True)
class CreateResult:
    domain: str
    slug: str
    port: int
    project_path: str
    local_url: str
    health_url: str
    uploaded_files: tuple[str, ...]
    compose_command: str
    db_enabled: bool = False
    db_health_url: str | None = None


SSHFactory = Callable[[Settings, str | None], SSHClient]
HealthGetter = Callable[..., Any]


def create_site(
    domain: str,
    *,
    settings: Settings,
    framework: str = "flask",
    port: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    strict_cloudflare: bool = False,
    db_mode: str = "none",
    ssh_factory: SSHFactory = default_ssh_factory,
    health_get: HealthGetter = requests.get,
    prompted_password: str | None = None,
) -> CreateResult:
    if db_mode not in {"none", "container"}:
        raise SynologySiteError("Only DB mode none or container is supported")
    domain = validate_domain(domain)
    scaffold = FRAMEWORKS.get(framework)
    if scaffold is None:
        msg = f"Unsupported framework: {framework}"
        raise SynologySiteError(msg)

    cf_split = split_domain_for_zone(domain, settings.cf_zone_domain, strict=False)
    if cf_split.warning and strict_cloudflare:
        raise SynologySiteError(cf_split.warning)

    slug = domain_to_slug(domain)
    project_path = f"{settings.nas_docker_root.rstrip('/')}/{slug}"
    local_url = f"http://{settings.local_base_url_host}:{{port}}"

    with ssh_factory(settings, prompted_password) as ssh:
        require_docker(ssh)
        compose = detect_compose_command(ssh)
        ensure_remote_directory(ssh, settings.nas_docker_root)
        selected_port = find_available_port(
            ssh,
            start=settings.default_start_port,
            end=settings.default_end_port,
            requested=port,
        )
        resolved_local_url = local_url.format(port=selected_port)
        db_enabled = db_mode == "container"
        db_password = generate_password(settings.db_password_length) if db_enabled else None
        db_root_password = generate_password(settings.db_password_length) if db_enabled else None
        context = ScaffoldContext(
            domain=domain,
            slug=slug,
            framework=framework,
            port=selected_port,
            project_path=project_path,
            local_base_url_host=settings.local_base_url_host,
            restart_policy=settings.restart_policy,
            db_enabled=db_enabled,
            db_mode=db_mode,
            db_type=settings.db_type,
            db_image=settings.db_image,
            db_name=database_name(domain),
            db_user=database_user(domain),
            db_password=db_password,
            db_root_password=db_root_password,
            db_publish_port=settings.db_publish_port,
            db_host_port=settings.db_host_port,
        )
        files = scaffold.generate(context)
        if dry_run:
            return CreateResult(
                domain=domain,
                slug=slug,
                port=selected_port,
                project_path=project_path,
                local_url=resolved_local_url,
                health_url=f"{resolved_local_url}/health",
                uploaded_files=tuple(file.path for file in files),
                compose_command=compose,
                db_enabled=context.db_enabled,
                db_health_url=f"{resolved_local_url}/db-health" if context.db_enabled else None,
            )

        _prepare_remote_project(ssh, project_path, force=force)
        _upload_files(ssh, project_path, files)
        _start_compose(ssh, project_path, compose)
        _confirm_container(ssh, slug)
        if context.db_enabled:
            _confirm_container(ssh, db_container_name(domain))
        _confirm_health(health_get, f"{resolved_local_url}/health")
        if context.db_enabled:
            _confirm_health(health_get, f"{resolved_local_url}/db-health")
    return CreateResult(
        domain=domain,
        slug=slug,
        port=selected_port,
        project_path=project_path,
        local_url=resolved_local_url,
        health_url=f"{resolved_local_url}/health",
        uploaded_files=tuple(file.path for file in files),
        compose_command=compose,
        db_enabled=context.db_enabled,
        db_health_url=f"{resolved_local_url}/db-health" if context.db_enabled else None,
    )


def _prepare_remote_project(ssh: SSHClient, project_path: str, *, force: bool) -> None:
    quoted_project = shlex.quote(project_path)
    exists = ssh.run(f"test -e {quoted_project}")
    if exists.ok and not force:
        msg = f"Remote project folder already exists: {project_path}. Use --force to overwrite."
        raise SynologySiteError(msg)
    ssh.run(f"mkdir -p {quoted_project}/app {quoted_project}/docs", check=True)


def _upload_files(ssh: SSHClient, project_path: str, files: list[GeneratedFile]) -> None:
    for file in files:
        remote_path = f"{project_path}/{file.path}"
        ssh.upload_text(remote_path, file.content)
        if file.secret:
            ssh.run(f"chmod 600 {shlex.quote(remote_path)}", check=True)


def _start_compose(ssh: SSHClient, project_path: str, compose: str) -> None:
    quoted_project = shlex.quote(project_path)
    result = ssh.run(f"cd {quoted_project} && {compose} up -d --build")
    if result.ok:
        return
    if compose == "docker compose":
        fallback = ssh.run(f"cd {quoted_project} && docker-compose up -d --build")
        if fallback.ok:
            return
    raise SynologySiteError("Docker Compose failed to start the project")


def _confirm_container(ssh: SSHClient, slug: str) -> None:
    result = ssh.run(f"docker inspect -f '{{{{.State.Running}}}}' {shlex.quote(slug)}")
    if not result.ok or result.stdout.strip().lower() != "true":
        msg = f"Container is not running: {slug}"
        raise SynologySiteError(msg)


def _confirm_health(health_get: HealthGetter, url: str) -> None:
    try:
        response = health_get(url, timeout=20)
    except requests.RequestException as exc:
        msg = f"Health check failed: {url}"
        raise SynologySiteError(msg) from exc
    if response.status_code != 200:
        msg = f"Health check returned HTTP {response.status_code}: {url}"
        raise SynologySiteError(msg)


def app(
    domain: str,
    framework: str = typer.Option("flask", "--framework"),
    port: int | None = typer.Option(None, "--port"),
    with_db: bool = typer.Option(False, "--with-db"),
    db_mode: str = typer.Option("none", "--db-mode"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    force: bool = typer.Option(False, "--force"),
    strict_cloudflare: bool = typer.Option(False, "--strict-cloudflare"),
) -> None:
    selected_db_mode = "container" if with_db else db_mode
    try:
        settings = load_config()
        prompted_password = None
        if not settings.nas_ssh_key_path and not settings.nas_ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        result = create_site(
            domain,
            settings=settings,
            framework=framework,
            port=port,
            force=force or settings.allow_overwrite,
            dry_run=dry_run or settings.dry_run,
            strict_cloudflare=strict_cloudflare,
            db_mode=selected_db_mode,
            prompted_password=prompted_password,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Result")
    ok(f"Domain: {result.domain}")
    ok(f"Project folder: {result.project_path}")
    ok(f"Local URL: {result.local_url}")
    ok(f"Health URL: {result.health_url}")
    if result.db_health_url:
        ok(f"DB Health URL: {result.db_health_url}")
    if not settings.cloudflare_api_ready:
        warn("Cloudflare API credentials are incomplete. Manual setup is required.")
        console.rule("Cloudflare")
        console.print(
            build_manual_instructions(
                result.domain,
                settings.cf_zone_domain,
                settings.local_base_url_host,
                result.port,
                settings.cf_tunnel_name,
            )
        )
    next_step(f"Open {result.local_url}")
