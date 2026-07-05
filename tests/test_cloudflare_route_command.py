from __future__ import annotations

import pytest

from synology_site.commands.cloudflare_route import configure_route
from synology_site.config import Settings
from synology_site.errors import SynologySiteError


def settings(**overrides: object) -> Settings:
    base = dict(
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
        cf_api_token="token",
        cf_account_id="account",
        cf_zone_id="zone",
        cf_zone_domain="veloso.dev",
        cf_tunnel_id="tunnel-id",
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
    base.update(overrides)
    return Settings(**base)


class FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, object]:
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        if method == "GET" and url.endswith("/configurations"):
            return FakeResponse({"success": True, "result": {"config": {"ingress": []}}})
        if method == "PUT" and url.endswith("/configurations"):
            return FakeResponse({"success": True, "result": {}})
        if method == "GET" and url.endswith("/dns_records"):
            return FakeResponse({"success": True, "result": []})
        if method == "POST" and url.endswith("/dns_records"):
            return FakeResponse({"success": True, "result": {"id": "record-id"}})
        return FakeResponse({"success": True, "result": {}})


def test_configure_route_points_hostname_at_fixed_port() -> None:
    session = FakeSession()

    result = configure_route(
        "api.resilinked.veloso.dev",
        port=80,
        settings=settings(),
        session=session,
    )

    assert result.hostname == "api.resilinked.veloso.dev"
    assert result.service_url == "http://192.0.2.10:80"

    tunnel_put = next(
        kwargs
        for method, url, kwargs in session.requests
        if method == "PUT" and "cfd_tunnel" in url
    )
    assert tunnel_put["json"]["config"]["ingress"][0] == {
        "hostname": "api.resilinked.veloso.dev",
        "service": "http://192.0.2.10:80",
    }


def test_configure_route_allows_service_host_override() -> None:
    session = FakeSession()

    result = configure_route(
        "studio.resilinked.veloso.dev",
        port=80,
        settings=settings(),
        service_host="10.0.0.5",
        session=session,
    )

    assert result.service_url == "http://10.0.0.5:80"


def test_configure_route_requires_cloudflare_credentials() -> None:
    session = FakeSession()

    with pytest.raises(SynologySiteError, match="Cloudflare API credentials"):
        configure_route(
            "app.resilinked.veloso.dev",
            port=80,
            settings=settings(cf_api_token=None),
            session=session,
        )
