from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path

import typer

from synology_site.commands.bootstrap_compose import deploy_generated_compose_app
from synology_site.commands.check_nas import default_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.database.passwords import generate_password
from synology_site.errors import SynologySiteError
from synology_site.output import console, next_step, ok, warn
from synology_site.ssh_client import SSHClient

# Umami's official Docker install is a two-service Compose project:
# the analytics app plus PostgreSQL. This bootstrap keeps that topology,
# but replaces the example database password and APP_SECRET with generated
# values and stores them locally for recovery.

UMAMI_IMAGE = "ghcr.io/umami-software/umami:latest"
UMAMI_DB_IMAGE = "postgres:15-alpine"


@dataclass(frozen=True)
class BootstrapUmamiResult:
    project_path: str
    secrets_file: str
    container_name: str
    db_container_name: str
    port: int
    local_url: str


SSHFactory = Callable[[Settings, str | None], SSHClient]


def _compose_content(*, container_name: str, port: int, restart_policy: str) -> str:
    db_container_name = f"{container_name}-db"
    return (
        "services:\n"
        f"  {container_name}:\n"
        f"    image: {UMAMI_IMAGE}\n"
        f"    container_name: {container_name}\n"
        f"    restart: {restart_policy}\n"
        "    init: true\n"
        "    ports:\n"
        f'      - "{port}:3000"\n'
        "    env_file:\n"
        "      - .env\n"
        "    depends_on:\n"
        "      db:\n"
        "        condition: service_healthy\n"
        "    healthcheck:\n"
        '      test: ["CMD-SHELL", "curl http://localhost:3000/api/heartbeat"]\n'
        "      interval: 5s\n"
        "      timeout: 5s\n"
        "      retries: 5\n"
        "  db:\n"
        f"    image: {UMAMI_DB_IMAGE}\n"
        f"    container_name: {db_container_name}\n"
        f"    restart: {restart_policy}\n"
        "    env_file:\n"
        "      - .env\n"
        "    volumes:\n"
        f"      - {container_name}-db-data:/var/lib/postgresql/data\n"
        "    healthcheck:\n"
        '      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]\n'
        "      interval: 5s\n"
        "      timeout: 5s\n"
        "      retries: 5\n"
        "\n"
        "volumes:\n"
        f"  {container_name}-db-data:\n"
    )


def _env_content(*, postgres_password: str, app_secret: str) -> str:
    return (
        "POSTGRES_DB=umami\n"
        "POSTGRES_USER=umami\n"
        f"POSTGRES_PASSWORD={postgres_password}\n"
        f"DATABASE_URL=postgresql://umami:{postgres_password}@db:5432/umami\n"
        f"APP_SECRET={app_secret}\n"
    )


def bootstrap_umami(
    *,
    settings: Settings,
    project_dir_name: str = "umami",
    port: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    ssh_factory: SSHFactory = default_ssh_factory,
    secrets_dir: Path = Path("secrets"),
    prompted_password: str | None = None,
) -> BootstrapUmamiResult:
    project_path = f"{settings.nas_docker_root.rstrip('/')}/{project_dir_name}"
    container_name = project_dir_name
    db_container_name = f"{container_name}-db"
    final_env = _env_content(
        postgres_password=generate_password(settings.db_password_length),
        app_secret=generate_password(64),
    )
    deployed = deploy_generated_compose_app(
        settings=settings,
        project_dir_name=project_dir_name,
        compose_content=lambda selected_port: _compose_content(
            container_name=container_name,
            port=selected_port,
            restart_policy=settings.restart_policy,
        ),
        env_content=final_env,
        container_names=(container_name, db_container_name),
        port=port,
        force=force,
        dry_run=dry_run,
        ssh_factory=ssh_factory,
        secrets_dir=secrets_dir,
        prompted_password=prompted_password,
    )

    return BootstrapUmamiResult(
        project_path=project_path,
        secrets_file=deployed.secrets_file,
        container_name=container_name,
        db_container_name=db_container_name,
        port=deployed.port,
        local_url=deployed.local_url,
    )


def app(
    project_dir_name: str = typer.Option("umami", "--project-dir-name"),
    port: int | None = typer.Option(None, "--port"),
    force: bool = typer.Option(False, "--force"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    try:
        settings = load_config()
        prompted_password = None
        if not settings.nas_ssh_key_path and not settings.nas_ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        result = bootstrap_umami(
            settings=settings,
            project_dir_name=project_dir_name,
            port=port,
            force=force or settings.allow_overwrite,
            dry_run=dry_run or settings.dry_run,
            prompted_password=prompted_password,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Result")
    ok(f"Project folder: {result.project_path}")
    ok(f"Local URL: {result.local_url}")
    if result.secrets_file:
        ok(f"Secrets written to: {result.secrets_file} -- keep this safe, never commit it")
        warn("This file contains Umami's Postgres password and APP_SECRET.")
    next_step("Log in with Umami's default admin account and change the password immediately.")
    next_step(
        f"Wire up public access with: synology-site cloudflare-route <hostname> "
        f"--port {result.port}"
    )
