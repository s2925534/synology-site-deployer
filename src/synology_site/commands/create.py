from __future__ import annotations

import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path
from typing import Any

import requests
import typer

from synology_site.cloudflare.api import CloudflareAPI, configure_cloudflare_route
from synology_site.cloudflare.domain_split import split_domain_for_zone
from synology_site.cloudflare.manual_instructions import build_manual_instructions
from synology_site.commands.check_nas import smart_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.database.naming import database_name, database_user
from synology_site.database.passwords import generate_password
from synology_site.database.shared_mariadb import (
    ensure_shared_mariadb_running,
    provision_scoped_database,
    read_shared_root_password,
)
from synology_site.docker_remote import (
    detect_compose_command,
    docker_command,
    ensure_remote_directory,
    require_docker,
)
from synology_site.errors import SynologySiteError
from synology_site.godaddy.api import check_nameservers
from synology_site.naming import db_container_name, domain_to_slug, redis_container_name
from synology_site.output import console, next_step, ok, warn
from synology_site.port_allocator import find_available_port
from synology_site.scaffold import (
    FRAMEWORKS,
    PRODUCTION_PHP_SERVERS,
    validate_frontend,
    validate_php_server,
    validate_wordpress_db_mode,
)
from synology_site.scaffold.base import GeneratedFile, ScaffoldContext
from synology_site.ssh_client import SSHClient
from synology_site.validators import apply_default_site_domain, validate_domain


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
    redis_enabled: bool = False,
    queue_enabled: bool = False,
    scheduler_enabled: bool = False,
    frontend: str = "none",
    php_server: str = "artisan",
    wp_table_prefix: str = "wp_",
    wordpress_image_tag: str = "apache",
    workspace: str | None = None,
    ssh_factory: SSHFactory = smart_ssh_factory,
    health_get: HealthGetter = requests.get,
    prompted_password: str | None = None,
    secrets_dir: Path = Path("secrets"),
) -> CreateResult:
    if db_mode not in {"none", "container", "external"}:
        raise SynologySiteError("Only DB mode none, container, or external is supported")
    validate_wordpress_db_mode(framework, db_mode)
    if redis_enabled and framework != "laravel":
        raise SynologySiteError("--with-redis is only applicable to --framework laravel")
    if queue_enabled and framework != "laravel":
        raise SynologySiteError("--with-queue is only applicable to --framework laravel")
    if queue_enabled and not redis_enabled:
        raise SynologySiteError(
            "--with-queue requires --with-redis (a queue worker needs a real queue backend, "
            "not the default sync driver)"
        )
    if scheduler_enabled and framework != "laravel":
        raise SynologySiteError("--with-scheduler is only applicable to --framework laravel")
    validate_php_server(framework, php_server)
    validate_frontend(framework, frontend, php_server)
    domain = validate_domain(domain)
    scaffold = FRAMEWORKS.get(framework)
    if scaffold is None:
        msg = f"Unsupported framework: {framework}"
        raise SynologySiteError(msg)

    account = settings.resolve_cloudflare(domain, workspace=workspace)
    cf_split = split_domain_for_zone(domain, account.zone_domain, strict=False)
    if cf_split.warning and strict_cloudflare:
        raise SynologySiteError(cf_split.warning)

    target = settings.resolve_target(workspace=workspace)
    connection_settings = settings.resolved_for(target)

    slug = domain_to_slug(domain)
    project_path = f"{target.docker_root.rstrip('/')}/{slug}"
    local_url = f"http://{target.local_base_url_host}:{{port}}"

    with ssh_factory(connection_settings, prompted_password) as ssh:
        require_docker(ssh)
        compose = detect_compose_command(ssh)
        ensure_remote_directory(ssh, target.docker_root)
        selected_port = find_available_port(
            ssh,
            start=target.default_start_port,
            end=target.default_end_port,
            requested=port,
            docker_root=target.docker_root,
            domain=domain,
        )
        resolved_local_url = local_url.format(port=selected_port)
        db_enabled = db_mode in {"container", "external"}
        db_password = generate_password(settings.db_password_length) if db_enabled else None
        # Only a dedicated per-site container has its own root password to generate --
        # "external" sites authenticate with a scoped user/password on the shared
        # instance, provisioned below, and never see its root credential.
        db_root_password = (
            generate_password(settings.db_password_length) if db_mode == "container" else None
        )
        context = ScaffoldContext(
            domain=domain,
            slug=slug,
            framework=framework,
            port=selected_port,
            project_path=project_path,
            local_base_url_host=target.local_base_url_host,
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
            php_server=php_server,
            frontend=frontend,
            redis_enabled=redis_enabled,
            queue_enabled=queue_enabled,
            scheduler_enabled=scheduler_enabled,
            wp_table_prefix=wp_table_prefix,
            wordpress_image_tag=wordpress_image_tag,
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

        if context.db_mode == "external":
            ensure_shared_mariadb_running(ssh)
            provision_scoped_database(
                ssh,
                root_password=read_shared_root_password(secrets_dir),
                db_name=context.db_name,
                db_user=context.db_user,
                db_password=context.db_password,
            )

        _prepare_remote_project(ssh, project_path, force=force)
        _upload_files(ssh, project_path, files)
        _start_compose(ssh, project_path, compose)
        docker = docker_command(ssh)
        for container_name in scaffold.container_names(context):
            _confirm_container(ssh, container_name, docker)
        if context.db_mode == "container":
            _confirm_container(ssh, db_container_name(domain), docker)
        if context.redis_enabled:
            _confirm_container(ssh, redis_container_name(domain), docker)
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


def _confirm_container(ssh: SSHClient, slug: str, docker: str = "docker") -> None:
    result = ssh.run(f"{docker} inspect -f '{{{{.State.Running}}}}' {shlex.quote(slug)}")
    if not result.ok or result.stdout.strip().lower() != "true":
        msg = f"Container is not running: {slug}"
        raise SynologySiteError(msg)


def _warn_on_godaddy_nameserver_mismatch(
    settings: Settings,
    domain: str,
    *,
    workspace: str | None,
    cloudflare_session: Any = requests,
    godaddy_session: Any = requests,
) -> None:
    """Best-effort, read-only: if a GoDaddy account is configured, compare its nameservers for
    `domain` against the Cloudflare zone's assigned ones and warn on a mismatch. Never raises --
    any failure here (no GoDaddy account configured, domain not found at GoDaddy, network
    error) is swallowed, since this is purely informational and must never block a deploy.
    """
    try:
        godaddy_account = settings.resolve_godaddy(workspace=workspace)
        if not godaddy_account.ready:
            return
        cf_account = settings.resolve_cloudflare(domain, workspace=workspace)
        if not cf_account.ready:
            return
        expected = CloudflareAPI(cf_account, session=cloudflare_session).get_zone_nameservers()
        result = check_nameservers(
            godaddy_account,
            domain=domain,
            expected_nameservers=expected,
            session=godaddy_session,
        )
        if not result.matches:
            warn(
                f"GoDaddy nameservers for {domain} don't match this Cloudflare zone -- "
                f"current: {', '.join(result.current_nameservers)}; "
                f"expected: {', '.join(result.expected_nameservers)}. "
                "Run `synology-site godaddy-nameservers` to review/fix."
            )
    except Exception:  # noqa: BLE001
        pass


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
    framework: str = typer.Option("flask", "--framework"),
    port: int | None = typer.Option(None, "--port"),
    with_db: bool = typer.Option(False, "--with-db"),
    db_mode: str = typer.Option(
        "none",
        "--db-mode",
        help="'none' (default), 'container' (dedicated MariaDB container for this site, "
        "same as --with-db), or 'external' (join the shared MariaDB instance from "
        "`bootstrap-mariadb` instead, with a database/user scoped to just this site).",
    ),
    with_redis: bool = typer.Option(
        False,
        "--with-redis",
        help="Laravel only. Adds a Redis container, and switches cache/session/queue "
        "drivers to it instead of file/sync.",
    ),
    with_queue: bool = typer.Option(
        False,
        "--with-queue",
        help="Laravel only. Adds a queue worker container (php artisan queue:work) sharing "
        "the app's image. Requires --with-redis.",
    ),
    with_scheduler: bool = typer.Option(
        False,
        "--with-scheduler",
        help="Laravel only. Adds a container looping php artisan schedule:run every minute "
        "(Laravel has no built-in scheduler daemon).",
    ),
    frontend: str = typer.Option(
        "none",
        "--frontend",
        help="Laravel only. 'none' (default), 'livewire', 'inertia-vue', 'inertia-react' "
        "(single container), or 'vue'/'react'/'angular' (decoupled SPA, requires "
        "--php-server fpm-nginx).",
    ),
    php_server: str = typer.Option(
        "artisan",
        "--php-server",
        help="Laravel only. 'artisan' (php artisan serve, single process) or 'fpm-nginx' "
        "(PHP-FPM + nginx, two containers -- recommended for production NAS use).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
    force: bool = typer.Option(False, "--force"),
    strict_cloudflare: bool = typer.Option(False, "--strict-cloudflare"),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        help="Force a specific workspace (Cloudflare account and/or NAS target, "
        "see secrets/<name>/)",
    ),
) -> None:
    selected_db_mode = "container" if with_db else db_mode
    try:
        settings = load_config()
        domain = apply_default_site_domain(domain, settings.default_site_domain)
        target = settings.resolve_target(workspace=workspace)
        prompted_password = None
        if not target.ssh_key_path and not target.ssh_password:
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
            redis_enabled=with_redis,
            queue_enabled=with_queue,
            scheduler_enabled=with_scheduler,
            frontend=frontend,
            php_server=php_server,
            workspace=workspace,
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
    if framework == "laravel" and php_server not in PRODUCTION_PHP_SERVERS:
        warn(
            "Running php artisan serve (single process, not production-grade). "
            "For a NAS deployment meant for production traffic, re-run with "
            "--php-server fpm-nginx for a PHP-FPM + nginx setup."
        )
    account = settings.resolve_cloudflare(result.domain, workspace=workspace)
    if account.ready:
        try:
            configure_cloudflare_route(
                account,
                hostname=result.domain,
                service_url=result.local_url,
            )
            ok(f"Cloudflare route configured: {result.domain} -> {result.local_url}")
            _warn_on_godaddy_nameserver_mismatch(settings, result.domain, workspace=workspace)
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
    next_step(f"Open {result.local_url}")
