from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from synology_site.errors import SynologySiteError

# One Cloudflare zone-level Ruleset Engine phase implements redirects (as opposed to Bulk
# Redirects, which is a separate, simpler static-list product): "http_request_dynamic_redirect".
# Its entrypoint ruleset holds every redirect rule for the zone, static and pattern-based alike --
# `PUT .../rulesets/phases/http_request_dynamic_redirect/entrypoint` replaces the *entire* rule
# list for the zone in one call, so every write in this module round-trips the full set, not a
# single rule.
REDIRECT_PHASE = "http_request_dynamic_redirect"

# Rule `ref`s follow "<group>--<name>" (e.g. "blog-redirect--posts", "aliases--pv") so a group of
# related rules can be found and toggled together later from Cloudflare's own GET response alone
# -- no need to keep the original rules file around for --enable-group/--disable-group.
_REF_SEPARATOR = "--"


@dataclass(frozen=True)
class RedirectTarget:
    """Where a matched request redirects to.

    'static' is a fixed URL (used for the alias redirects: pv.veloso.dev -> p.veloso.dev).
    'dynamic' is a Cloudflare ruleset expression that builds the target from the request (used
    for the blog-link redirects, which need to carry the original path through, e.g.
    `concat("https://www.systemsnotsilos.com", http.request.uri.path)`).
    """

    kind: str  # "static" | "dynamic"
    value: str

    def __post_init__(self) -> None:
        if self.kind not in {"static", "dynamic"}:
            raise SynologySiteError(f"Unknown redirect target kind: {self.kind!r}")


@dataclass(frozen=True)
class RedirectRule:
    group: str
    name: str
    description: str
    enabled: bool
    expression: str
    target: RedirectTarget
    status_code: int = 301
    preserve_query_string: bool = True

    @property
    def ref(self) -> str:
        return f"{self.group}{_REF_SEPARATOR}{self.name}"


@dataclass(frozen=True)
class RedirectRuleSet:
    domain: str
    rules: tuple[RedirectRule, ...]


def group_of(ref: str) -> str:
    return ref.split(_REF_SEPARATOR, 1)[0]


def load_rules_file(path: str | Path) -> RedirectRuleSet:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    domain = data.get("domain")
    if not domain:
        raise SynologySiteError(f"{path}: missing top-level 'domain'")
    rules = tuple(_rule_from_dict(entry, source=path) for entry in data.get("rules", []))
    if not rules:
        raise SynologySiteError(f"{path}: no rules defined")
    return RedirectRuleSet(domain=domain, rules=rules)


def _rule_from_dict(entry: dict[str, Any], *, source: str | Path) -> RedirectRule:
    for required in ("group", "name", "expression", "target"):
        if required not in entry:
            raise SynologySiteError(f"{source}: rule missing required field {required!r}")
    target_data = entry["target"]
    target = RedirectTarget(kind=target_data["type"], value=target_data["value"])
    return RedirectRule(
        group=entry["group"],
        name=entry["name"],
        description=entry.get("description", ""),
        enabled=bool(entry.get("enabled", False)),
        expression=entry["expression"],
        target=target,
        status_code=int(entry.get("status_code", 301)),
        preserve_query_string=bool(entry.get("preserve_query_string", True)),
    )


def rule_to_cloudflare_payload(rule: RedirectRule) -> dict[str, Any]:
    """Builds one Cloudflare Redirect Rule object for the phase-entrypoint PUT body.

    Modeled on Cloudflare's documented Redirect Rules shape (action_parameters.from_value.
    target_url is either {"value": <static URL>} or {"expression": <rewrite expression>}) --
    not yet verified against a live response for this account. Run `--status` against the real
    zone before the first `--apply` and adjust here if the actual shape differs.
    """
    if rule.target.kind == "static":
        target_url: dict[str, str] = {"value": rule.target.value}
    else:
        target_url = {"expression": rule.target.value}
    return {
        "ref": rule.ref,
        "description": rule.description,
        "expression": rule.expression,
        "action": "redirect",
        "action_parameters": {
            "from_value": {
                "target_url": target_url,
                "status_code": rule.status_code,
                "preserve_query_string": rule.preserve_query_string,
            }
        },
        "enabled": rule.enabled,
    }


def rules_to_cloudflare_payload(rules: tuple[RedirectRule, ...]) -> list[dict[str, Any]]:
    return [rule_to_cloudflare_payload(rule) for rule in rules]


def with_group_enabled(
    live_rules: list[dict[str, Any]], *, group: str, enabled: bool
) -> list[dict[str, Any]]:
    """Pure function: returns a new rule list with every rule in `group` flipped to `enabled`,
    everything else unchanged. Operates on Cloudflare's own GET response (each rule dict already
    has the `ref` we set when it was created) -- no local rules file needed for this operation.
    """
    updated = []
    matched = False
    for rule in live_rules:
        ref = rule.get("ref", "")
        if group_of(ref) == group:
            matched = True
            updated.append({**rule, "enabled": enabled})
        else:
            updated.append(rule)
    if not matched:
        raise SynologySiteError(f"No rules found for group {group!r} in the live ruleset")
    return updated
