from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from synology_site.commands.bootstrap_mariadb import bootstrap_mariadb
from synology_site.config import Settings
from synology_site.database.shared_mariadb import SHARED_MARIADB_CONTAINER, SHARED_MARIADB_NETWORK
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
    def __init__(self, *, project_exists: bool = False, network_exists: bool = False) -> None:
        self.project_exists = project_exists
        self.network_exists = network_exists
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
        elif command == "docker ps --format '{{.Names}}'":
            stdout = "\n"
        elif command.startswith("docker network inspect"):
            exit_code = 0 if self.network_exists else 1
        elif command == f"test -e /volume1/docker/{SHARED_MARIADB_CONTAINER}":
            exit_code = 0 if self.project_exists else 1
        elif command.startswith("docker inspect -f '{{.State.Running}}'"):
            stdout = "true\n"
        result = RemoteCommandResult(command, exit_code, stdout, "")
        if check and not result.ok:
            raise SynologySiteError("command failed")
        return result

    def upload_text(self, remote_path: str, content: str) -> None:
        self.uploads[remote_path] = content


def test_bootstrap_mariadb_deploys_shared_instance(tmp_path: Path) -> None:
    fake = FakeSSH()

    result = bootstrap_mariadb(
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
        secrets_dir=tmp_path,
    )

    assert result.project_path == f"/volume1/docker/{SHARED_MARIADB_CONTAINER}"
    assert result.container_name == SHARED_MARIADB_CONTAINER
    assert result.network_name == SHARED_MARIADB_NETWORK
    assert result.secrets_file == str(tmp_path / "mariadb.env")
    assert any("docker network create" in c for c in fake.commands)

    compose_path = f"/volume1/docker/{SHARED_MARIADB_CONTAINER}/docker-compose.yml"
    compose = yaml.safe_load(fake.uploads[compose_path])
    service = compose["services"][SHARED_MARIADB_CONTAINER]
    assert service["image"] == "mariadb:11"
    assert "ports" not in service
    assert service["networks"] == [SHARED_MARIADB_NETWORK]
    assert compose["networks"][SHARED_MARIADB_NETWORK]["external"] is True

    env = fake.uploads[f"/volume1/docker/{SHARED_MARIADB_CONTAINER}/.env"]
    assert env.startswith("MARIADB_ROOT_PASSWORD=")
    assert "MARIADB_DATABASE" not in env
    assert (tmp_path / "mariadb.env").read_text(encoding="utf-8") == env


def test_bootstrap_mariadb_reuses_existing_network(tmp_path: Path) -> None:
    fake = FakeSSH(network_exists=True)

    bootstrap_mariadb(
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
        secrets_dir=tmp_path,
    )

    assert not any("docker network create" in c for c in fake.commands)


def test_bootstrap_mariadb_dry_run_skips_remote_and_local_writes(tmp_path: Path) -> None:
    fake = FakeSSH()

    result = bootstrap_mariadb(
        settings=settings(),
        dry_run=True,
        ssh_factory=lambda _settings, _password: fake,
        secrets_dir=tmp_path,
    )

    assert result.secrets_file == ""
    assert fake.uploads == {}
    assert fake.commands == []
    assert list(tmp_path.iterdir()) == []


def test_bootstrap_mariadb_refuses_existing_project_without_force(tmp_path: Path) -> None:
    fake = FakeSSH(project_exists=True)

    with pytest.raises(SynologySiteError, match="already exists"):
        bootstrap_mariadb(
            settings=settings(),
            ssh_factory=lambda _settings, _password: fake,
            secrets_dir=tmp_path,
        )


def test_bootstrap_mariadb_force_overwrites_existing_project(tmp_path: Path) -> None:
    fake = FakeSSH(project_exists=True)

    result = bootstrap_mariadb(
        settings=settings(),
        force=True,
        ssh_factory=lambda _settings, _password: fake,
        secrets_dir=tmp_path,
    )

    assert result.project_path == f"/volume1/docker/{SHARED_MARIADB_CONTAINER}"
    assert any("down" in command for command in fake.commands)
    assert any(
        command == f"rm -rf /volume1/docker/{SHARED_MARIADB_CONTAINER}"
        for command in fake.commands
    )
