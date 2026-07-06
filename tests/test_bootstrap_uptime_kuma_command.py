from __future__ import annotations

import pytest
import yaml

from synology_site.commands.bootstrap_uptime_kuma import bootstrap_uptime_kuma
from synology_site.config import Settings
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


class FakeSSH:
    def __init__(self, *, project_exists: bool = False) -> None:
        self.project_exists = project_exists
        self.commands: list[str] = []
        self.uploads: dict[str, str] = {}

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
        exit_code = 0
        stdout = ""
        if command == "command -v docker":
            stdout = "docker\n"
        elif command.startswith("test -e /volume1/docker/"):
            exit_code = 0 if self.project_exists else 1
        elif command.startswith("docker inspect -f '{{.State.Running}}'"):
            stdout = "true\n"
        result = RemoteCommandResult(command, exit_code, stdout, "")
        if check and not result.ok:
            raise SynologySiteError("command failed")
        return result

    def upload_text(self, remote_path: str, content: str) -> None:
        self.uploads[remote_path] = content


def test_bootstrap_uptime_kuma_deploys_single_container() -> None:
    fake = FakeSSH()

    result = bootstrap_uptime_kuma(
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
    )

    assert result.project_path == "/volume1/docker/uptime-kuma"
    assert result.container_name == "uptime-kuma"
    assert result.port == 5050
    assert result.local_url == "http://192.0.2.10:5050"

    compose = yaml.safe_load(fake.uploads["/volume1/docker/uptime-kuma/docker-compose.yml"])
    service = compose["services"]["uptime-kuma"]
    assert service["image"] == "louislam/uptime-kuma:1"
    assert service["ports"] == ["5050:3001"]
    assert service["volumes"] == ["uptime-kuma-data:/app/data"]
    assert "docker inspect -f '{{.State.Running}}' uptime-kuma" in fake.commands


def test_bootstrap_uptime_kuma_dry_run_skips_remote_writes() -> None:
    fake = FakeSSH()

    result = bootstrap_uptime_kuma(
        settings=settings(),
        dry_run=True,
        ssh_factory=lambda _settings, _password: fake,
    )

    assert result.port == 5050
    assert fake.uploads == {}


def test_bootstrap_uptime_kuma_refuses_existing_project_without_force() -> None:
    fake = FakeSSH(project_exists=True)

    with pytest.raises(SynologySiteError, match="already exists"):
        bootstrap_uptime_kuma(
            settings=settings(),
            ssh_factory=lambda _settings, _password: fake,
        )


def test_bootstrap_uptime_kuma_force_overwrites_existing_project() -> None:
    fake = FakeSSH(project_exists=True)

    result = bootstrap_uptime_kuma(
        settings=settings(),
        force=True,
        ssh_factory=lambda _settings, _password: fake,
    )

    assert result.project_path == "/volume1/docker/uptime-kuma"
    assert any("down" in command for command in fake.commands)


def test_bootstrap_uptime_kuma_custom_project_dir_name() -> None:
    fake = FakeSSH()

    result = bootstrap_uptime_kuma(
        settings=settings(),
        project_dir_name="status",
        ssh_factory=lambda _settings, _password: fake,
    )

    assert result.project_path == "/volume1/docker/status"
    assert result.container_name == "status"
    assert "/volume1/docker/status/docker-compose.yml" in fake.uploads
