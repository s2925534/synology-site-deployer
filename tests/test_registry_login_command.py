from __future__ import annotations

import pytest

from synology_site.commands.registry_login import registry_login
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
    def __init__(self, failures: dict[str, int] | None = None) -> None:
        self.failures = failures or {}
        self.commands: list[str] = []
        self.uploaded: dict[str, str] = {}

    def __enter__(self) -> FakeSSH:
        return self

    def __exit__(self, *_exc: object) -> None:
        pass

    def upload_text(self, remote_path: str, content: str) -> None:
        self.uploaded[remote_path] = content

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
        stdout = "docker\n" if command == "command -v docker" else ""
        stderr = "" if exit_code == 0 else "login failed\n"
        result = RemoteCommandResult(command, exit_code, stdout, stderr)
        if check and not result.ok:
            raise SynologySiteError("failed")
        return result


def test_registry_login_uploads_token_and_logs_in() -> None:
    fake = FakeSSH()

    result = registry_login(
        "zqxdeveloper",
        "sekret-token",
        settings=settings(),
        registry="ghcr.io",
        ssh_factory=lambda _settings, _password: fake,
    )

    assert result.registry == "ghcr.io"
    assert result.username == "zqxdeveloper"
    assert fake.uploaded["/tmp/.synology-site-registry-token"] == "sekret-token"
    assert any(
        "docker login ghcr.io -u zqxdeveloper --password-stdin" in c for c in fake.commands
    )
    # the token itself must never appear in a command string
    assert not any("sekret-token" in c for c in fake.commands)
    # temp file removed afterwards
    assert any(c.startswith("rm -f") for c in fake.commands)


def test_registry_login_raises_on_docker_login_failure() -> None:
    fake = FakeSSH(
        {
            "docker login ghcr.io -u zqxdeveloper --password-stdin "
            "< /tmp/.synology-site-registry-token": 1
        }
    )

    with pytest.raises(SynologySiteError, match="docker login to ghcr.io failed"):
        registry_login(
            "zqxdeveloper",
            "sekret-token",
            settings=settings(),
            registry="ghcr.io",
            ssh_factory=lambda _settings, _password: fake,
        )


def test_registry_login_removes_temp_file_even_on_failure() -> None:
    fake = FakeSSH(
        {
            "docker login ghcr.io -u zqxdeveloper --password-stdin "
            "< /tmp/.synology-site-registry-token": 1
        }
    )

    with pytest.raises(SynologySiteError):
        registry_login(
            "zqxdeveloper",
            "sekret-token",
            settings=settings(),
            registry="ghcr.io",
            ssh_factory=lambda _settings, _password: fake,
        )

    assert any(c.startswith("rm -f") for c in fake.commands)
