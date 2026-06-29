from __future__ import annotations

from synology_site.commands.tunnel_fix import (
    parse_cloudflared_containers,
    run_tunnel_fix_autostart,
)
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
    def __init__(self, output: str) -> None:
        self.output = output
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
        del check, timeout
        self.commands.append(command)
        stdout = self.output if command.startswith("docker ps -a") else ""
        return RemoteCommandResult(command, 0, stdout, "")


def test_parse_cloudflared_containers() -> None:
    containers = parse_cloudflared_containers(
        "cloudflared\tcloudflare/cloudflared:latest\tUp 2 hours\n"
        "app\tpython:3.11\tUp 1 hour\n"
    )

    assert len(containers) == 1
    assert containers[0].name == "cloudflared"
    assert containers[0].running is True


def test_tunnel_fix_updates_restart_policy() -> None:
    fake = FakeSSH("cloudflared\tcloudflare/cloudflared:latest\tUp 2 hours\n")

    run_tunnel_fix_autostart(settings(), ssh_factory=lambda _settings, _password: fake)

    assert "docker update --restart unless-stopped cloudflared" in fake.commands


def test_tunnel_fix_can_rename_random_container() -> None:
    fake = FakeSSH("clever_carver\tcloudflare/cloudflared:latest\tExited (0) 1 hour ago\n")

    run_tunnel_fix_autostart(
        settings(),
        ssh_factory=lambda _settings, _password: fake,
        rename_random=True,
    )

    assert "docker stop clever_carver" in fake.commands
    assert "docker rename clever_carver cloudflared" in fake.commands
    assert "docker update --restart unless-stopped cloudflared" in fake.commands
    assert "docker start cloudflared" in fake.commands
