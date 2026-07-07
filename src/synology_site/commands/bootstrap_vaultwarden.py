from __future__ import annotations

import contextlib
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path

import typer

from synology_site.commands.check_nas import default_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.database.passwords import generate_password
from synology_site.docker_remote import (
    detect_compose_command,
    docker_command,
    ensure_remote_directory,
    require_docker,
)
from synology_site.errors import SynologySiteError
from synology_site.output import console, next_step, ok, warn
from synology_site.port_allocator import find_available_port
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
        local_url = f"http://{settings.local_base_url_host}:{selected_port}"
        public_url = f"https://{hostname}" if hostname else None

        if dry_run:
            return BootstrapVaultwardenResult(
                project_path=project_path,
                secrets_file="",
                container_name=container_name,
                port=selected_port,
                local_url=local_url,
                public_url=public_url,
            )

        quoted_project = shlex.quote(project_path)
        exists = ssh.run(f"test -e {quoted_project}")
        if exists.ok:
            if not force:
                msg = (
                    f"Remote project folder already exists: {project_path}. "
                    "Use --force to overwrite."
                )
                raise SynologySiteError(msg)
            ssh.run(f"cd {quoted_project} && {compose} down", check=False)
            ssh.run(f"rm -rf {quoted_project}", check=True)

        ssh.run(f"mkdir -p {quoted_project}", check=True)
        ssh.upload_text(
            f"{project_path}/docker-compose.yml",
            _compose_content(
                container_name=container_name,
                port=selected_port,
                restart_policy=settings.restart_policy,
            ),
        )
        remote_env_path = f"{project_path}/.env"
        ssh.upload_text(remote_env_path, final_env)
        ssh.run(f"chmod 600 {shlex.quote(remote_env_path)}", check=True)
        ssh.run(f"cd {quoted_project} && {compose} up -d", check=True)

        docker = docker_command(ssh)
        result = ssh.run(
            f"{docker} inspect -f '{{{{.State.Running}}}}' {shlex.quote(container_name)}"
        )
        if not result.ok or result.stdout.strip().lower() != "true":
            msg = f"Container is not running: {container_name}"
            raise SynologySiteError(msg)

    secrets_dir.mkdir(parents=True, exist_ok=True)
    secrets_path = secrets_dir / f"{project_dir_name}.env"
    secrets_path.write_text(final_env, encoding="utf-8")
    with contextlib.suppress(OSError):
        secrets_path.chmod(0o600)

    return BootstrapVaultwardenResult(
        project_path=project_path,
        secrets_file=str(secrets_path),
        container_name=container_name,
        port=selected_port,
        local_url=local_url,
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
