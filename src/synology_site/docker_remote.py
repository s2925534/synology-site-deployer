from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from synology_site.errors import SynologySiteError
from synology_site.ssh_client import SSHClient


def docker_command(ssh: SSHClient) -> str:
    result = ssh.run("command -v docker")
    if result.ok and result.stdout.strip():
        docker = "docker"
        if _docker_daemon_accessible(ssh, docker):
            return docker
        sudo_docker = f"sudo -S -p '' {docker}"
        if _docker_daemon_accessible(ssh, sudo_docker):
            return sudo_docker

    for path in [
        "/usr/local/bin/docker",
        "/var/packages/ContainerManager/target/usr/bin/docker",
    ]:
        fallback = ssh.run(f"test -x {shlex.quote(path)}")
        if fallback.ok:
            if _docker_daemon_accessible(ssh, path):
                return path
            sudo_path = f"sudo -S -p '' {path}"
            if _docker_daemon_accessible(ssh, sudo_path):
                return sudo_path

    raise SynologySiteError("Docker is not available on the NAS")


def _docker_daemon_accessible(ssh: SSHClient, docker: str) -> bool:
    result = ssh.run(f"{docker} ps --format '{{{{.Names}}}}'")
    return result.ok


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


def list_containers(ssh: SSHClient, *, all_containers: bool = False) -> str:
    docker = docker_command(ssh)
    flag = " -a" if all_containers else ""
    return ssh.run(
        f"{docker} ps{flag} --format '{{{{.Names}}}}\\t{{{{.Image}}}}\\t{{{{.Status}}}}'",
        check=True,
    ).stdout


def list_published_ports(ssh: SSHClient) -> str:
    docker = docker_command(ssh)
    return ssh.run(f"{docker} ps --format '{{{{.Ports}}}}'", check=True).stdout


def container_logs(ssh: SSHClient, name: str, *, tail: int = 100) -> str:
    """Read-only: the last `tail` lines of a container's logs (stdout+stderr combined)."""
    docker = docker_command(ssh)
    quoted = shlex.quote(name)
    result = ssh.run(f"{docker} logs --tail {int(tail)} {quoted} 2>&1", check=True)
    return result.stdout


@dataclass(frozen=True)
class ContainerInfo:
    name: str
    project: str
    working_dir: str
    status: str
    restart_policy: str
    service: str = ""

    @property
    def has_auto_restart(self) -> bool:
        return self.restart_policy in {"unless-stopped", "always", "on-failure"}

    @property
    def is_running(self) -> bool:
        return self.status.startswith("Up")


def container_restart_policies(ssh: SSHClient, names: list[str]) -> dict[str, str]:
    """Read-only: restart policy name for each of `names`, in one batched `docker inspect`.

    Missing/unparseable entries are simply absent from the returned dict rather than raising --
    callers treat "not present" the same as "unknown", not as a hard failure.
    """
    if not names:
        return {}
    docker = docker_command(ssh)
    quoted_names = " ".join(shlex.quote(name) for name in names)
    result = ssh.run(
        f"{docker} inspect --format "
        "'{{.Name}}\\t{{.HostConfig.RestartPolicy.Name}}' "
        f"{quoted_names}"
    )
    policies: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        policies[parts[0].lstrip("/")] = parts[1]
    return policies


def list_containers_with_projects(ssh: SSHClient) -> list[ContainerInfo]:
    """Read-only: every container (any state), its Compose project/working dir, and its restart
    policy -- the building block `doctor` and `restart-all` both cross-reference site markers
    against, since a container's actual on-disk location (not just its name) is what identifies
    which marker it belongs to.
    """
    docker = docker_command(ssh)
    fmt = (
        "{{.Names}}\\t"
        '{{.Label "com.docker.compose.project"}}\\t'
        '{{.Label "com.docker.compose.project.working_dir"}}\\t'
        '{{.Label "com.docker.compose.service"}}\\t'
        "{{.Status}}"
    )
    result = ssh.run(f"{docker} ps -a --format '{fmt}'", check=True)
    rows: list[tuple[str, str, str, str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        while len(parts) < 5:
            parts.append("")
        rows.append((parts[0], parts[1], parts[2], parts[3], parts[4]))
    policies = container_restart_policies(ssh, [row[0] for row in rows])
    return [
        ContainerInfo(
            name=name,
            project=project,
            working_dir=working_dir,
            status=status,
            restart_policy=policies.get(name, ""),
            service=service,
        )
        for name, project, working_dir, service, status in rows
    ]


@dataclass(frozen=True)
class SystemLoad:
    load1: float
    load5: float
    load15: float


_LOAD_AVERAGE_RE = re.compile(r"load average:\s*([\d.]+),\s*([\d.]+),\s*([\d.]+)")


def read_system_load(ssh: SSHClient) -> SystemLoad:
    """Read-only: 1/5/15-minute load averages, parsed from `uptime`.

    Matches only the three load-average numbers, so it's unaffected by DSM's custom `uptime`
    output on Synology, which appends extra `[IO: ... CPU: ...]` figures after the standard
    three -- those are ignored rather than tripping up parsing.
    """
    result = ssh.run("uptime", check=True)
    match = _LOAD_AVERAGE_RE.search(result.stdout)
    if not match:
        msg = f"Could not parse load average from `uptime` output: {result.stdout!r}"
        raise SynologySiteError(msg)
    return SystemLoad(
        load1=float(match.group(1)),
        load5=float(match.group(2)),
        load15=float(match.group(3)),
    )


@dataclass(frozen=True)
class MemoryInfo:
    total_mb: int
    available_mb: int
    swap_total_mb: int
    swap_used_mb: int

    @property
    def swap_percent(self) -> float:
        if self.swap_total_mb == 0:
            return 0.0
        return (self.swap_used_mb / self.swap_total_mb) * 100


def read_memory_info(ssh: SSHClient) -> MemoryInfo:
    """Read-only: memory/swap usage in MB, parsed from `free -m`."""
    result = ssh.run("free -m", check=True)
    total_mb = available_mb = swap_total_mb = swap_used_mb = 0
    for line in result.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "Mem:" and len(parts) >= 7:
            total_mb = int(parts[1])
            available_mb = int(parts[6])
        elif parts[0] == "Swap:" and len(parts) >= 3:
            swap_total_mb = int(parts[1])
            swap_used_mb = int(parts[2])
    return MemoryInfo(
        total_mb=total_mb,
        available_mb=available_mb,
        swap_total_mb=swap_total_mb,
        swap_used_mb=swap_used_mb,
    )


def compose_services(
    ssh: SSHClient,
    compose_cmd: str,
    working_dir: str,
    *,
    compose_file: str = "docker-compose.yml",
) -> list[str]:
    """Read-only: service names defined in a project's Compose file.

    Always passes `-f` explicitly (never relies on Compose's default-filename discovery) so
    projects using a non-default filename (e.g. `docker-compose.admin.yml`) work the same as
    ones using the default -- the exact gap that made a bare `compose up -d` silently fail with
    "no configuration file provided: not found" for one of this NAS's real projects.
    """
    quoted_dir = shlex.quote(working_dir)
    quoted_file = shlex.quote(compose_file)
    result = ssh.run(
        f"cd {quoted_dir} && {compose_cmd} -f {quoted_file} config --services", check=True
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]
