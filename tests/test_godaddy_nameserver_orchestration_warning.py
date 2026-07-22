from __future__ import annotations

import pytest

from synology_site.commands.create import _warn_on_godaddy_nameserver_mismatch as create_warn
from synology_site.commands.migrate_from_lightsail import (
    _warn_on_godaddy_nameserver_mismatch as migrate_warn,
)
from synology_site.config import Settings


def base_settings(*, godaddy_ready: bool, cloudflare_ready: bool) -> Settings:
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
        cf_api_token="token" if cloudflare_ready else None,
        cf_account_id="account" if cloudflare_ready else None,
        cf_zone_id="zone" if cloudflare_ready else None,
        cf_zone_domain="demo.example.com",
        cf_tunnel_id="tunnel-id" if cloudflare_ready else None,
        cf_tunnel_name="my-nas-tunnel",
        db_mode="none",
        db_type="mariadb",
        db_image="mariadb:11",
        db_password_length=32,
        db_publish_port=False,
        db_host_port=None,
        allow_overwrite=False,
        dry_run=False,
        gd_access_token="pat-token" if godaddy_ready else None,
    )


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self.payload


class BoomSession:
    """Asserts if ever called -- proves the check short-circuits before any network call."""

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        raise AssertionError(f"unexpected request: {method} {url}")


class FakeCloudflareSession:
    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        if method == "GET" and url.endswith("/zones/zone"):
            nameservers = ["ns1.cloudflare.com", "ns2.cloudflare.com"]
            return FakeResponse({"success": True, "result": {"name_servers": nameservers}})
        return FakeResponse({"success": True, "result": {}})


class FakeGoDaddySession:
    def __init__(self, nameservers: list[str]) -> None:
        self.nameservers = nameservers

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        return FakeResponse({"domain": "demo.example.com", "nameServers": self.nameservers})


@pytest.mark.parametrize("warn_fn", [create_warn, migrate_warn])
def test_skips_silently_when_godaddy_not_configured(warn_fn) -> None:
    settings = base_settings(godaddy_ready=False, cloudflare_ready=True)

    # BoomSession proves neither Cloudflare nor GoDaddy is ever contacted when there's no
    # GoDaddy account to check against -- this must be a pure no-op, not a network call.
    warn_fn(
        settings,
        "demo.example.com",
        workspace=None,
        cloudflare_session=BoomSession(),
        godaddy_session=BoomSession(),
    )


@pytest.mark.parametrize("warn_fn", [create_warn, migrate_warn])
def test_skips_silently_when_cloudflare_not_configured(warn_fn) -> None:
    settings = base_settings(godaddy_ready=True, cloudflare_ready=False)

    warn_fn(
        settings,
        "demo.example.com",
        workspace=None,
        cloudflare_session=BoomSession(),
        godaddy_session=BoomSession(),
    )


@pytest.mark.parametrize("warn_fn", [create_warn, migrate_warn])
def test_never_raises_on_internal_error(warn_fn) -> None:
    settings = base_settings(godaddy_ready=True, cloudflare_ready=True)

    class ErrorSession:
        def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
            raise RuntimeError("network exploded")

    # Must swallow the error, not propagate it -- this check is purely informational.
    warn_fn(
        settings,
        "demo.example.com",
        workspace=None,
        cloudflare_session=ErrorSession(),
        godaddy_session=ErrorSession(),
    )


@pytest.mark.parametrize("warn_fn", [create_warn, migrate_warn])
def test_runs_check_when_both_configured_and_matching(warn_fn) -> None:
    settings = base_settings(godaddy_ready=True, cloudflare_ready=True)

    warn_fn(
        settings,
        "demo.example.com",
        workspace=None,
        cloudflare_session=FakeCloudflareSession(),
        godaddy_session=FakeGoDaddySession(["ns1.cloudflare.com", "ns2.cloudflare.com"]),
    )


@pytest.mark.parametrize("warn_fn", [create_warn, migrate_warn])
def test_runs_check_and_does_not_raise_on_mismatch(warn_fn) -> None:
    settings = base_settings(godaddy_ready=True, cloudflare_ready=True)

    # A mismatch prints a warning (not asserted here, output.py is a thin wrapper) but must
    # never raise -- the migration/deploy already succeeded, this is advisory only.
    warn_fn(
        settings,
        "demo.example.com",
        workspace=None,
        cloudflare_session=FakeCloudflareSession(),
        godaddy_session=FakeGoDaddySession(["ns-1.awsdns-00.net"]),
    )
