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


def test_container_restart_policies_parses_batched_inspect_output() -> None:
    class InspectSSH(FakeSSH):
        def run(self, command, *, check=False, timeout=None):  # noqa: ANN001, ANN201
            if command.startswith("/usr/local/bin/docker inspect --format"):
                return RemoteCommandResult(
                    command,
                    0,
                    "/web\tunless-stopped\n/db\t\n",
                    "",
                )
            return super().run(command, check=check, timeout=timeout)

    from synology_site.docker_remote import container_restart_policies

    policies = container_restart_policies(InspectSSH(), ["web", "db"])

    assert policies == {"web": "unless-stopped", "db": ""}


def test_container_restart_policies_returns_empty_for_no_names() -> None:
    from synology_site.docker_remote import container_restart_policies

    assert container_restart_policies(FakeSSH(), []) == {}


def test_container_restart_policies_uses_a_real_tab_separator() -> None:
    """Regression test: `docker inspect --format` is a Go template, and neither bash's single
    quotes nor Go's text/template interpret backslash escapes in plain template text -- a
    literal two-character "\\t" in the format string reaches Docker unchanged and comes back
    in the output unchanged too, so it can never actually separate the two fields. This fake
    mimics that real pass-through behavior (echoing back whatever separator sits between the
    two `{{...}}` tokens in the command it receives) instead of assuming a well-formed
    response, which is what let the "\\t"-vs-real-tab bug ship undetected originally.
    """

    class LiteralInspectSSH(FakeSSH):
        def run(self, command, *, check=False, timeout=None):  # noqa: ANN001, ANN201
            if command.startswith("/usr/local/bin/docker inspect --format"):
                start = command.index("'{{.Name}}") + len("'{{.Name}}")
                end = command.index("{{.HostConfig.RestartPolicy.Name}}")
                separator = command[start:end]
                return RemoteCommandResult(command, 0, f"/web{separator}unless-stopped\n", "")
            return super().run(command, check=check, timeout=timeout)

    from synology_site.docker_remote import container_restart_policies

    assert container_restart_policies(LiteralInspectSSH(), ["web"]) == {"web": "unless-stopped"}


def test_list_containers_with_projects_joins_status_and_restart_policy() -> None:
    class ProjectsSSH(FakeSSH):
        def run(self, command, *, check=False, timeout=None):  # noqa: ANN001, ANN201
            if command.startswith("/usr/local/bin/docker ps -a --format"):
                return RemoteCommandResult(
                    command,
                    0,
                    "web\tmyproj\t/volume1/docker/myproj\tweb\tUp 2 minutes\n"
                    "orphan\t\t\t\tExited (0) 1 hour ago\n",
                    "",
                )
            if command.startswith("/usr/local/bin/docker inspect --format"):
                return RemoteCommandResult(command, 0, "/web\tunless-stopped\n/orphan\t\n", "")
            return super().run(command, check=check, timeout=timeout)

    from synology_site.docker_remote import list_containers_with_projects

    containers = list_containers_with_projects(ProjectsSSH())

    assert len(containers) == 2
    assert containers[0].name == "web"
    assert containers[0].project == "myproj"
    assert containers[0].working_dir == "/volume1/docker/myproj"
    assert containers[0].service == "web"
    assert containers[0].status == "Up 2 minutes"
    assert containers[0].is_running is True
    assert containers[0].restart_policy == "unless-stopped"
    assert containers[0].has_auto_restart is True
    assert containers[1].name == "orphan"
    assert containers[1].status == "Exited (0) 1 hour ago"
    assert containers[1].is_running is False
    assert containers[1].has_auto_restart is False


def test_read_system_load_parses_standard_uptime() -> None:
    class UptimeSSH(FakeSSH):
        def run(self, command, *, check=False, timeout=None):  # noqa: ANN001, ANN201
            if command == "uptime":
                return RemoteCommandResult(
                    command,
                    0,
                    " 12:00:00 up 1 day,  2:03,  1 user,  load average: 1.50, 2.25, 0.75\n",
                    "",
                )
            return super().run(command, check=check, timeout=timeout)

    from synology_site.docker_remote import read_system_load

    load = read_system_load(UptimeSSH())

    assert load.load1 == 1.50
    assert load.load5 == 2.25
    assert load.load15 == 0.75


def test_read_system_load_parses_synology_uptime_with_io_cpu_suffix() -> None:
    class UptimeSSH(FakeSSH):
        def run(self, command, *, check=False, timeout=None):  # noqa: ANN001, ANN201
            if command == "uptime":
                return RemoteCommandResult(
                    command,
                    0,
                    "11:41:51 up 3 days,  4:14,  0 users,  load average: 44.53, 63.59, 44.40 "
                    "[IO: 43.56, 62.65, 43.50 CPU: 0.98, 0.94, 0.90]\n",
                    "",
                )
            return super().run(command, check=check, timeout=timeout)

    from synology_site.docker_remote import read_system_load

    load = read_system_load(UptimeSSH())

    assert load.load1 == 44.53
    assert load.load5 == 63.59
    assert load.load15 == 44.40


def test_read_system_load_raises_on_unparseable_output() -> None:
    from synology_site.errors import SynologySiteError

    class UptimeSSH(FakeSSH):
        def run(self, command, *, check=False, timeout=None):  # noqa: ANN001, ANN201
            if command == "uptime":
                return RemoteCommandResult(command, 0, "nonsense\n", "")
            return super().run(command, check=check, timeout=timeout)

    from synology_site.docker_remote import read_system_load

    try:
        read_system_load(UptimeSSH())
        raise AssertionError("expected SynologySiteError")
    except SynologySiteError:
        pass


def test_read_memory_info_parses_free_output() -> None:
    class FreeSSH(FakeSSH):
        def run(self, command, *, check=False, timeout=None):  # noqa: ANN001, ANN201
            if command == "free -m":
                free_output = (
                    "          total   used   free  shared  buff/cache  available\n"
                    "Mem:       7894   3282    346     253        4265       3553\n"
                    "Swap:      2047   1876    171\n"
                )
                return RemoteCommandResult(command, 0, free_output, "")
            return super().run(command, check=check, timeout=timeout)

    from synology_site.docker_remote import read_memory_info

    mem = read_memory_info(FreeSSH())

    assert mem.total_mb == 7894
    assert mem.available_mb == 3553
    assert mem.swap_total_mb == 2047
    assert mem.swap_used_mb == 1876
    assert round(mem.swap_percent, 1) == 91.6


def test_compose_services_passes_explicit_file_flag() -> None:
    class ServicesSSH(FakeSSH):
        def run(self, command, *, check=False, timeout=None):  # noqa: ANN001, ANN201
            if "config --services" in command:
                self.commands.append(command)
                return RemoteCommandResult(command, 0, "web\nworker\n\n", "")
            return super().run(command, check=check, timeout=timeout)

    from synology_site.docker_remote import compose_services

    fake = ServicesSSH()
    services = compose_services(
        fake,
        "docker compose",
        "/volume1/docker/admin-reslk-com/repo/infra/admin",
        compose_file="docker-compose.admin.yml",
    )

    assert services == ["web", "worker"]
    assert "-f docker-compose.admin.yml" in fake.commands[-1]
    assert "cd /volume1/docker/admin-reslk-com/repo/infra/admin" in fake.commands[-1]
