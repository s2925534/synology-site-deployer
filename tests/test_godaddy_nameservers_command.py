from __future__ import annotations

from pathlib import Path

import pytest

from synology_site.commands.godaddy_nameservers import run_check, run_set
from synology_site.errors import SynologySiteError
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
    def __init__(self, nameservers: list[str]) -> None:
        self.nameservers = nameservers
        self.requests: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        if method == "GET" and url.endswith("/v3/domains/demo.example.com"):
            return FakeResponse({"domain": "demo.example.com", "nameServers": self.nameservers})
        if method == "PATCH":
            return FakeResponse({}, status_code=204)
        return FakeResponse({}, status_code=200)


def test_run_check_reports_match() -> None:
    session = FakeSession(["ns1.cloudflare.com", "ns2.cloudflare.com"])

    result = run_check(
        "demo.example.com",
        account=account(),
        expected_nameservers=["ns1.cloudflare.com", "ns2.cloudflare.com"],
        session=session,
    )

    assert result.matches is True


def test_run_check_reports_mismatch() -> None:
    session = FakeSession(["ns-1.awsdns-00.net"])

    result = run_check(
        "demo.example.com",
        account=account(),
        expected_nameservers=["ns1.cloudflare.com", "ns2.cloudflare.com"],
        session=session,
    )

    assert result.matches is False


def test_run_set_snapshots_before_writing(tmp_path: Path) -> None:
    session = FakeSession(["ns-old-1.awsdns-00.net", "ns-old-2.awsdns-00.net"])
    backup_dir = tmp_path / "godaddy-backups"

    snapshot_path = run_set(
        "demo.example.com",
        account=account(),
        nameservers=["ns1.cloudflare.com", "ns2.cloudflare.com"],
        confirmed=True,
        backup_dir=backup_dir,
        session=session,
    )

    assert snapshot_path == backup_dir / "demo.example.com" / "nameservers-before.json"
    assert snapshot_path.exists()
    assert "ns-old-1.awsdns-00.net" in snapshot_path.read_text(encoding="utf-8")
    rollback_doc = (backup_dir / "demo.example.com" / "rollback.md").read_text(encoding="utf-8")
    assert "ns-old-1.awsdns-00.net" in rollback_doc
    assert "ns1.cloudflare.com" in rollback_doc

    # snapshot must be written before the PATCH -- assert the GET (snapshot read) happened
    # strictly before the PATCH (the write) in the request order.
    methods = [method for method, _, _ in session.requests]
    assert methods.index("GET") < methods.index("PATCH")


def test_run_set_refuses_without_confirmation(tmp_path: Path) -> None:
    session = FakeSession(["ns-old-1.awsdns-00.net"])

    with pytest.raises(SynologySiteError, match="not confirmed"):
        run_set(
            "demo.example.com",
            account=account(),
            nameservers=["ns1.cloudflare.com"],
            confirmed=False,
            backup_dir=tmp_path / "godaddy-backups",
            session=session,
        )
    # the snapshot read is allowed to happen (harmless, read-only) but no write should occur
    assert not any(method == "PATCH" for method, _, _ in session.requests)
