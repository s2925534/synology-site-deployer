from __future__ import annotations

from synology_site.commands.ensure_network import ensure_network
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
    def __init__(self, *, network_exists: bool) -> None:
        self.network_exists = network_exists
        self.commands: list[str] = []

    def __enter__(self) -> FakeSSH:
        return self

    def __exit__(self, *_exc: object) -> None:
        pass

    def run(self, command: str, *, check: bool = False, timeout: int | None = None):
        del timeout
        self.commands.append(command)
        exit_code = 0
        stdout = ""
        if command == "command -v docker":
            stdout = "docker\n"
        elif command.startswith("docker network inspect"):
            exit_code = 0 if self.network_exists else 1
        result = RemoteCommandResult(command, exit_code, stdout, "")
        if check and not result.ok:
            raise SynologySiteError("command failed")
        return result


def test_ensure_network_creates_when_missing() -> None:
    fake = FakeSSH(network_exists=False)

    created = ensure_network(
        "shared-services",
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
    )

    assert created is True
    assert any(c.startswith("docker network create") for c in fake.commands)


def test_ensure_network_is_idempotent_when_already_present() -> None:
    fake = FakeSSH(network_exists=True)

    created = ensure_network(
        "shared-services",
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
    )

    assert created is False
    assert not any(c.startswith("docker network create") for c in fake.commands)
