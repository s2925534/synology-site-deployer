from __future__ import annotations

import json
from pathlib import Path

import pytest

from synology_site.cloudflare.workspace import CloudflareAccount
from synology_site.commands.redirect_ruleset import run_apply, run_set_group_enabled, run_status
from synology_site.errors import SynologySiteError


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
    def __init__(self, live_rules: list[dict[str, object]]) -> None:
        self.live_rules = live_rules
        self.requests: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
        self.requests.append((method, url, kwargs))
        if method == "GET" and "rulesets/phases" in url:
            return FakeResponse({"success": True, "result": {"rules": self.live_rules}})
        if method == "PUT" and "rulesets/phases" in url:
            return FakeResponse({"success": True, "result": {}})
        return FakeResponse({"success": True, "result": {}})


def rules_file(tmp_path: Path) -> Path:
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps(
            {
                "domain": "example.com",
                "rules": [
                    {
                        "group": "aliases",
                        "name": "pv",
                        "description": "pv alias",
                        "enabled": True,
                        "expression": '(http.host eq "pv.example.com")',
                        "target": {"type": "static", "value": "https://example.com/"},
                    },
                    {
                        "group": "blog-redirect",
                        "name": "posts",
                        "description": "posts redirect",
                        "enabled": False,
                        "expression": '(http.request.uri.path matches "^/[0-9]{4}/")',
                        "target": {
                            "type": "dynamic",
                            "value": 'concat("https://other.example", http.request.uri.path)',
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_run_status_is_read_only() -> None:
    session = FakeSession(live_rules=[{"ref": "aliases--pv", "enabled": True}])

    rules = run_status("example.com", account=account(), session=session)

    assert rules == [{"ref": "aliases--pv", "enabled": True}]
    assert not any(method == "PUT" for method, _, _ in session.requests)


def test_run_apply_snapshots_before_writing(tmp_path: Path) -> None:
    session = FakeSession(live_rules=[{"ref": "old--rule", "enabled": True}])
    backup_dir = tmp_path / "redirect-backups"

    snapshot_path = run_apply(
        "example.com",
        account=account(),
        rules_file=rules_file(tmp_path),
        confirmed=True,
        backup_dir=backup_dir,
        session=session,
    )

    assert snapshot_path.exists()
    saved = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert saved["rules"] == [{"ref": "old--rule", "enabled": True}]

    methods = [method for method, _, _ in session.requests]
    assert methods.index("GET") < methods.index("PUT")

    put_body = next(kwargs for method, _, kwargs in session.requests if method == "PUT")
    refs = [rule["ref"] for rule in put_body["json"]["rules"]]
    assert refs == ["aliases--pv", "blog-redirect--posts"]


def test_run_apply_refuses_without_confirmation(tmp_path: Path) -> None:
    session = FakeSession(live_rules=[])

    with pytest.raises(SynologySiteError, match="ot confirmed"):
        run_apply(
            "example.com",
            account=account(),
            rules_file=rules_file(tmp_path),
            confirmed=False,
            backup_dir=tmp_path / "redirect-backups",
            session=session,
        )
    assert not any(method == "PUT" for method, _, _ in session.requests)


def test_run_set_group_enabled_flips_only_the_target_group(tmp_path: Path) -> None:
    session = FakeSession(
        live_rules=[
            {"ref": "aliases--pv", "enabled": True},
            {"ref": "blog-redirect--posts", "enabled": False},
            {"ref": "blog-redirect--category", "enabled": False},
        ]
    )

    run_set_group_enabled(
        "example.com",
        account=account(),
        group="blog-redirect",
        enabled=True,
        confirmed=True,
        backup_dir=tmp_path / "redirect-backups",
        session=session,
    )

    put_body = next(kwargs for method, _, kwargs in session.requests if method == "PUT")
    by_ref = {rule["ref"]: rule["enabled"] for rule in put_body["json"]["rules"]}
    assert by_ref == {
        "aliases--pv": True,
        "blog-redirect--posts": True,
        "blog-redirect--category": True,
    }


def test_run_set_group_enabled_refuses_without_confirmation(tmp_path: Path) -> None:
    session = FakeSession(live_rules=[{"ref": "blog-redirect--posts", "enabled": False}])

    with pytest.raises(SynologySiteError, match="ot confirmed"):
        run_set_group_enabled(
            "example.com",
            account=account(),
            group="blog-redirect",
            enabled=True,
            confirmed=False,
            backup_dir=tmp_path / "redirect-backups",
            session=session,
        )
    assert not any(method == "PUT" for method, _, _ in session.requests)
