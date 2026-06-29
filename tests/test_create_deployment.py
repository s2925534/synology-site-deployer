from __future__ import annotations

import pytest

from synology_site.commands.create import create_site
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


class FakeResponse:
    status_code = 200


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
        elif command == "test -e /volume1/docker/demo-example-com":
            exit_code = 0 if self.project_exists else 1
        elif command in {
            "docker inspect -f '{{.State.Running}}' demo-example-com",
            "docker inspect -f '{{.State.Running}}' demo-example-com-db",
        }:
            stdout = "true\n"
        elif command == "docker ps --format '{{.Ports}}'":
            stdout = "0.0.0.0:5050->5000/tcp\n"
        result = RemoteCommandResult(command, exit_code, stdout, "")
        if check and not result.ok:
            raise SynologySiteError("command failed")
        return result

    def upload_text(self, remote_path: str, content: str) -> None:
        self.uploads[remote_path] = content


def test_create_site_deploys_flask_without_db() -> None:
    fake = FakeSSH()

    result = create_site(
        "demo.example.com",
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert result.port == 5051
    assert result.local_url == "http://192.0.2.10:5051"
    assert "/volume1/docker/demo-example-com/app/app.py" in fake.uploads
    assert "/volume1/docker/demo-example-com/docker-compose.yml" in fake.uploads
    assert "/volume1/docker/demo-example-com/docs/README.md" in fake.uploads
    assert "cd /volume1/docker/demo-example-com && docker compose up -d --build" in fake.commands


def test_create_site_dry_run_skips_remote_writes_and_start() -> None:
    fake = FakeSSH()

    result = create_site(
        "demo.example.com",
        settings=settings(),
        dry_run=True,
        ssh_factory=lambda _settings, _password: fake,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert result.uploaded_files
    assert fake.uploads == {}
    assert not any("up -d --build" in command for command in fake.commands)


def test_create_site_refuses_existing_project_without_force() -> None:
    fake = FakeSSH(project_exists=True)

    with pytest.raises(SynologySiteError, match="already exists"):
        create_site(
            "demo.example.com",
            settings=settings(),
            ssh_factory=lambda _settings, _password: fake,
            health_get=lambda _url, timeout: FakeResponse(),
        )


def test_create_site_deploys_flask_with_db() -> None:
    fake = FakeSSH()
    health_urls: list[str] = []

    def health_get(url: str, timeout: int) -> FakeResponse:
        del timeout
        health_urls.append(url)
        return FakeResponse()

    result = create_site(
        "demo.example.com",
        settings=settings(),
        db_mode="container",
        ssh_factory=lambda _settings, _password: fake,
        health_get=health_get,
    )

    assert result.db_enabled is True
    assert result.db_health_url == "http://192.0.2.10:5051/db-health"
    assert "/volume1/docker/demo-example-com/app/.env" in fake.uploads
    assert "/volume1/docker/demo-example-com/docs/DATABASE.md" in fake.uploads
    assert "chmod 600 /volume1/docker/demo-example-com/app/.env" in fake.commands
    assert "chmod 600 /volume1/docker/demo-example-com/docs/DATABASE.md" in fake.commands
    assert "http://192.0.2.10:5051/health" in health_urls
    assert "http://192.0.2.10:5051/db-health" in health_urls
