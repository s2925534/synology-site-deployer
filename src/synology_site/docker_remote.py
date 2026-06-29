from __future__ import annotations

import shlex

from synology_site.errors import SynologySiteError
from synology_site.ssh_client import SSHClient


def docker_command(ssh: SSHClient) -> str:
    result = ssh.run("command -v docker")
    if result.ok and result.stdout.strip():
        return "docker"

    for path in [
        "/usr/local/bin/docker",
        "/var/packages/ContainerManager/target/usr/bin/docker",
    ]:
        fallback = ssh.run(f"test -x {shlex.quote(path)}")
        if fallback.ok:
            return path

    raise SynologySiteError("Docker is not available on the NAS")


def require_docker(ssh: SSHClient) -> str:
    return docker_command(ssh)


def detect_compose_command(ssh: SSHClient) -> str:
    docker = docker_command(ssh)
    result = ssh.run(f"{docker} compose version")
    if result.ok:
        return f"{docker} compose"
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
    docker = docker_command(ssh)
    return ssh.run(
        f"{docker} ps --format '{{{{.Names}}}}\\t{{{{.Image}}}}\\t{{{{.Status}}}}'",
        check=True,
    ).stdout


def list_published_ports(ssh: SSHClient) -> str:
    docker = docker_command(ssh)
    return ssh.run(f"{docker} ps --format '{{{{.Ports}}}}'", check=True).stdout
