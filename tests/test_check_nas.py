from __future__ import annotations

from dataclasses import replace

import pytest

from synology_site.commands.check_nas import (
    default_ssh_factory,
    local_ssh_factory,
    probe_lan_reachable,
    remote_transport_label,
    resolve_remote_mode,
    run_check_nas,
)
from synology_site.config import Settings
from synology_site.errors import SynologySiteError
from synology_site.ssh_client import CloudflareAccessSSHClient, RemoteCommandResult, SSHClient


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
    def __init__(self, failures: dict[str, int] | None = None) -> None:
        self.failures = failures or {}
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
        exit_code = self.failures.get(command, 0)
        stdout = ""
        if command == "command -v docker":
            stdout = "docker\n"
        elif command.startswith("test -x "):
            exit_code = self.failures.get(command, 1)
        if command == "docker ps --format '{{.Names}}\\t{{.Image}}\\t{{.Status}}'":
            stdout = "demo\tpython:3.11\tUp 2 minutes\n"
        result = RemoteCommandResult(command, exit_code, stdout, "failed\n" if exit_code else "")
        if check and not result.ok:
            raise SynologySiteError("failed")
        return result


def test_run_check_nas_success() -> None:
    fake = FakeSSH()

    results = run_check_nas(settings(), ssh_factory=lambda _settings, _password: fake)

    assert [result.name for result in results] == [
        "Configuration",
        "Network",
        "SSH",
        "Docker",
        "Docker Compose",
        "Docker root",
        "Containers",
        "Ports",
    ]
    assert "command -v docker" in fake.commands
    assert "docker compose version" in fake.commands


def test_run_check_nas_uses_docker_compose_fallback() -> None:
    fake = FakeSSH({"docker compose version": 1})

    results = run_check_nas(settings(), ssh_factory=lambda _settings, _password: fake)

    compose = next(result for result in results if result.name == "Docker Compose")
    assert compose.detail == "docker-compose available"
    assert "docker-compose version" in fake.commands


def test_run_check_nas_fails_when_docker_missing() -> None:
    container_manager_path = "/var/packages/ContainerManager/target/usr/bin/docker"
    fake = FakeSSH(
        {
            "command -v docker": 1,
            "test -x /usr/local/bin/docker": 1,
            f"test -x {container_manager_path}": 1,
            "sudo -S -p '' /usr/local/bin/docker ps --format '{{.Names}}'": 1,
            f"sudo -S -p '' {container_manager_path} ps --format '{{{{.Names}}}}'": 1,
        }
    )

    with pytest.raises(SynologySiteError, match="Docker is not available"):
        run_check_nas(settings(), ssh_factory=lambda _settings, _password: fake)


def test_run_check_nas_accepts_prompted_password() -> None:
    captured: dict[str, str | None] = {}

    def factory(config: Settings, password: str | None) -> FakeSSH:
        del config
        captured["password"] = password
        return FakeSSH()

    run_check_nas(
        replace(settings(), nas_ssh_password=None),
        ssh_factory=factory,
        prompted_password="prompted",
    )

    assert captured["password"] == "prompted"


def test_default_ssh_factory_uses_cloudflare_access_when_configured() -> None:
    ssh = default_ssh_factory(
        replace(
            settings(),
            ssh_access_hostname="nas-ssh.example.com",
            ssh_access_local_port=9210,
        )
    )

    assert isinstance(ssh, CloudflareAccessSSHClient)
    assert ssh.access_hostname == "nas-ssh.example.com"
    assert ssh.requested_local_port == 9210


def test_local_ssh_factory_always_uses_plain_nas_host_ignoring_tailscale() -> None:
    ssh = local_ssh_factory(
        replace(settings(), tailscale_enabled=True, tailscale_host="100.64.1.2")
    )

    assert isinstance(ssh, SSHClient)
    assert not isinstance(ssh, CloudflareAccessSSHClient)
    assert ssh.host == "192.0.2.10"


def test_resolve_remote_mode_force_remote_skips_lan_probe() -> None:
    probed: list[tuple[str, int]] = []

    def probe(host: str, port: int) -> bool:
        probed.append((host, port))
        return True

    assert resolve_remote_mode(settings(), force_remote=True, lan_probe=probe) is True
    assert probed == []


def test_resolve_remote_mode_auto_detects_from_lan_probe() -> None:
    assert resolve_remote_mode(settings(), lan_probe=lambda host, port: True) is False
    assert resolve_remote_mode(settings(), lan_probe=lambda host, port: False) is True


def test_probe_lan_reachable_returns_false_on_connection_refused() -> None:
    # Port 1 on the TEST-NET-1 documentation range (RFC 5737) is never reachable, so this
    # exercises the real socket path without depending on any actual network being up.
    assert probe_lan_reachable("192.0.2.10", 1, timeout=0.2) is False


def test_remote_transport_label_prefers_cloudflare_access_over_tailscale() -> None:
    label = remote_transport_label(
        replace(
            settings(),
            ssh_access_hostname="nas-ssh.example.com",
            tailscale_enabled=True,
            tailscale_host="100.64.1.2",
        )
    )

    assert "Cloudflare Access" in label
    assert "nas-ssh.example.com" in label


def test_remote_transport_label_falls_back_to_tailscale() -> None:
    label = remote_transport_label(
        replace(settings(), tailscale_enabled=True, tailscale_host="100.64.1.2")
    )

    assert "Tailscale" in label
    assert "100.64.1.2" in label


def test_remote_transport_label_reports_nothing_configured() -> None:
    label = remote_transport_label(settings())

    assert "no remote transport configured" in label


def test_run_check_nas_reports_local_network_by_default() -> None:
    fake = FakeSSH()

    results = run_check_nas(settings(), ssh_factory=lambda _settings, _password: fake)

    network = next(result for result in results if result.name == "Network")
    assert network.detail == "local LAN"


def test_run_check_nas_reports_remote_network_when_requested() -> None:
    fake = FakeSSH()

    results = run_check_nas(
        replace(settings(), tailscale_enabled=True, tailscale_host="100.64.1.2"),
        ssh_factory=lambda _settings, _password: fake,
        remote_mode=True,
    )

    network = next(result for result in results if result.name == "Network")
    assert "remote via Tailscale" in network.detail
