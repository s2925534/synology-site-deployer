from __future__ import annotations

import pytest

from synology_site.commands.godaddy_dns import _parse_record
from synology_site.errors import SynologySiteError
from synology_site.godaddy.api import GoDaddyAPI
from synology_site.godaddy.workspace import GoDaddyAccount


def account() -> GoDaddyAccount:
    return GoDaddyAccount(name="default", access_token="pat-token", api_key=None, api_secret=None)


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        if method == "GET" and url.endswith("/records"):
            return FakeResponse([{"type": "A", "name": "@", "data": "1.2.3.4"}])
        return FakeResponse({}, status_code=200)


def test_parse_record_without_ttl() -> None:
    record = _parse_record("A,@,1.2.3.4")
    assert record == {"type": "A", "name": "@", "data": "1.2.3.4"}


def test_parse_record_with_ttl() -> None:
    record = _parse_record("TXT,@,hello,3600")
    assert record == {"type": "TXT", "name": "@", "data": "hello", "ttl": 3600}


def test_parse_record_rejects_too_few_parts() -> None:
    with pytest.raises(SynologySiteError, match="Invalid record spec"):
        _parse_record("A,@")


def test_list_dns_records_via_api() -> None:
    session = FakeSession()
    records = GoDaddyAPI(account(), session=session).list_dns_records("demo.example.com")
    assert records == [{"type": "A", "name": "@", "data": "1.2.3.4"}]


def test_add_and_replace_records_via_api() -> None:
    session = FakeSession()
    api = GoDaddyAPI(account(), session=session)

    api.add_dns_records("demo.example.com", [_parse_record("TXT,@,hello")])
    api.replace_dns_records("demo.example.com", "A", "@", [_parse_record("A,@,5.6.7.8")])

    methods = [method for method, _, _ in session.requests]
    assert "POST" in methods
    assert "PUT" in methods
