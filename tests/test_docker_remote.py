from synology_site.docker_remote import detect_compose_command, docker_command
from synology_site.ssh_client import RemoteCommandResult


class FakeSSH:
    def __init__(self) -> None:
        self.commands: list[str] = []

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
        if command == "/usr/local/bin/docker compose version":
            return RemoteCommandResult(command, 0, "Docker Compose version v2\n", "")
        return RemoteCommandResult(command, 1, "", "")


def test_docker_command_falls_back_to_synology_path() -> None:
    fake = FakeSSH()

    assert docker_command(fake) == "/usr/local/bin/docker"


def test_detect_compose_uses_synology_docker_path() -> None:
    fake = FakeSSH()

    assert detect_compose_command(fake) == "/usr/local/bin/docker compose"
