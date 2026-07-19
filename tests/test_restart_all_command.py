from __future__ import annotations

import json

from synology_site.commands.restart_all import (
    ProjectPlan,
    discover_projects,
    filter_projects,
    restart_all,
)
from synology_site.config import Settings
from synology_site.docker_remote import ContainerInfo
from synology_site.errors import SynologySiteError
from synology_site.ssh_client import RemoteCommandResult


def settings() -> Settings:
    return Settings(
        nas_host="192.0.2.10",
        nas_port=22,
        nas_user="deploy",
        nas_docker_root="/volume1/docker",
        nas_ssh_key_path=None,
        nas_ssh_password="secret",
        local_base_url_host="192.0.2.10",
        default_start_port=5050,
        default_end_port=5999,
        default_framework="flask",
        restart_policy="unless-stopped",
        cf_api_token=None,
        cf_account_id=None,
        cf_zone_id=None,
        cf_zone_domain="example.com",
        cf_tunnel_id=None,
        cf_tunnel_name="my-nas-tunnel",
        db_mode="none",
        db_type="mariadb",
        db_image="mariadb:11",
        db_password_length=32,
        db_publish_port=False,
        db_host_port=None,
        allow_overwrite=False,
        dry_run=False,
    )


def test_discover_projects_includes_never_started_marker() -> None:
    markers = [{"slug": "ghost-site", "domain": "ghost.example.com"}]
    containers = [
        ContainerInfo("web", "existing", "/volume1/docker/existing", "Up", "unless-stopped"),
    ]

    plans = discover_projects(markers, containers, "/volume1/docker")

    labels = {plan.label for plan in plans}
    assert "ghost.example.com" in labels
    assert "existing" in labels


def test_discover_projects_uses_marker_compose_file_basename() -> None:
    markers = [
        {
            "slug": "admin-reslk-com",
            "domain": "admin.reslk.com",
            "compose_file": "repo/infra/admin/docker-compose.admin.yml",
        }
    ]

    plans = discover_projects(markers, [], "/volume1/docker")

    plan = plans[0]
    assert plan.working_dir == "/volume1/docker/admin-reslk-com/repo/infra/admin"
    assert plan.compose_file == "docker-compose.admin.yml"


def test_discover_projects_defaults_unmarked_project_to_plain_compose_filename() -> None:
    containers = [
        ContainerInfo(
            "supabase-db", "supabase", "/volume1/docker/supabase", "Up", "unless-stopped"
        ),
    ]

    plans = discover_projects([], containers, "/volume1/docker")

    assert plans[0].compose_file == "docker-compose.yml"
    assert plans[0].label == "supabase"


def test_filter_projects_matches_label_or_directory_basename() -> None:
    plans = [
        ProjectPlan("/volume1/docker/lofas-org", "docker-compose.yml", "lofas.org"),
        ProjectPlan("/volume1/docker/other", "docker-compose.yml", "other"),
    ]

    filtered = filter_projects(plans, ["lofas.org"])

    assert [plan.label for plan in filtered] == ["lofas.org"]


def test_filter_projects_returns_everything_when_only_not_given() -> None:
    plans = [ProjectPlan("/d", "docker-compose.yml", "x")]

    assert filter_projects(plans, None) == plans


class FakeSSH:
    def __init__(
        self,
        markers: list[dict[str, object]],
        containers_output: str,
        *,
        services_by_dir: dict[str, str] | None = None,
        load_sequence: list[str] | None = None,
        memory_sequence: list[str] | None = None,
    ) -> None:
        self.markers = markers
        self.containers_output = containers_output
        self.services_by_dir = services_by_dir or {}
        self.load_sequence = list(load_sequence or ["load average: 2.0, 1.0, 1.0\n"])
        self.memory_sequence = list(
            memory_sequence
            or [
                "              total        used        free      shared  buff/cache   available\n"
                "Mem:           8000        2000        4000         100        2000        6000\n"
                "Swap:          2000           0        2000\n"
            ]
        )
        self.commands: list[str] = []

    def __enter__(self) -> FakeSSH:
        return self

    def __exit__(self, *_exc: object) -> None:
        pass

    def run(
        self,
        command: str,
        *,
        check: bool = False,
        timeout: int | None = None,
    ) -> RemoteCommandResult:
        del timeout
        self.commands.append(command)
        result = self._respond(command)
        if check and not result.ok:
            raise SynologySiteError(f"command failed: {command}")
        return result

    def _respond(self, command: str) -> RemoteCommandResult:
        marker_paths = [
            f"/volume1/docker/site-{index}/.synology-site.json"
            for index in range(len(self.markers))
        ]
        if command.startswith("find "):
            return RemoteCommandResult(command, 0, "\n".join(marker_paths), "")
        for index, marker_path in enumerate(marker_paths):
            if command == f"cat {marker_path}":
                return RemoteCommandResult(command, 0, json.dumps(self.markers[index]), "")
        if command == "command -v docker":
            return RemoteCommandResult(command, 0, "docker\n", "")
        if command == "docker ps --format '{{.Names}}'":
            return RemoteCommandResult(command, 0, "", "")
        if command == "docker compose version":
            return RemoteCommandResult(command, 0, "Docker Compose version v2\n", "")
        if command.startswith("docker ps -a --format"):
            return RemoteCommandResult(command, 0, self.containers_output, "")
        if command.startswith("docker inspect --format"):
            return RemoteCommandResult(command, 0, "", "")
        if command == "uptime":
            if len(self.load_sequence) > 1:
                return RemoteCommandResult(command, 0, self.load_sequence.pop(0), "")
            return RemoteCommandResult(command, 0, self.load_sequence[0], "")
        if command == "free -m":
            if len(self.memory_sequence) > 1:
                return RemoteCommandResult(command, 0, self.memory_sequence.pop(0), "")
            return RemoteCommandResult(command, 0, self.memory_sequence[0], "")
        if "config --services" in command:
            for working_dir, services in self.services_by_dir.items():
                if f"cd {working_dir}" in command:
                    return RemoteCommandResult(command, 0, services, "")
            return RemoteCommandResult(command, 1, "", "no such directory")
        if " up -d " in command:
            return RemoteCommandResult(command, 0, "Container started\n", "")
        return RemoteCommandResult(command, 1, "", "unexpected")


def test_restart_all_starts_each_service_one_at_a_time_with_pauses() -> None:
    fake = FakeSSH(
        markers=[{"slug": "myproj", "domain": "myproj.example.com"}],
        containers_output="web\tmyproj\t/volume1/docker/myproj\tweb\tUp 2 minutes\n",
        services_by_dir={"/volume1/docker/myproj": "web\nworker\n"},
    )
    sleeps: list[float] = []

    steps = restart_all(
        settings(),
        (settings().default_nas_target,),
        ssh_factory=lambda _settings, _password: fake,
        stagger_seconds=7.5,
        sleep=sleeps.append,
    )

    ok_steps = [step for step in steps if step.ok]
    assert {step.service for step in ok_steps} == {"web", "worker"}
    assert sleeps == [7.5, 7.5]


def test_restart_all_aborts_remaining_work_when_load_is_too_high() -> None:
    fake = FakeSSH(
        markers=[],
        containers_output=(
            "web\tmyproj\t/volume1/docker/myproj\tweb\tUp 2 minutes\n"
            "web2\tother\t/volume1/docker/other\tweb\tUp 2 minutes\n"
        ),
        services_by_dir={
            "/volume1/docker/myproj": "web\n",
            "/volume1/docker/other": "web\n",
        },
        load_sequence=["load average: 44.0, 30.0, 20.0\n"],
    )

    steps = restart_all(
        settings(),
        (settings().default_nas_target,),
        ssh_factory=lambda _settings, _password: fake,
        max_load=20.0,
        sleep=lambda _seconds: None,
    )

    aborted = [step for step in steps if step.detail.startswith("aborted")]
    skipped = [step for step in steps if step.detail.startswith("skipped")]
    assert len(aborted) == 1
    assert len(skipped) == 1
    assert not any(" up -d " in command for command in fake.commands)


def test_restart_all_aborts_remaining_work_when_memory_is_too_high() -> None:
    fake = FakeSSH(
        markers=[],
        containers_output=(
            "web\tmyproj\t/volume1/docker/myproj\tweb\tUp 2 minutes\n"
            "web2\tother\t/volume1/docker/other\tweb\tUp 2 minutes\n"
        ),
        services_by_dir={
            "/volume1/docker/myproj": "web\n",
            "/volume1/docker/other": "web\n",
        },
        memory_sequence=[
            "              total        used        free      shared  buff/cache   available\n"
            "Mem:           8000        7300         200         100         400         700\n"
            "Swap:          2000           0        2000\n"
        ],
    )

    steps = restart_all(
        settings(),
        (settings().default_nas_target,),
        ssh_factory=lambda _settings, _password: fake,
        max_memory_percent=90.0,
        sleep=lambda _seconds: None,
    )

    aborted = [step for step in steps if step.detail.startswith("aborted")]
    skipped = [step for step in steps if step.detail.startswith("skipped")]
    assert len(aborted) == 1
    assert "memory usage" in aborted[0].detail
    assert len(skipped) == 1
    assert not any(" up -d " in command for command in fake.commands)


def test_restart_all_dry_run_reports_plan_without_running_compose() -> None:
    fake = FakeSSH(
        markers=[{"slug": "myproj", "domain": "myproj.example.com"}],
        containers_output="",
    )

    steps = restart_all(
        settings(),
        (settings().default_nas_target,),
        ssh_factory=lambda _settings, _password: fake,
        dry_run=True,
    )

    assert len(steps) == 1
    assert "[dry-run]" in steps[0].detail
    assert not any("config --services" in command for command in fake.commands)


def test_restart_all_only_filters_to_named_project() -> None:
    fake = FakeSSH(
        markers=[
            {"slug": "site-a", "domain": "a.example.com"},
            {"slug": "site-b", "domain": "b.example.com"},
        ],
        containers_output="",
        services_by_dir={
            "/volume1/docker/site-a": "web\n",
            "/volume1/docker/site-b": "web\n",
        },
    )

    steps = restart_all(
        settings(),
        (settings().default_nas_target,),
        ssh_factory=lambda _settings, _password: fake,
        only=["a.example.com"],
        sleep=lambda _seconds: None,
    )

    assert all("site-a" in step.working_dir for step in steps)


def test_restart_all_records_error_when_compose_file_missing() -> None:
    fake = FakeSSH(
        markers=[{"slug": "broken-site", "domain": "broken.example.com"}],
        containers_output="",
        services_by_dir={},
    )

    steps = restart_all(
        settings(),
        (settings().default_nas_target,),
        ssh_factory=lambda _settings, _password: fake,
        sleep=lambda _seconds: None,
    )

    assert len(steps) == 1
    assert steps[0].ok is False
    assert "could not read services" in steps[0].detail


def test_restart_all_keeps_going_when_a_target_is_unreachable() -> None:
    from dataclasses import dataclass

    from synology_site.nas.target import NasTarget

    @dataclass
    class UnreachableSSH:
        def __enter__(self) -> UnreachableSSH:
            raise SynologySiteError("connection refused")

        def __exit__(self, *_exc: object) -> None:
            pass

    other = NasTarget(
        name="other",
        host="203.0.113.5",
        port=22,
        user="deploy",
        ssh_key_path=None,
        ssh_password="secret",
        docker_root="/volume1/docker",
        local_base_url_host="203.0.113.5",
        default_start_port=5050,
        default_end_port=5999,
    )

    def ssh_factory(connection_settings: Settings, _password: str | None) -> object:
        if connection_settings.nas_host == "203.0.113.5":
            return UnreachableSSH()
        return FakeSSH(markers=[], containers_output="")

    steps = restart_all(
        settings(),
        (settings().default_nas_target, other),
        ssh_factory=ssh_factory,
        sleep=lambda _seconds: None,
    )

    assert any(step.target_name == "other" and not step.ok for step in steps)
