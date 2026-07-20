from __future__ import annotations

from synology_site.commands.stop import stop_site
from synology_site.config import Settings
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
    def __init__(self) -> None:
        self.commands: list[str] = []

    def __enter__(self) -> FakeSSH:
        return self

    def __exit__(self, *_exc: object) -> None:
        pass

    def run(self, command: str, *, check: bool = False, timeout: int | None = None):
        del check, timeout
        self.commands.append(command)
        stdout = "docker\n" if command == "command -v docker" else ""
        return RemoteCommandResult(command, 0, stdout, "")


def test_stop_site_plain_down() -> None:
    fake = FakeSSH()
    stop_site("app.example.com", settings=settings(), ssh_factory=lambda _s, _p: fake)

    assert "cd /volume1/docker/app-example-com && docker compose down" in fake.commands


def test_stop_site_with_remove_orphans() -> None:
    fake = FakeSSH()
    stop_site(
        "app.example.com",
        settings=settings(),
        remove_orphans=True,
        ssh_factory=lambda _s, _p: fake,
    )

    assert (
        "cd /volume1/docker/app-example-com && docker compose down --remove-orphans"
        in fake.commands
    )
