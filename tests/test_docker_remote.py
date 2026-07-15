from synology_site.docker_remote import (
    container_logs,
    detect_compose_command,
    docker_command,
    list_containers,
)
from synology_site.ssh_client import RemoteCommandResult


class FakeSSH:
    def __init__(self, *, direct_access: bool = True) -> None:
        self.commands: list[str] = []
        self.direct_access = direct_access

    def run(
        self,
        command: str,
        *,
        check: bool = False,
        timeout: int | None = None,
    ) -> RemoteCommandResult:
        del check, timeout
        self.commands.append(command)
        if command == "command -v docker":
            return RemoteCommandResult(command, 1, "", "")
        if command == "test -x /usr/local/bin/docker":
            return RemoteCommandResult(command, 0, "", "")
        if command == "/usr/local/bin/docker ps --format '{{.Names}}'":
            return RemoteCommandResult(command, 0 if self.direct_access else 1, "", "")
        if command == "sudo -S -p '' /usr/local/bin/docker ps --format '{{.Names}}'":
            return RemoteCommandResult(command, 0, "", "")
        if command == "/usr/local/bin/docker compose version":
            return RemoteCommandResult(command, 0, "Docker Compose version v2\n", "")
        if command == "sudo -S -p '' /usr/local/bin/docker compose version":
            return RemoteCommandResult(command, 0, "Docker Compose version v2\n", "")
        if command.startswith("/usr/local/bin/docker ps -a --format"):
            return RemoteCommandResult(
                command, 0, "traefik\ttraefik:v3.1\tExited (137) 2 minutes ago\n", ""
            )
        if command.startswith("/usr/local/bin/docker ps --format '{{.Names}}\\t"):
            return RemoteCommandResult(command, 0, "traefik\ttraefik:v3.1\tUp 2 hours\n", "")
        if command == "/usr/local/bin/docker logs --tail 50 traefik 2>&1":
            return RemoteCommandResult(command, 0, "level=fatal msg=\"OOM\"\n", "")
        return RemoteCommandResult(command, 1, "", "")


def test_docker_command_falls_back_to_synology_path() -> None:
    fake = FakeSSH()

    assert docker_command(fake) == "/usr/local/bin/docker"


def test_docker_command_uses_sudo_when_daemon_requires_it() -> None:
    fake = FakeSSH(direct_access=False)

    assert docker_command(fake) == "sudo -S -p '' /usr/local/bin/docker"


def test_detect_compose_uses_synology_docker_path() -> None:
    fake = FakeSSH()

    assert detect_compose_command(fake) == "/usr/local/bin/docker compose"


def test_list_containers_all_includes_exited() -> None:
    fake = FakeSSH()

    output = list_containers(fake, all_containers=True)

    assert "Exited" in output
    assert "docker ps -a --format" in fake.commands[-1]


def test_list_containers_running_only_by_default() -> None:
    fake = FakeSSH()

    output = list_containers(fake)

    assert "Up 2 hours" in output


def test_container_logs_returns_recent_output() -> None:
    fake = FakeSSH()

    output = container_logs(fake, "traefik", tail=50)

    assert "OOM" in output
