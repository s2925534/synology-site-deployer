from __future__ import annotations

import contextlib
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from synology_site.commands.check_nas import smart_ssh_factory
from synology_site.config import Settings
from synology_site.docker_remote import (
    detect_compose_command,
    docker_command,
    ensure_remote_directory,
    require_docker,
)
from synology_site.errors import SynologySiteError
from synology_site.port_allocator import find_available_port
from synology_site.ssh_client import SSHClient

SSHFactory = Callable[[Settings, str | None], SSHClient]


@dataclass(frozen=True)
class ComposeBootstrapResult:
    project_path: str
    secrets_file: str
    port: int
    local_url: str


def deploy_generated_compose_app(
    *,
    settings: Settings,
    project_dir_name: str,
    compose_content: Callable[[int], str],
    env_content: str,
    container_names: tuple[str, ...],
    port: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    ssh_factory: SSHFactory = smart_ssh_factory,
    secrets_dir: Path = Path("secrets"),
    prompted_password: str | None = None,
) -> ComposeBootstrapResult:
    project_path = f"{settings.nas_docker_root.rstrip('/')}/{project_dir_name}"

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
            return ComposeBootstrapResult(
                project_path=project_path,
                secrets_file="",
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
        ssh.upload_text(f"{project_path}/docker-compose.yml", compose_content(selected_port))
        remote_env_path = f"{project_path}/.env"
        ssh.upload_text(remote_env_path, env_content)
        ssh.run(f"chmod 600 {shlex.quote(remote_env_path)}", check=True)
        ssh.run(f"cd {quoted_project} && {compose} up -d", check=True)

        docker = docker_command(ssh)
        for name in container_names:
            result = ssh.run(f"{docker} inspect -f '{{{{.State.Running}}}}' {shlex.quote(name)}")
            if not result.ok or result.stdout.strip().lower() != "true":
                msg = f"Container is not running: {name}"
                raise SynologySiteError(msg)

    secrets_dir.mkdir(parents=True, exist_ok=True)
    secrets_path = secrets_dir / f"{project_dir_name}.env"
    secrets_path.write_text(env_content, encoding="utf-8")
    with contextlib.suppress(OSError):
        secrets_path.chmod(0o600)

    return ComposeBootstrapResult(
        project_path=project_path,
        secrets_file=str(secrets_path),
        port=selected_port,
        local_url=local_url,
    )
