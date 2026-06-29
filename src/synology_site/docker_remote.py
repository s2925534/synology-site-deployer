from __future__ import annotations

import shlex

from synology_site.errors import SynologySiteError
from synology_site.ssh_client import SSHClient


def require_docker(ssh: SSHClient) -> None:
    result = ssh.run("command -v docker")
    if not result.ok:
        raise SynologySiteError("Docker is not available on the NAS")


def detect_compose_command(ssh: SSHClient) -> str:
    result = ssh.run("docker compose version")
    if result.ok:
        return "docker compose"
    fallback = ssh.run("docker-compose version")
    if fallback.ok:
        return "docker-compose"
    raise SynologySiteError("Docker Compose is not available on the NAS")


def ensure_remote_directory(ssh: SSHClient, path: str) -> None:
    quoted = shlex.quote(path)
    result = ssh.run(f"test -d {quoted}")
    if not result.ok:
        msg = f"Remote directory does not exist: {path}"
        raise SynologySiteError(msg)


def list_containers(ssh: SSHClient) -> str:
    return ssh.run("docker ps --format '{{.Names}}\\t{{.Image}}\\t{{.Status}}'", check=True).stdout


def list_published_ports(ssh: SSHClient) -> str:
    return ssh.run("docker ps --format '{{.Ports}}'", check=True).stdout
