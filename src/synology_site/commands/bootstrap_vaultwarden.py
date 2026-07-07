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
from synology_site.validators import validate_domain

# Vaultwarden is security-sensitive, so the bootstrap defaults to no open
# public signups. The generated admin token is saved locally so the owner can
# reach /admin and invite the first user without exposing registration.

VAULTWARDEN_IMAGE = "vaultwarden/server:latest"


@dataclass(frozen=True)
class BootstrapVaultwardenResult:
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
        f"    image: {VAULTWARDEN_IMAGE}\n"
        f"    container_name: {container_name}\n"
        f"    restart: {restart_policy}\n"
        "    ports:\n"
        f'      - "{port}:80"\n'
        "    env_file:\n"
        "      - .env\n"
        "    volumes:\n"
        f"      - {container_name}-data:/data\n"
        "\n"
        "volumes:\n"
        f"  {container_name}-data:\n"
    )


def _env_content(
    *,
    admin_token: str,
    hostname: str | None,
    signups_allowed: bool,
) -> str:
    lines = [
        f"ADMIN_TOKEN={admin_token}",
        f"SIGNUPS_ALLOWED={str(signups_allowed).lower()}",
        "INVITATIONS_ALLOWED=true",
        "WEBSOCKET_ENABLED=true",
    ]
    if hostname:
        lines.append(f"DOMAIN=https://{hostname}")
    return "\n".join(lines) + "\n"


def bootstrap_vaultwarden(
    *,
    settings: Settings,
    project_dir_name: str = "vaultwarden",
    hostname: str | None = None,
    port: int | None = None,
    signups_allowed: bool = False,
    force: bool = False,
    dry_run: bool = False,
    ssh_factory: SSHFactory = default_ssh_factory,
    secrets_dir: Path = Path("secrets"),
    prompted_password: str | None = None,
) -> BootstrapVaultwardenResult:
    if hostname is not None:
        hostname = validate_domain(hostname)
    project_path = f"{settings.nas_docker_root.rstrip('/')}/{project_dir_name}"
    container_name = project_dir_name
    admin_token = generate_password(48)
    final_env = _env_content(
        admin_token=admin_token,
        hostname=hostname,
        signups_allowed=signups_allowed,
    )
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

    return BootstrapVaultwardenResult(
        project_path=project_path,
        secrets_file=deployed.secrets_file,
        container_name=container_name,
        port=deployed.port,
        local_url=deployed.local_url,
        public_url=public_url,
    )


def app(
    project_dir_name: str = typer.Option("vaultwarden", "--project-dir-name"),
    hostname: str | None = typer.Option(
        None,
        "--hostname",
        help="Public HTTPS hostname for DOMAIN, e.g. vault.example.com",
    ),
    port: int | None = typer.Option(None, "--port"),
    allow_signups: bool = typer.Option(False, "--allow-signups"),
    force: bool = typer.Option(False, "--force"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    try:
        settings = load_config()
        prompted_password = None
        if not settings.nas_ssh_key_path and not settings.nas_ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        result = bootstrap_vaultwarden(
            settings=settings,
            project_dir_name=project_dir_name,
            hostname=hostname,
            port=port,
            signups_allowed=allow_signups,
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
        ok(f"Public URL configured in Vaultwarden: {result.public_url}")
    if result.secrets_file:
        ok(f"Secrets written to: {result.secrets_file} -- keep this safe, never commit it")
        warn("This file contains ADMIN_TOKEN for Vaultwarden's /admin page.")
    next_step("Open /admin with ADMIN_TOKEN to invite the first user or adjust settings.")
    next_step(
        f"Wire up public access with: synology-site cloudflare-route <hostname> "
        f"--port {result.port}"
    )
