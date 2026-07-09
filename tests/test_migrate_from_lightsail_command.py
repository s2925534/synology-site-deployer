from __future__ import annotations

from pathlib import Path

import pytest

from synology_site.commands.migrate_from_lightsail import run_dry_run
from synology_site.config import Settings
from synology_site.errors import SynologySiteError
from synology_site.lightsail.report import DnsRecordInfo
from synology_site.lightsail.source import LightsailSource
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
        cf_zone_domain="veloso.dev",
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


def source() -> LightsailSource:
    return LightsailSource(
        name="veloso-dev",
        host="198.51.100.10",
        port=22,
        user="ubuntu",
        ssh_key_path="/keys/veloso-dev.pem",
        ssh_password=None,
    )


class FakeSSH:
    def __init__(self) -> None:
        self.entered = False

    def __enter__(self) -> FakeSSH:
        self.entered = True
        return self

    def __exit__(self, *_exc: object) -> None:
        pass

    def run(
        self, command: str, *, check: bool = False, timeout: int | None = None
    ) -> RemoteCommandResult:
        del check, timeout
        return RemoteCommandResult(command, 1, "", "")


def test_run_dry_run_writes_report(tmp_path: Path) -> None:
    result = run_dry_run(
        source=source(),
        source_domain="veloso.dev",
        target_domain="systemsnotsilos.com",
        target_mode="existing-site-replace",
        settings=settings(),
        output_dir=tmp_path,
        ssh_factory=lambda _source, _password: FakeSSH(),
        dns_lookup=lambda _settings, _domain: (
            True,
            (DnsRecordInfo("A", "veloso.dev", "203.0.113.5", False),),
        ),
    )

    assert result.report_path == tmp_path / "veloso-dev-to-systemsnotsilos-com-dry-run.md"
    content = result.report_path.read_text(encoding="utf-8")
    assert "veloso.dev -> systemsnotsilos.com" in content
    assert "existing-site-replace" in content
    assert "203.0.113.5" in content
    assert "serialization-safe search-replace" in content


def test_run_dry_run_rejects_invalid_target_mode(tmp_path: Path) -> None:
    with pytest.raises(SynologySiteError, match="--target-mode"):
        run_dry_run(
            source=source(),
            source_domain="veloso.dev",
            target_domain="veloso.dev",
            target_mode="bogus-mode",
            settings=settings(),
            output_dir=tmp_path,
            ssh_factory=lambda _source, _password: FakeSSH(),
            dns_lookup=lambda _settings, _domain: (False, ()),
        )


def test_run_dry_run_reports_skipped_dns_check_when_not_configured(tmp_path: Path) -> None:
    result = run_dry_run(
        source=source(),
        source_domain="veloso.dev",
        target_domain="veloso.dev",
        target_mode="new-site",
        settings=settings(),
        output_dir=tmp_path,
        ssh_factory=lambda _source, _password: FakeSSH(),
        dns_lookup=lambda _settings, _domain: (False, ()),
    )

    assert "Skipped: no Cloudflare API credentials" in result.report
