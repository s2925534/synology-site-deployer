from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from synology_site.commands.bootstrap_vaultwarden import bootstrap_vaultwarden
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


def test_bootstrap_vaultwarden_deploys_single_container(tmp_path: Path) -> None:
    fake = FakeSSH()

    result = bootstrap_vaultwarden(
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
        secrets_dir=tmp_path,
    )

    assert result.project_path == "/volume1/docker/vaultwarden"
    assert result.container_name == "vaultwarden"
    assert result.port == 5050
    assert result.local_url == "http://192.0.2.10:5050"
    assert result.secrets_file == str(tmp_path / "vaultwarden.env")

    compose = yaml.safe_load(fake.uploads["/volume1/docker/vaultwarden/docker-compose.yml"])
    service = compose["services"]["vaultwarden"]
    assert service["image"] == "vaultwarden/server:latest"
    assert service["ports"] == ["5050:80"]
    assert service["env_file"] == [".env"]
    assert service["volumes"] == ["vaultwarden-data:/data"]
    assert "docker inspect -f '{{.State.Running}}' vaultwarden" in fake.commands

    remote_env = fake.uploads["/volume1/docker/vaultwarden/.env"]
    assert "ADMIN_TOKEN=" in remote_env
    assert "SIGNUPS_ALLOWED=false" in remote_env
    assert "INVITATIONS_ALLOWED=true" in remote_env
    assert "DOMAIN=" not in remote_env
    assert (tmp_path / "vaultwarden.env").read_text(encoding="utf-8") == remote_env


def test_bootstrap_vaultwarden_sets_public_hostname_env(tmp_path: Path) -> None:
    fake = FakeSSH()

    result = bootstrap_vaultwarden(
        settings=settings(),
        hostname="vault.example.com",
        ssh_factory=lambda _settings, _password: fake,
        secrets_dir=tmp_path,
    )

    assert result.public_url == "https://vault.example.com"
    remote_env = fake.uploads["/volume1/docker/vaultwarden/.env"]
    assert "DOMAIN=https://vault.example.com" in remote_env


def test_bootstrap_vaultwarden_can_allow_signups(tmp_path: Path) -> None:
    fake = FakeSSH()

    bootstrap_vaultwarden(
        settings=settings(),
        signups_allowed=True,
        ssh_factory=lambda _settings, _password: fake,
        secrets_dir=tmp_path,
    )

    remote_env = fake.uploads["/volume1/docker/vaultwarden/.env"]
    assert "SIGNUPS_ALLOWED=true" in remote_env


def test_bootstrap_vaultwarden_dry_run_skips_remote_and_local_writes(tmp_path: Path) -> None:
    fake = FakeSSH()

    result = bootstrap_vaultwarden(
        settings=settings(),
        dry_run=True,
        ssh_factory=lambda _settings, _password: fake,
        secrets_dir=tmp_path,
    )

    assert result.port == 5050
    assert result.secrets_file == ""
    assert fake.uploads == {}
    assert list(tmp_path.iterdir()) == []


def test_bootstrap_vaultwarden_refuses_existing_project_without_force(tmp_path: Path) -> None:
    fake = FakeSSH(project_exists=True)

    with pytest.raises(SynologySiteError, match="already exists"):
        bootstrap_vaultwarden(
            settings=settings(),
            ssh_factory=lambda _settings, _password: fake,
            secrets_dir=tmp_path,
        )


def test_bootstrap_vaultwarden_force_overwrites_existing_project(tmp_path: Path) -> None:
    fake = FakeSSH(project_exists=True)

    result = bootstrap_vaultwarden(
        settings=settings(),
        force=True,
        ssh_factory=lambda _settings, _password: fake,
        secrets_dir=tmp_path,
    )

    assert result.project_path == "/volume1/docker/vaultwarden"
    assert any("down" in command for command in fake.commands)
    assert any(command == "rm -rf /volume1/docker/vaultwarden" for command in fake.commands)


def test_bootstrap_vaultwarden_custom_project_dir_name(tmp_path: Path) -> None:
    fake = FakeSSH()

    result = bootstrap_vaultwarden(
        settings=settings(),
        project_dir_name="passwords",
        ssh_factory=lambda _settings, _password: fake,
        secrets_dir=tmp_path,
    )

    assert result.project_path == "/volume1/docker/passwords"
    assert result.container_name == "passwords"
    assert "/volume1/docker/passwords/docker-compose.yml" in fake.uploads
    assert result.secrets_file == str(tmp_path / "passwords.env")
