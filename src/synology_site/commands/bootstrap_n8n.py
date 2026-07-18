from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path

import typer

from synology_site.commands.bootstrap_compose import deploy_generated_compose_app
from synology_site.commands.check_nas import smart_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.database.passwords import generate_password
from synology_site.errors import SynologySiteError
from synology_site.output import console, next_step, ok, warn
from synology_site.ssh_client import SSHClient
from synology_site.validators import validate_domain

# n8n is another "single command, popular self-hosted stack" like Uptime Kuma,
# but it has one critical generated secret: N8N_ENCRYPTION_KEY. n8n uses that
# key to encrypt stored credentials, so losing it makes existing credentials
# unrecoverable even if the SQLite volume is intact.

N8N_IMAGE = "n8nio/n8n:1"


@dataclass(frozen=True)
class BootstrapN8nResult:
    project_path: str
    secrets_file: str
    container_name: str
    port: int
    local_url: str
    public_url: str | None


SSHFactory = Callable[[Settings, str | None], SSHClient]


def _compose_content(*, container_name: str, port: int, restart_policy: str) -> str:
    return (
        "services:\n"
        f"  {container_name}:\n"
        f"    image: {N8N_IMAGE}\n"
        f"    container_name: {container_name}\n"
        f"    restart: {restart_policy}\n"
        "    ports:\n"
        f'      - "{port}:5678"\n'
        "    env_file:\n"
        "      - .env\n"
        "    volumes:\n"
        f"      - {container_name}-data:/home/node/.n8n\n"
        "\n"
        "volumes:\n"
        f"  {container_name}-data:\n"
    )


def _env_content(*, encryption_key: str, hostname: str | None) -> str:
    lines = [
        f"N8N_ENCRYPTION_KEY={encryption_key}",
        "N8N_DIAGNOSTICS_ENABLED=false",
        "N8N_PERSONALIZATION_ENABLED=false",
        "N8N_HIRING_BANNER_ENABLED=false",
        "GENERIC_TIMEZONE=UTC",
        "TZ=UTC",
    ]
    if hostname:
        public_url = f"https://{hostname}"
        lines.extend(
            [
                f"N8N_HOST={hostname}",
                "N8N_PROTOCOL=https",
                f"N8N_EDITOR_BASE_URL={public_url}",
                f"WEBHOOK_URL={public_url}/",
            ]
        )
    else:
        # Local HTTP access is useful before a public hostname is routed. With a
        # plain HTTP URL, secure cookies prevent the first-run UI from working.
        lines.append("N8N_SECURE_COOKIE=false")
    return "\n".join(lines) + "\n"


def bootstrap_n8n(
    *,
    settings: Settings,
    project_dir_name: str = "n8n",
    hostname: str | None = None,
    port: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    ssh_factory: SSHFactory = smart_ssh_factory,
    secrets_dir: Path = Path("secrets"),
    prompted_password: str | None = None,
) -> BootstrapN8nResult:
    if hostname is not None:
        hostname = validate_domain(hostname)
    project_path = f"{settings.nas_docker_root.rstrip('/')}/{project_dir_name}"
    container_name = project_dir_name
    encryption_key = generate_password(64)
    final_env = _env_content(encryption_key=encryption_key, hostname=hostname)
    public_url = f"https://{hostname}" if hostname else None
    deployed = deploy_generated_compose_app(
        settings=settings,
        project_dir_name=project_dir_name,
        compose_content=lambda selected_port: _compose_content(
            container_name=container_name,
            port=selected_port,
            restart_policy=settings.restart_policy,
        ),
        env_content=final_env,
        container_names=(container_name,),
        port=port,
        force=force,
        dry_run=dry_run,
        ssh_factory=ssh_factory,
        secrets_dir=secrets_dir,
        prompted_password=prompted_password,
    )

    return BootstrapN8nResult(
        project_path=project_path,
        secrets_file=deployed.secrets_file,
        container_name=container_name,
        port=deployed.port,
        local_url=deployed.local_url,
        public_url=public_url,
    )


def app(
    project_dir_name: str = typer.Option("n8n", "--project-dir-name"),
    hostname: str | None = typer.Option(
        None,
        "--hostname",
        help="Public HTTPS hostname for editor/webhook URLs, e.g. n8n.example.com",
    ),
    port: int | None = typer.Option(None, "--port"),
    force: bool = typer.Option(False, "--force"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    try:
        settings = load_config()
        prompted_password = None
        if not settings.nas_ssh_key_path and not settings.nas_ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        result = bootstrap_n8n(
            settings=settings,
            project_dir_name=project_dir_name,
            hostname=hostname,
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
    if result.public_url:
        ok(f"Public URL configured in n8n: {result.public_url}")
    if result.secrets_file:
        ok(f"Secrets written to: {result.secrets_file} -- keep this safe, never commit it")
        warn("This file contains N8N_ENCRYPTION_KEY, which protects stored credentials.")
    next_step("Open n8n to complete its first-run owner setup.")
    next_step(
        f"Wire up public access with: synology-site cloudflare-route <hostname> "
        f"--port {result.port}"
    )
