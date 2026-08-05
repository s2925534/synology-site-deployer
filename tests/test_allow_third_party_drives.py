from __future__ import annotations

import re

import pytest

from synology_site.commands.allow_third_party_drives import (
    STORAGE_DAEMON,
    run_allow_third_party_drives,
    set_drive_compatibility_enforcement,
)
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
    def __init__(self, *, initial_flag: str = "yes", restart_exit_code: int = 0) -> None:
        self.flag = initial_flag
        self.restart_exit_code = restart_exit_code
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
        stdin: str | None = None,
    ) -> RemoteCommandResult:
        del timeout, stdin
        self.commands.append(command)

        if command.startswith("grep -o 'support_disk_compatibility"):
            result = RemoteCommandResult(
                command, 0, f'support_disk_compatibility="{self.flag}"\n', ""
            )
        elif "sed -i" in command:
            match = re.search(r'support_disk_compatibility="(yes|no)"', command)
            assert match is not None
            self.flag = match.group(1)
            result = RemoteCommandResult(command, 0, "", "")
        elif STORAGE_DAEMON in command:
            result = RemoteCommandResult(
                command, self.restart_exit_code, "", "" if self.restart_exit_code == 0 else "boom"
            )
        else:
            result = RemoteCommandResult(command, 0, "", "")

        if check and not result.ok:
            raise SynologySiteError(f"failed: {command}")
        return result


def test_disables_certified_drive_enforcement_and_restarts_daemon() -> None:
    fake = FakeSSH(initial_flag="yes")

    result = set_drive_compatibility_enforcement(fake, enforce=False)

    assert result.before == "yes"
    assert result.after == "no"
    assert any("sed -i" in c and "sudo -S" in c for c in fake.commands)
    assert any(STORAGE_DAEMON in c for c in fake.commands)
    # both synoinfo.conf copies get backed up, only if not already backed up
    assert any("/etc/synoinfo.conf.bak.synology-site-drive-fix" in c for c in fake.commands)
    assert any("/etc.defaults/synoinfo.conf.bak.synology-site-drive-fix" in c for c in fake.commands)


def test_revert_restores_certified_drive_enforcement() -> None:
    fake = FakeSSH(initial_flag="no")

    result = set_drive_compatibility_enforcement(fake, enforce=True)

    assert result.before == "no"
    assert result.after == "yes"


def test_raises_when_storage_daemon_restart_fails() -> None:
    fake = FakeSSH(initial_flag="yes", restart_exit_code=127)

    with pytest.raises(SynologySiteError, match="storage daemon could not be restarted"):
        set_drive_compatibility_enforcement(fake, enforce=False)


def test_run_allow_third_party_drives_uses_resolved_target() -> None:
    fake = FakeSSH(initial_flag="yes")

    result = run_allow_third_party_drives(
        settings(),
        enforce=False,
        ssh_factory=lambda _settings, _password: fake,
    )

    assert result.after == "no"
