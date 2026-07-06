from __future__ import annotations

from synology_site.cloudflare.api import configure_cloudflare_route
from synology_site.cloudflare.workspace import CloudflareAccount


def account() -> CloudflareAccount:
    return CloudflareAccount(
        name="default",
        api_token="token",
        account_id="account",
        zone_id="zone",
        zone_domain="example.com",
        tunnel_id="tunnel-id",
        tunnel_name="my-nas-tunnel",
    )


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


def test_configure_cloudflare_route_updates_tunnel_and_dns() -> None:
    session = FakeSession()

    result = configure_cloudflare_route(
        account(),
        hostname="demo.example.com",
        service_url="http://192.0.2.10:5051",
        session=session,
    )

    assert result.tunnel_configured is True
    assert result.dns_configured is True
    assert result.dns_record_id == "record-id"

    tunnel_put = next(
        kwargs
        for method, url, kwargs in session.requests
        if method == "PUT" and "cfd_tunnel" in url
    )
    assert tunnel_put["json"] == {
        "config": {
            "ingress": [
                {"hostname": "demo.example.com", "service": "http://192.0.2.10:5051"},
                {"service": "http_status:404"},
            ]
        }
    }

    dns_post = next(
        kwargs
        for method, url, kwargs in session.requests
        if method == "POST" and "dns_records" in url
    )
    assert dns_post["json"] == {
        "type": "CNAME",
        "name": "demo.example.com",
        "content": "tunnel-id.cfargotunnel.com",
        "proxied": True,
    }
