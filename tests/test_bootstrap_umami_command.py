from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from synology_site.commands.bootstrap_umami import bootstrap_umami
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


def test_bootstrap_umami_deploys_app_and_postgres(tmp_path: Path) -> None:
    fake = FakeSSH()

    result = bootstrap_umami(
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
        secrets_dir=tmp_path,
    )

    assert result.project_path == "/volume1/docker/umami"
    assert result.container_name == "umami"
    assert result.db_container_name == "umami-db"
    assert result.port == 5050
    assert result.local_url == "http://192.0.2.10:5050"
    assert result.secrets_file == str(tmp_path / "umami.env")

    compose = yaml.safe_load(fake.uploads["/volume1/docker/umami/docker-compose.yml"])
    service = compose["services"]["umami"]
    db = compose["services"]["db"]
    assert service["image"] == "ghcr.io/umami-software/umami:latest"
    assert service["ports"] == ["5050:3000"]
    assert service["env_file"] == [".env"]
    assert service["depends_on"]["db"]["condition"] == "service_healthy"
    assert db["image"] == "postgres:15-alpine"
    assert db["container_name"] == "umami-db"
    assert db["volumes"] == ["umami-db-data:/var/lib/postgresql/data"]
    assert "docker inspect -f '{{.State.Running}}' umami" in fake.commands
    assert "docker inspect -f '{{.State.Running}}' umami-db" in fake.commands

    remote_env = fake.uploads["/volume1/docker/umami/.env"]
    assert "POSTGRES_DB=umami" in remote_env
    assert "POSTGRES_USER=umami" in remote_env
    assert "POSTGRES_PASSWORD=" in remote_env
    assert "DATABASE_URL=postgresql://umami:" in remote_env
    assert "@db:5432/umami" in remote_env
    assert "APP_SECRET=" in remote_env
    assert (tmp_path / "umami.env").read_text(encoding="utf-8") == remote_env


def test_bootstrap_umami_dry_run_skips_remote_and_local_writes(tmp_path: Path) -> None:
    fake = FakeSSH()

    result = bootstrap_umami(
        settings=settings(),
        dry_run=True,
        ssh_factory=lambda _settings, _password: fake,
        secrets_dir=tmp_path,
    )

    assert result.port == 5050
    assert result.secrets_file == ""
    assert fake.uploads == {}
    assert list(tmp_path.iterdir()) == []


def test_bootstrap_umami_refuses_existing_project_without_force(tmp_path: Path) -> None:
    fake = FakeSSH(project_exists=True)

    with pytest.raises(SynologySiteError, match="already exists"):
        bootstrap_umami(
            settings=settings(),
            ssh_factory=lambda _settings, _password: fake,
            secrets_dir=tmp_path,
        )


def test_bootstrap_umami_force_overwrites_existing_project(tmp_path: Path) -> None:
    fake = FakeSSH(project_exists=True)

    result = bootstrap_umami(
        settings=settings(),
        force=True,
        ssh_factory=lambda _settings, _password: fake,
        secrets_dir=tmp_path,
    )

    assert result.project_path == "/volume1/docker/umami"
    assert any("down" in command for command in fake.commands)
    assert any(command == "rm -rf /volume1/docker/umami" for command in fake.commands)


def test_bootstrap_umami_custom_project_dir_name(tmp_path: Path) -> None:
    fake = FakeSSH()

    result = bootstrap_umami(
        settings=settings(),
        project_dir_name="analytics",
        ssh_factory=lambda _settings, _password: fake,
        secrets_dir=tmp_path,
    )

    assert result.project_path == "/volume1/docker/analytics"
    assert result.container_name == "analytics"
    assert result.db_container_name == "analytics-db"
    assert "/volume1/docker/analytics/docker-compose.yml" in fake.uploads
    assert result.secrets_file == str(tmp_path / "analytics.env")
