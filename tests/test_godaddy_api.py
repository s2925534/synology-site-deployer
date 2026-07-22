from __future__ import annotations

import pytest

from synology_site.errors import SynologySiteError
from synology_site.godaddy.api import (
    GoDaddyAPI,
    check_nameservers,
    update_domain_nameservers,
)
from synology_site.godaddy.workspace import GoDaddyAccount


def pat_account() -> GoDaddyAccount:
    return GoDaddyAccount(name="default", access_token="pat-token", api_key=None, api_secret=None)


def sso_account() -> GoDaddyAccount:
    return GoDaddyAccount(name="default", access_token=None, api_key="key123", api_secret="sec456")


class FakeResponse:
    def __init__(
        self, payload: object, status_code: int = 200, text: str = ""
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.text = text

    def json(self) -> object:
        if self.payload is None:
            raise ValueError("no json")
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        if method == "GET" and url.endswith("/v3/domains/demo.example.com"):
            return FakeResponse({"domain": "demo.example.com", "nameServers": ["ns1.x", "ns2.x"]})
        if method == "PATCH" and url.endswith("/v3/domains/demo.example.com"):
            return FakeResponse({}, status_code=204)
        if method == "GET" and url.endswith("/records"):
            return FakeResponse([{"type": "A", "name": "@", "data": "1.2.3.4"}])
        if method == "POST" and url.endswith("/records"):
            return FakeResponse({}, status_code=200)
        if method == "PUT" and "/records/" in url:
            return FakeResponse({}, status_code=200)
        return FakeResponse({}, status_code=200)


def test_bearer_header_used_when_access_token_present() -> None:
    api = GoDaddyAPI(pat_account())
    assert api.headers["Authorization"] == "Bearer pat-token"


def test_sso_key_header_used_when_only_key_secret_present() -> None:
    api = GoDaddyAPI(sso_account())
    assert api.headers["Authorization"] == "sso-key key123:sec456"


def test_get_nameservers_is_read_only() -> None:
    session = FakeSession()

    nameservers = GoDaddyAPI(pat_account(), session=session).get_nameservers("demo.example.com")

    assert nameservers == ["ns1.x", "ns2.x"]
    assert all(method == "GET" for method, _, _ in session.requests)


def test_update_nameservers_sends_patch_with_bearer_auth() -> None:
    session = FakeSession()

    GoDaddyAPI(pat_account(), session=session).update_nameservers(
        "demo.example.com", ["ns1.new", "ns2.new"]
    )

    method, url, kwargs = session.requests[-1]
    assert method == "PATCH"
    assert url.endswith("/v3/domains/demo.example.com")
    assert kwargs["json"] == {"nameServers": ["ns1.new", "ns2.new"]}
    assert kwargs["headers"]["Authorization"] == "Bearer pat-token"


def test_list_dns_records_read_only() -> None:
    session = FakeSession()

    records = GoDaddyAPI(pat_account(), session=session).list_dns_records("demo.example.com")

    assert records == [{"type": "A", "name": "@", "data": "1.2.3.4"}]


def test_replace_dns_records_sends_put() -> None:
    session = FakeSession()

    GoDaddyAPI(pat_account(), session=session).replace_dns_records(
        "demo.example.com", "A", "@", [{"data": "5.6.7.8"}]
    )

    method, url, kwargs = session.requests[-1]
    assert method == "PUT"
    assert url.endswith("/records/A/@")
    assert kwargs["json"] == [{"data": "5.6.7.8"}]


def test_add_dns_records_sends_post() -> None:
    session = FakeSession()

    GoDaddyAPI(pat_account(), session=session).add_dns_records(
        "demo.example.com", [{"type": "TXT", "name": "@", "data": "hello"}]
    )

    method, url, kwargs = session.requests[-1]
    assert method == "POST"
    assert url.endswith("/records")
    assert kwargs["json"] == [{"type": "TXT", "name": "@", "data": "hello"}]


def test_request_raises_on_error_status_with_message_body() -> None:
    class ErrorSession:
        def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
            return FakeResponse({"code": "NOT_FOUND", "message": "Domain not found"}, 404)

    with pytest.raises(SynologySiteError, match="Domain not found"):
        GoDaddyAPI(pat_account(), session=ErrorSession()).get_domain("missing.example.com")


def test_request_raises_with_raw_text_when_body_not_json() -> None:
    class ErrorSession:
        def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
            return FakeResponse(None, 500, text="internal server error")

    with pytest.raises(SynologySiteError, match="internal server error"):
        GoDaddyAPI(pat_account(), session=ErrorSession()).get_domain("demo.example.com")


def test_godaddy_api_requires_ready_account() -> None:
    with pytest.raises(SynologySiteError, match="incomplete"):
        GoDaddyAPI(GoDaddyAccount(name="x", access_token=None, api_key=None, api_secret=None))


def test_check_nameservers_matches_case_and_trailing_dot_insensitively() -> None:
    session = FakeSession()

    result = check_nameservers(
        pat_account(),
        domain="demo.example.com",
        expected_nameservers=["NS1.X.", "ns2.x"],
        session=session,
    )

    assert result.matches is True
    assert result.current_nameservers == ("ns1.x", "ns2.x")


def test_check_nameservers_detects_mismatch() -> None:
    session = FakeSession()

    result = check_nameservers(
        pat_account(),
        domain="demo.example.com",
        expected_nameservers=["ns1.cloudflare.com", "ns2.cloudflare.com"],
        session=session,
    )

    assert result.matches is False


def test_update_domain_nameservers_refuses_without_confirmation() -> None:
    session = FakeSession()

    with pytest.raises(SynologySiteError, match="not confirmed"):
        update_domain_nameservers(
            pat_account(),
            domain="demo.example.com",
            nameservers=["ns1.new", "ns2.new"],
            confirmed=False,
            session=session,
        )
    assert not any(method == "PATCH" for method, _, _ in session.requests)


def test_update_domain_nameservers_writes_when_confirmed() -> None:
    session = FakeSession()

    update_domain_nameservers(
        pat_account(),
        domain="demo.example.com",
        nameservers=["ns1.new", "ns2.new"],
        confirmed=True,
        session=session,
    )

    assert any(method == "PATCH" for method, _, _ in session.requests)
