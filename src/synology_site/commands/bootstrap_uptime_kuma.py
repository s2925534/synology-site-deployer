from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass

import typer

from synology_site.commands.check_nas import default_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.docker_remote import (
    detect_compose_command,
    docker_command,
    ensure_remote_directory,
    require_docker,
)
from synology_site.errors import SynologySiteError
from synology_site.output import console, next_step, ok
from synology_site.port_allocator import find_available_port
from synology_site.ssh_client import SSHClient

# Same "one command, popular self-hosted stack" pattern as bootstrap-supabase, but much
# simpler: Uptime Kuma ships as a single official image with no secrets to regenerate (it has
# its own first-run setup wizard for creating the admin account), so there's no repo to clone
# and no .env to rewrite -- just a small generated Compose file.

UPTIME_KUMA_IMAGE = "louislam/uptime-kuma:1"


def _compose_content(*, container_name: str, port: int, restart_policy: str) -> str:
    return (
        "services:\n"
        f"  {container_name}:\n"
        f"    image: {UPTIME_KUMA_IMAGE}\n"
        f"    container_name: {container_name}\n"
        f"    restart: {restart_policy}\n"
        "    ports:\n"
        f'      - "{port}:3001"\n'
        "    volumes:\n"
        f"      - {container_name}-data:/app/data\n"
        "\n"
        "volumes:\n"
        f"  {container_name}-data:\n"
    )


@dataclass(frozen=True)
class BootstrapUptimeKumaResult:
    project_path: str
    container_name: str
    port: int
    local_url: str


SSHFactory = Callable[[Settings, str | None], SSHClient]


def bootstrap_uptime_kuma(
    *,
    settings: Settings,
    project_dir_name: str = "uptime-kuma",
    port: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    ssh_factory: SSHFactory = default_ssh_factory,
    prompted_password: str | None = None,
) -> BootstrapUptimeKumaResult:
    project_path = f"{settings.nas_docker_root.rstrip('/')}/{project_dir_name}"
    container_name = project_dir_name

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

        if dry_run:
            return BootstrapUptimeKumaResult(
                project_path=project_path,
                container_name=container_name,
                port=selected_port,
                local_url=local_url,
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
        ssh.run(f"cd {quoted_project} && {compose} up -d", check=True)

        docker = docker_command(ssh)
        result = ssh.run(
            f"{docker} inspect -f '{{{{.State.Running}}}}' {shlex.quote(container_name)}"
        )
        if not result.ok or result.stdout.strip().lower() != "true":
            msg = f"Container is not running: {container_name}"
            raise SynologySiteError(msg)

    return BootstrapUptimeKumaResult(
        project_path=project_path,
        container_name=container_name,
        port=selected_port,
        local_url=local_url,
    )


def app(
    project_dir_name: str = typer.Option("uptime-kuma", "--project-dir-name"),
    port: int | None = typer.Option(None, "--port"),
    force: bool = typer.Option(False, "--force"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    try:
        settings = load_config()
        prompted_password = None
        if not settings.nas_ssh_key_path and not settings.nas_ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        result = bootstrap_uptime_kuma(
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
    next_step(
        f"Open {result.local_url} to complete Uptime Kuma's first-run setup wizard "
        "(creates the admin account -- there's no default login)."
    )
    next_step(
        f"Wire up public access with: synology-site cloudflare-route <hostname> "
        f"--port {result.port}"
    )
