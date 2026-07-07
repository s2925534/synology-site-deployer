from __future__ import annotations

import json
from dataclasses import replace

import pytest

from synology_site.commands.update import update_site
from synology_site.config import Settings
from synology_site.errors import SynologySiteError
from synology_site.nas.target import NasTarget
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


class FakeResponse:
    status_code = 200


class FakeSSH:
    def __init__(
        self,
        *,
        project_exists: bool = True,
        pull_ok: bool = True,
        marker: dict[str, object] | None = None,
    ) -> None:
        self.project_exists = project_exists
        self.pull_ok = pull_ok
        self.marker = marker or {
            "domain": "app.example.com",
            "slug": "app-example-com",
            "framework": "flask",
            "port": 5050,
            "container": "app-example-com",
        }
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
        exit_code = 0
        stdout = ""
        if command == "command -v docker":
            stdout = "docker\n"
        elif command == "test -d /volume1/docker/app-example-com":
            exit_code = 0 if self.project_exists else 1
        elif command == "cat /volume1/docker/app-example-com/.synology-site.json":
            stdout = json.dumps(self.marker)
        elif command.endswith("pull"):
            exit_code = 0 if self.pull_ok else 1
        elif command == "docker inspect -f '{{.State.Running}}' app-example-com":
            stdout = "true\n"
        result = RemoteCommandResult(command, exit_code, stdout, "")
        if check and not result.ok:
            raise SynologySiteError("command failed")
        return result


def test_update_site_pulls_and_restarts_create_site_with_health_check() -> None:
    fake = FakeSSH()
    health_urls: list[str] = []

    def health_get(url: str, timeout: int) -> FakeResponse:
        del timeout
        health_urls.append(url)
        return FakeResponse()

    result = update_site(
        "app.example.com",
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
        health_get=health_get,
    )

    assert result.project_path == "/volume1/docker/app-example-com"
    assert result.compose_file == "docker-compose.yml"
    assert result.pulled is True
    assert result.built is False
    assert result.container_name == "app-example-com"
    assert result.health_url == "http://192.0.2.10:5050/health"
    assert (
        "cd /volume1/docker/app-example-com && docker compose -f docker-compose.yml pull"
        in fake.commands
    )
    assert (
        "cd /volume1/docker/app-example-com && docker compose -f docker-compose.yml up -d"
        in fake.commands
    )
    assert health_urls == ["http://192.0.2.10:5050/health"]


def test_update_site_uses_deploy_marker_compose_file_without_default_health() -> None:
    fake = FakeSSH(
        marker={
            "mode": "deploy",
            "domain": "app.example.com",
            "slug": "app-example-com",
            "port": 5050,
            "compose_file": "repo/infra/web/docker-compose.web.yml",
        }
    )

    result = update_site(
        "app.example.com",
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
    )

    assert result.compose_file == "repo/infra/web/docker-compose.web.yml"
    assert result.health_url is None
    assert (
        "cd /volume1/docker/app-example-com && docker compose -f "
        "repo/infra/web/docker-compose.web.yml up -d"
    ) in fake.commands


def test_update_site_falls_back_to_build_when_pull_fails() -> None:
    fake = FakeSSH(pull_ok=False)

    result = update_site(
        "app.example.com",
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert result.pulled is False
    assert result.built is True
    assert (
        "cd /volume1/docker/app-example-com && docker compose -f docker-compose.yml "
        "up -d --build"
    ) in fake.commands


def test_update_site_accepts_explicit_health_and_container_for_deploy_marker() -> None:
    fake = FakeSSH(
        marker={
            "mode": "deploy",
            "domain": "app.example.com",
            "slug": "app-example-com",
            "port": 5050,
            "compose_file": "docker-compose.yml",
        }
    )
    health_urls: list[str] = []

    def health_get(url: str, timeout: int) -> FakeResponse:
        del timeout
        health_urls.append(url)
        return FakeResponse()

    result = update_site(
        "app.example.com",
        settings=settings(),
        health_path="/ready",
        container_name="app-example-com",
        ssh_factory=lambda _settings, _password: fake,
        health_get=health_get,
    )

    assert result.health_url == "http://192.0.2.10:5050/ready"
    assert "docker inspect -f '{{.State.Running}}' app-example-com" in fake.commands
    assert health_urls == ["http://192.0.2.10:5050/ready"]


def test_update_site_dry_run_skips_update_commands() -> None:
    fake = FakeSSH()

    result = update_site(
        "app.example.com",
        settings=settings(),
        dry_run=True,
        ssh_factory=lambda _settings, _password: fake,
    )

    assert result.project_path == "/volume1/docker/app-example-com"
    assert not any(command.endswith(" up -d") for command in fake.commands)
    assert not any(command.endswith(" pull") for command in fake.commands)


def test_update_site_requires_existing_project_folder() -> None:
    fake = FakeSSH(project_exists=False)

    with pytest.raises(SynologySiteError, match="not found"):
        update_site(
            "app.example.com",
            settings=settings(),
            ssh_factory=lambda _settings, _password: fake,
        )


def test_update_passes_cloudflare_access_ssh_settings_from_workspace() -> None:
    fake = FakeSSH()
    captured_settings: list[Settings] = []

    def capturing_ssh_factory(passed_settings: Settings, _password: object) -> FakeSSH:
        captured_settings.append(passed_settings)
        return fake

    clienta_target = NasTarget(
        name="clienta",
        host="192.0.2.50",
        port=22,
        user="clienta-deploy",
        ssh_key_path=None,
        ssh_password="clienta-secret",
        docker_root="/volume1/docker",
        local_base_url_host="192.0.2.10",
        default_start_port=5050,
        default_end_port=5999,
        ssh_access_hostname="nas-ssh.example.com",
        ssh_access_local_port=9210,
    )

    update_site(
        "app.example.com",
        settings=replace(settings(), nas_targets=(clienta_target,)),
        workspace="clienta",
        ssh_factory=capturing_ssh_factory,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert captured_settings[0].nas_host == "192.0.2.50"
    assert captured_settings[0].ssh_access_hostname == "nas-ssh.example.com"
    assert captured_settings[0].ssh_access_local_port == 9210
