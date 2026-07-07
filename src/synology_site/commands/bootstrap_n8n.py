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
    ssh_factory: SSHFactory = default_ssh_factory,
    secrets_dir: Path = Path("secrets"),
    prompted_password: str | None = None,
) -> BootstrapN8nResult:
    if hostname is not None:
        hostname = validate_domain(hostname)
    project_path = f"{settings.nas_docker_root.rstrip('/')}/{project_dir_name}"
    container_name = project_dir_name
    encryption_key = generate_password(64)
    final_env = _env_content(encryption_key=encryption_key, hostname=hostname)

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
            return BootstrapN8nResult(
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

    return BootstrapN8nResult(
        project_path=project_path,
        secrets_file=str(secrets_path),
        container_name=container_name,
        port=selected_port,
        local_url=local_url,
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
