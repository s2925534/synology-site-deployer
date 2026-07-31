from __future__ import annotations

import json
from pathlib import Path

import pytest

from synology_site.cloudflare.redirects import (
    RedirectRule,
    RedirectTarget,
    group_of,
    load_rules_file,
    rule_to_cloudflare_payload,
    with_group_enabled,
)
from synology_site.errors import SynologySiteError


def test_group_of_splits_on_the_separator() -> None:
    assert group_of("blog-redirect--posts") == "blog-redirect"
    assert group_of("aliases--pv") == "aliases"


def test_rule_ref_is_group_and_name_joined() -> None:
    rule = RedirectRule(
        group="aliases",
        name="pv",
        description="",
        enabled=True,
        expression='(http.host eq "pv.example.com")',
        target=RedirectTarget(kind="static", value="https://example.com/"),
    )
    assert rule.ref == "aliases--pv"


def test_redirect_target_rejects_unknown_kind() -> None:
    with pytest.raises(SynologySiteError):
        RedirectTarget(kind="bogus", value="x")


def test_rule_to_cloudflare_payload_static_target() -> None:
    rule = RedirectRule(
        group="aliases",
        name="pv",
        description="pv -> canonical",
        enabled=True,
        expression='(http.host eq "pv.example.com")',
        target=RedirectTarget(kind="static", value="https://example.com/"),
    )

    payload = rule_to_cloudflare_payload(rule)

    assert payload == {
        "ref": "aliases--pv",
        "description": "pv -> canonical",
        "expression": '(http.host eq "pv.example.com")',
        "action": "redirect",
        "action_parameters": {
            "from_value": {
                "target_url": {"value": "https://example.com/"},
                "status_code": 301,
                "preserve_query_string": True,
            }
        },
        "enabled": True,
    }


def test_rule_to_cloudflare_payload_dynamic_target() -> None:
    rule = RedirectRule(
        group="blog-redirect",
        name="posts",
        description="",
        enabled=False,
        expression='(http.request.uri.path matches "^/[0-9]{4}/")',
        target=RedirectTarget(
            kind="dynamic", value='concat("https://x.example", http.request.uri.path)'
        ),
        status_code=302,
        preserve_query_string=False,
    )

    payload = rule_to_cloudflare_payload(rule)

    assert payload["action_parameters"]["from_value"]["target_url"] == {
        "expression": 'concat("https://x.example", http.request.uri.path)'
    }
    assert payload["action_parameters"]["from_value"]["status_code"] == 302
    assert payload["action_parameters"]["from_value"]["preserve_query_string"] is False
    assert payload["enabled"] is False


def test_load_rules_file(tmp_path: Path) -> None:
    rules_file = tmp_path / "example.json"
    rules_file.write_text(
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
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    rule_set = load_rules_file(rules_file)

    assert rule_set.domain == "example.com"
    assert len(rule_set.rules) == 1
    assert rule_set.rules[0].ref == "aliases--pv"
    assert rule_set.rules[0].target.kind == "static"


def test_load_rules_file_rejects_missing_domain(tmp_path: Path) -> None:
    rules_file = tmp_path / "bad.json"
    rules_file.write_text(json.dumps({"rules": []}), encoding="utf-8")

    with pytest.raises(SynologySiteError, match="domain"):
        load_rules_file(rules_file)


def test_load_rules_file_rejects_empty_rules(tmp_path: Path) -> None:
    rules_file = tmp_path / "empty.json"
    rules_file.write_text(json.dumps({"domain": "example.com", "rules": []}), encoding="utf-8")

    with pytest.raises(SynologySiteError, match="no rules"):
        load_rules_file(rules_file)


def test_load_rules_file_rejects_rule_missing_a_required_field(tmp_path: Path) -> None:
    rules_file = tmp_path / "bad-rule.json"
    rules_file.write_text(
        json.dumps({"domain": "example.com", "rules": [{"group": "aliases", "name": "pv"}]}),
        encoding="utf-8",
    )

    with pytest.raises(SynologySiteError, match="expression"):
        load_rules_file(rules_file)


def test_load_the_real_veloso_dev_rules_file() -> None:
    """Guards against the checked-in redirects/veloso-dev.json drifting out of a loadable shape."""
    rule_set = load_rules_file(Path("redirects/veloso-dev.json"))

    assert rule_set.domain == "veloso.dev"
    refs = {rule.ref for rule in rule_set.rules}
    assert refs == {
        "aliases--pv",
        "aliases--resume",
        "aliases--cv",
        "blog-redirect--posts",
        "blog-redirect--category",
        "blog-redirect--tag",
    }
    enabled_by_ref = {rule.ref: rule.enabled for rule in rule_set.rules}
    assert enabled_by_ref["aliases--pv"] is True
    assert enabled_by_ref["blog-redirect--posts"] is False


def test_with_group_enabled_flips_only_the_matching_group() -> None:
    live_rules = [
        {"ref": "aliases--pv", "enabled": True, "other": "untouched"},
        {"ref": "blog-redirect--posts", "enabled": False},
        {"ref": "blog-redirect--category", "enabled": False},
    ]

    updated = with_group_enabled(live_rules, group="blog-redirect", enabled=True)

    assert updated == [
        {"ref": "aliases--pv", "enabled": True, "other": "untouched"},
        {"ref": "blog-redirect--posts", "enabled": True},
        {"ref": "blog-redirect--category", "enabled": True},
    ]
    # original list must not be mutated in place
    assert live_rules[1]["enabled"] is False


def test_with_group_enabled_raises_when_group_not_found() -> None:
    live_rules = [{"ref": "aliases--pv", "enabled": True}]
    with pytest.raises(SynologySiteError, match="nonexistent"):
        with_group_enabled(live_rules, group="nonexistent", enabled=True)
