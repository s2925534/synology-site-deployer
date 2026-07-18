from __future__ import annotations

import json

from synology_site.commands.doctor import (
    check_resources,
    expected_working_dir,
    find_missing_restart_policy,
    find_never_started_sites,
    find_project_name_collisions,
    run_doctor,
)
from synology_site.config import Settings
from synology_site.docker_remote import ContainerInfo, MemoryInfo, SystemLoad
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


def test_expected_working_dir_defaults_to_slug_directory() -> None:
    marker = {"slug": "health-veloso-dev"}

    assert expected_working_dir("/volume1/docker", marker) == "/volume1/docker/health-veloso-dev"


def test_expected_working_dir_resolves_nested_compose_file() -> None:
    marker = {"slug": "addr-systemsnotsilos-com", "compose_file": "repo/docker-compose.yml"}

    assert (
        expected_working_dir("/volume1/docker", marker)
        == "/volume1/docker/addr-systemsnotsilos-com/repo"
    )


def test_expected_working_dir_resolves_deeply_nested_compose_file() -> None:
    marker = {
        "slug": "admin-reslk-com",
        "compose_file": "repo/infra/admin/docker-compose.admin.yml",
    }

    assert (
        expected_working_dir("/volume1/docker", marker)
        == "/volume1/docker/admin-reslk-com/repo/infra/admin"
    )


def test_find_never_started_sites_flags_markers_with_no_matching_container() -> None:
    markers = [
        {"slug": "running-site", "domain": "running.example.com"},
        {"slug": "ghost-site", "domain": "ghost.example.com"},
    ]
    containers = [
        ContainerInfo(
            name="running-site",
            project="running-site",
            working_dir="/volume1/docker/running-site",
            status="Up 2 minutes",
            restart_policy="unless-stopped",
        )
    ]

    never_started = find_never_started_sites(markers, containers, "/volume1/docker")

    assert [marker["domain"] for marker in never_started] == ["ghost.example.com"]


def test_find_never_started_sites_matches_nested_compose_working_dir() -> None:
    markers = [
        {"slug": "addr-systemsnotsilos-com", "compose_file": "repo/docker-compose.yml"},
    ]
    containers = [
        ContainerInfo(
            name="au-address-opensearch",
            project="repo",
            working_dir="/volume1/docker/addr-systemsnotsilos-com/repo",
            status="Up",
            restart_policy="unless-stopped",
        )
    ]

    assert find_never_started_sites(markers, containers, "/volume1/docker") == []


def test_find_missing_restart_policy_flags_containers_without_auto_restart() -> None:
    containers = [
        ContainerInfo("good", "p", "/d/good", "Up", "unless-stopped"),
        ContainerInfo("bad", "p", "/d/bad", "Exited (137) 11 hours ago", ""),
    ]

    missing = find_missing_restart_policy(containers)

    assert [container.name for container in missing] == ["bad"]


def test_find_project_name_collisions_detects_shared_default_project_name() -> None:
    policy = "unless-stopped"
    containers = [
        ContainerInfo(
            "corroborly-api", "repo", "/volume1/docker/app-corroborly-com/repo", "Up", policy
        ),
        ContainerInfo(
            "corroborly-site", "repo", "/volume1/docker/corroborly-com/repo", "Up", policy
        ),
        ContainerInfo("url-shortener", "repo", "/volume1/docker/s-reslk-com/repo", "Up", policy),
        ContainerInfo("lofas-app", "lofas-org", "/volume1/docker/lofas-org", "Up", policy),
    ]

    collisions = find_project_name_collisions(containers)

    assert set(collisions.keys()) == {"repo"}
    assert len(collisions["repo"]) == 3


def test_check_resources_flags_high_load_and_swap() -> None:
    findings = check_resources(
        SystemLoad(load1=44.5, load5=30.0, load15=20.0),
        MemoryInfo(total_mb=7894, available_mb=1300, swap_total_mb=2047, swap_used_mb=1800),
    )

    categories = {severity for severity, _ in findings}
    assert "critical" in categories
    assert any("load average" in detail for _severity, detail in findings)
    assert any("swap" in detail for _severity, detail in findings)


def test_check_resources_reports_nothing_when_healthy() -> None:
    findings = check_resources(
        SystemLoad(load1=2.5, load5=3.0, load15=2.0),
        MemoryInfo(total_mb=7894, available_mb=4500, swap_total_mb=2047, swap_used_mb=100),
    )

    assert findings == []


class FakeSSH:
    def __init__(
        self,
        markers: list[dict[str, object]],
        containers_output: str,
        *,
        inspect_output: str = "",
        uptime_output: str = "up 1 day, load average: 2.0, 2.0, 2.0\n",
        free_output: str = (
            "Mem:  7894  2000  3000  100  2000  5000\nSwap: 2047  100  1947\n"
        ),
    ) -> None:
        self.markers = markers
        self.containers_output = containers_output
        self.inspect_output = inspect_output
        self.uptime_output = uptime_output
        self.free_output = free_output

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
        if command.startswith("docker ps -a --format"):
            return RemoteCommandResult(command, 0, self.containers_output, "")
        if command.startswith("docker inspect --format"):
            return RemoteCommandResult(command, 0, self.inspect_output, "")
        if command == "uptime":
            return RemoteCommandResult(command, 0, self.uptime_output, "")
        if command == "free -m":
            return RemoteCommandResult(command, 0, self.free_output, "")
        result = RemoteCommandResult(command, 1, "", "unexpected")
        if check and not result.ok:
            raise SynologySiteError(f"command failed: {command}")
        return result


def test_run_doctor_reports_never_started_site_and_missing_restart_policy() -> None:
    fake = FakeSSH(
        markers=[{"slug": "ghost-site", "domain": "ghost.example.com"}],
        containers_output="other\tother\t/volume1/docker/other\tExited (0) 1 hour ago\n",
        inspect_output="/other\t\n",
    )

    findings = run_doctor(
        settings(),
        (settings().default_nas_target,),
        ssh_factory=lambda _settings, _password: fake,
    )

    categories = {finding.category for finding in findings}
    assert "never-started" in categories
    assert "no-restart-policy" in categories
    assert any("ghost.example.com" in finding.summary for finding in findings)
    assert any("other" in finding.summary for finding in findings)


def test_run_doctor_reports_resource_pressure() -> None:
    fake = FakeSSH(
        markers=[],
        containers_output="",
        uptime_output="load average: 60.0, 40.0, 30.0\n",
        free_output="Mem:  7894  6000  200  100  1000  1300\nSwap: 2047  1800  247\n",
    )

    findings = run_doctor(
        settings(),
        (settings().default_nas_target,),
        ssh_factory=lambda _settings, _password: fake,
    )

    assert any(
        finding.category == "resources" and finding.severity == "critical" for finding in findings
    )


def test_run_doctor_reports_clean_fleet_as_no_findings() -> None:
    fake = FakeSSH(
        markers=[{"slug": "good-site", "domain": "good.example.com"}],
        containers_output="good-site\tgood-site\t/volume1/docker/good-site\tUp 2 minutes\n",
        inspect_output="/good-site\tunless-stopped\n",
    )

    findings = run_doctor(
        settings(),
        (settings().default_nas_target,),
        ssh_factory=lambda _settings, _password: fake,
    )

    assert findings == []


def test_run_doctor_keeps_going_when_a_target_is_unreachable() -> None:
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

    findings = run_doctor(
        settings(),
        (settings().default_nas_target, other),
        ssh_factory=ssh_factory,
    )

    assert any(
        finding.target_name == "other" and finding.category == "connectivity"
        for finding in findings
    )
