from __future__ import annotations

from synology_site.commands.run_hdd_db_fix import run_hdd_db_fix
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
        stdin: str | None = None,
    ) -> RemoteCommandResult:
        del timeout, stdin
        self.commands.append(command)
        stdout = "syno_hdd_db output\n" if "syno_hdd_db.sh" in command else ""
        return RemoteCommandResult(command, 0, stdout, "")


def fake_hdd_db_files(version: str) -> dict[str, str]:
    return {"syno_hdd_db.sh": f"script for {version}", "syno_hdd_vendor_ids.txt": "vendor ids"}


def test_returns_none_when_not_confirmed() -> None:
    fake = FakeSSH()

    result = run_hdd_db_fix(
        settings(),
        ssh_factory=lambda _settings, _password: fake,
        confirm=lambda _version: False,
        fetch_files=fake_hdd_db_files,
    )

    assert result is None
    assert fake.commands == []
    assert fake.uploaded == {}


def test_uploads_files_and_runs_script_when_confirmed() -> None:
    fake = FakeSSH()

    result = run_hdd_db_fix(
        settings(),
        hdd_db_version="v1.2.3",
        ssh_factory=lambda _settings, _password: fake,
        confirm=lambda _version: True,
        fetch_files=fake_hdd_db_files,
    )

    assert result is not None
    assert result.version == "v1.2.3"
    assert result.remote_dir == "/volume1/docker/hdd-db-fix"
    assert result.output == "syno_hdd_db output\n"

    assert fake.uploaded["/volume1/docker/hdd-db-fix/syno_hdd_db.sh"] == "script for v1.2.3"
    assert fake.uploaded["/volume1/docker/hdd-db-fix/syno_hdd_vendor_ids.txt"] == "vendor ids"

    assert any("mkdir -p /volume1/docker/hdd-db-fix" in c for c in fake.commands)
    assert any("chmod +x /volume1/docker/hdd-db-fix/syno_hdd_db.sh" in c for c in fake.commands)
    run_cmd = next(c for c in fake.commands if "syno_hdd_db.sh -s -n" in c)
    assert "sudo -S -p ''" in run_cmd
    assert "/volume1/docker/hdd-db-fix/syno_hdd_db.sh -s -n" in run_cmd
