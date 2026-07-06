from __future__ import annotations

from collections import defaultdict

import typer

from synology_site.config import Settings, load_config
from synology_site.errors import SynologySiteError
from synology_site.output import console, ok, warn


def _duplicate_owners(pairs: list[tuple[str, str]]) -> dict[str, list[str]]:
    """pairs: (value, owner name). Returns {value: [owners]} for values shared by >1 owner."""
    groups: dict[str, list[str]] = defaultdict(list)
    for value, owner in pairs:
        if value:
            groups[value].append(owner)
    return {value: owners for value, owners in groups.items() if len(owners) > 1}


def check_workspaces(settings: Settings) -> list[str]:
    """Flag copy-paste credential mistakes across workspaces before they surface as a
    confusing Cloudflare API error at deploy time.

    Only checks things that are essentially never intentional. Sharing the same NAS or the
    same CF_ACCOUNT_ID across workspaces is the normal, supported multi-account/multi-domain
    setup -- not flagged here. A tunnel belonging to two different workspaces is not: tunnels
    are 1:1 with an account (see README "Multiple Cloudflare Accounts / Domains"), so a shared
    CF_TUNNEL_ID is essentially always a copy-paste mistake.
    """
    problems: list[str] = []
    accounts = (settings.default_cloudflare_account, *settings.cloudflare_accounts)

    for tunnel_id, owners in _duplicate_owners(
        [(a.tunnel_id, a.name) for a in accounts if a.tunnel_id]
    ).items():
        problems.append(
            f"CF_TUNNEL_ID {tunnel_id!r} is shared by workspaces: {', '.join(owners)} -- "
            "a tunnel belongs to one Cloudflare account, so this is almost always a "
            "copy-paste mistake"
        )
    for token, owners in _duplicate_owners(
        [(a.api_token, a.name) for a in accounts if a.api_token]
    ).items():
        problems.append(
            f"CF_API_TOKEN is identical across workspaces: {', '.join(owners)} -- if these "
            "are meant to be separate Cloudflare accounts, double-check this wasn't a "
            f"copy-paste mistake (token starts with {token[:6]!r})"
        )
    return problems


def app() -> None:
    try:
        settings = load_config()
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    account_names = {account.name for account in settings.cloudflare_accounts}
    target_names = {target.name for target in settings.nas_targets}

    console.rule("Workspaces")
    for name in sorted(settings.known_workspace_names):
        if name == "default":
            ok(
                f"{name}: Cloudflare account ({settings.default_cloudflare_account.zone_domain}, "
                f"ready={settings.default_cloudflare_account.ready}), "
                f"NAS target ({settings.default_nas_target.host})"
            )
            continue
        parts = []
        if name in account_names:
            account = next(a for a in settings.cloudflare_accounts if a.name == name)
            parts.append(f"Cloudflare account ({account.zone_domain}, ready={account.ready})")
        if name in target_names:
            target = next(t for t in settings.nas_targets if t.name == name)
            parts.append(f"NAS target ({target.host})")
        ok(f"{name}: {'; '.join(parts)}")

    console.rule("Doctor")
    problems = check_workspaces(settings)
    if not problems:
        ok("No duplicate-credential issues detected")
    for problem in problems:
        warn(problem)
