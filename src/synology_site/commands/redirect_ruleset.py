from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
import typer
from rich.prompt import Confirm
from rich.table import Table

from synology_site.cloudflare.api import CloudflareAPI
from synology_site.cloudflare.redirects import (
    REDIRECT_PHASE,
    group_of,
    load_rules_file,
    rules_to_cloudflare_payload,
    with_group_enabled,
)
from synology_site.config import load_config
from synology_site.errors import SynologySiteError
from synology_site.output import console, ok, warn
from synology_site.validators import validate_domain

# Same shape as commands/godaddy_nameservers.py: --status is the read-only, always-safe default;
# --apply/--enable-group/--disable-group are the write paths, each snapshotting the zone's prior
# redirect-rule state to disk before touching anything, each requiring --yes or an interactive
# confirmation. Every write replaces the *entire* rule list for the zone's redirect phase (see
# CloudflareAPI.set_redirect_ruleset_rules) -- these functions always fetch the live set first and
# always send the full set back, never a partial one.


def _snapshot(domain: str, live_rules: list[dict[str, Any]], backup_dir: Path) -> Path:
    domain_dir = backup_dir / domain
    domain_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = domain_dir / f"ruleset-before-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    snapshot_path.write_text(
        json.dumps({"domain": domain, "rules": live_rules}, indent=2), encoding="utf-8"
    )
    return snapshot_path


def run_status(domain: str, *, account: Any, session: Any = requests) -> list[dict[str, Any]]:
    api = CloudflareAPI(account, session=session)
    return api.get_redirect_ruleset(REDIRECT_PHASE)


def run_apply(
    domain: str,
    *,
    account: Any,
    rules_file: Path,
    confirmed: bool,
    backup_dir: Path = Path("redirect-backups"),
    session: Any = requests,
) -> Path:
    if not confirmed:
        raise SynologySiteError("Not confirmed -- no changes made.")
    api = CloudflareAPI(account, session=session)
    rule_set = load_rules_file(rules_file)
    live_rules = api.get_redirect_ruleset(REDIRECT_PHASE)
    snapshot_path = _snapshot(domain, live_rules, backup_dir)
    api.set_redirect_ruleset_rules(REDIRECT_PHASE, rules_to_cloudflare_payload(rule_set.rules))
    return snapshot_path


def run_set_group_enabled(
    domain: str,
    *,
    account: Any,
    group: str,
    enabled: bool,
    confirmed: bool,
    backup_dir: Path = Path("redirect-backups"),
    session: Any = requests,
) -> Path:
    if not confirmed:
        raise SynologySiteError("Not confirmed -- no changes made.")
    api = CloudflareAPI(account, session=session)
    live_rules = api.get_redirect_ruleset(REDIRECT_PHASE)
    snapshot_path = _snapshot(domain, live_rules, backup_dir)
    updated = with_group_enabled(live_rules, group=group, enabled=enabled)
    api.set_redirect_ruleset_rules(REDIRECT_PHASE, updated)
    return snapshot_path


def app(
    domain: str,
    status: bool = typer.Option(
        False, "--status", help="Read-only: list the zone's current redirect rules."
    ),
    apply_rules: Path | None = typer.Option(  # noqa: B008
        None,
        "--apply",
        help="Path to a rules JSON file (see redirects/*.json for the format). Replaces the "
        "zone's entire redirect-rule set with what's in the file. Requires --yes.",
    ),
    enable_group: str | None = typer.Option(
        None,
        "--enable-group",
        help="Flip every rule in this group to enabled, leaving all other rules untouched. "
        "Requires --yes. Reusable across domains -- works from the zone's live rules alone, no "
        "rules file needed.",
    ),
    disable_group: str | None = typer.Option(
        None,
        "--disable-group",
        help="Flip every rule in this group to disabled, leaving all other rules untouched. "
        "Requires --yes.",
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Skip the interactive confirmation prompt for a write."
    ),
    workspace: str | None = typer.Option(
        None, "--workspace", help="Force a specific Cloudflare workspace (see secrets/<name>/)"
    ),
    backup_dir: Path = typer.Option(Path("redirect-backups"), "--backup-dir"),  # noqa: B008
) -> None:
    modes = [
        name
        for name, value in [
            ("--status", status),
            ("--apply", apply_rules is not None),
            ("--enable-group", enable_group is not None),
            ("--disable-group", disable_group is not None),
        ]
        if value
    ]
    if len(modes) != 1:
        console.print(
            "[ERROR] Pass exactly one of --status, --apply, --enable-group, --disable-group."
        )
        raise typer.Exit(1)

    try:
        domain = validate_domain(domain)
        settings = load_config()
        account = settings.resolve_cloudflare(domain, workspace=workspace)

        if status:
            rules = run_status(domain, account=account)
        elif apply_rules is not None:
            confirmed = yes or Confirm.ask(
                f"Replace ALL redirect rules on {domain}'s zone with the contents of "
                f"{apply_rules}? Any rule not in that file will be removed.",
                default=False,
            )
            snapshot_path = run_apply(
                domain,
                account=account,
                rules_file=apply_rules,
                confirmed=confirmed,
                backup_dir=backup_dir,
            )
        else:
            group = enable_group or disable_group
            enabling = enable_group is not None
            confirmed = yes or Confirm.ask(
                f"{'Enable' if enabling else 'Disable'} every redirect rule in group "
                f"{group!r} on {domain}'s zone?",
                default=False,
            )
            assert group is not None  # guaranteed by the `modes` check above
            snapshot_path = run_set_group_enabled(
                domain,
                account=account,
                group=group,
                enabled=enabling,
                confirmed=confirmed,
                backup_dir=backup_dir,
            )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    if status:
        console.rule(f"Redirect Rules -- {domain}")
        if not rules:
            warn("No redirect rules exist on this zone's phase entrypoint yet.")
        else:
            table = Table(show_header=True)
            table.add_column("ref")
            table.add_column("group")
            table.add_column("enabled")
            table.add_column("description")
            for rule in rules:
                ref = rule.get("ref", "")
                table.add_row(
                    ref,
                    group_of(ref),
                    "yes" if rule.get("enabled") else "no",
                    rule.get("description", ""),
                )
            console.print(table)
    else:
        console.rule(f"Redirect Rules -- {domain}")
        ok("Applied.")
        ok(f"Prior state snapshotted: {snapshot_path}")
