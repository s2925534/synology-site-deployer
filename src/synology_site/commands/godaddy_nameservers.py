from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests
import typer
from rich.prompt import Confirm

from synology_site.cloudflare.api import CloudflareAPI
from synology_site.config import load_config
from synology_site.errors import SynologySiteError
from synology_site.godaddy.api import GoDaddyAPI, check_nameservers, update_domain_nameservers
from synology_site.output import console, ok, warn
from synology_site.validators import validate_domain

# Standalone, no NAS/SSH interaction -- same shape as commands/cloudflare_route.py. `--check`
# (read-only, the safe default) compares GoDaddy's current nameservers for a domain against an
# expected set, either passed explicitly or read live from that domain's Cloudflare zone.
# `--set` is the one write path in this whole tool with the highest blast radius: a wrong
# nameserver set can take a domain's DNS fully offline for hours with no instant rollback. It
# always snapshots the current nameservers to disk first and always requires explicit
# confirmation -- never runs automatically from any other command.


def _rollback_doc(domain: str, prior_nameservers: list[str], new_nameservers: list[str]) -> str:
    return (
        f"# GoDaddy Nameserver Rollback -- {domain}\n\n"
        "Captured immediately before `godaddy-nameservers --set` changed this domain's "
        "nameservers at the registrar. If this needs to be reverted, set the nameservers back "
        "to the exact prior values below via the GoDaddy dashboard or "
        "`godaddy-nameservers --set` again with these values.\n\n"
        f"## Prior nameservers\n\n```\n{chr(10).join(prior_nameservers)}\n```\n\n"
        f"## New nameservers (just set)\n\n```\n{chr(10).join(new_nameservers)}\n```\n"
    )


def run_check(
    domain: str,
    *,
    account: Any,
    expected_nameservers: list[str],
    session: Any = requests,
) -> Any:
    return check_nameservers(
        account, domain=domain, expected_nameservers=expected_nameservers, session=session
    )


def run_set(
    domain: str,
    *,
    account: Any,
    nameservers: list[str],
    confirmed: bool,
    backup_dir: Path = Path("godaddy-backups"),
    session: Any = requests,
) -> Path:
    """Snapshots the domain's current nameservers to backup_dir/<domain>/ before writing, then
    calls update_domain_nameservers (which itself refuses to run unless confirmed=True)."""
    current = GoDaddyAPI(account, session=session).get_nameservers(domain)

    domain_dir = backup_dir / domain
    domain_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = domain_dir / "nameservers-before.json"
    snapshot_path.write_text(
        json.dumps({"domain": domain, "nameservers": current}, indent=2), encoding="utf-8"
    )
    (domain_dir / "rollback.md").write_text(
        _rollback_doc(domain, current, nameservers), encoding="utf-8"
    )

    update_domain_nameservers(
        account, domain=domain, nameservers=nameservers, confirmed=confirmed, session=session
    )
    return snapshot_path


def app(
    domain: str,
    check: bool = typer.Option(
        False, "--check", help="Read-only: compare current GoDaddy nameservers against expected."
    ),
    expected_nameservers: str | None = typer.Option(
        None,
        "--expected-nameservers",
        help="Comma-separated nameservers to compare against. --check only.",
    ),
    expected_provider: str | None = typer.Option(
        None,
        "--expected-provider",
        help="'cloudflare' -- reads expected nameservers live from that domain's configured "
        "Cloudflare zone instead of --expected-nameservers. --check only.",
    ),
    set_nameservers: str | None = typer.Option(
        None,
        "--set",
        help="Comma-separated nameservers to write. Snapshots the current ones first and "
        "requires --yes or an interactive confirmation -- this can take the domain's DNS "
        "offline for hours if wrong.",
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Skip the interactive confirmation prompt for --set."
    ),
    workspace: str | None = typer.Option(
        None, "--workspace", help="Force a specific GoDaddy workspace (see secrets/<name>/)"
    ),
    backup_dir: Path = typer.Option(Path("godaddy-backups"), "--backup-dir"),  # noqa: B008
) -> None:
    if not check and not set_nameservers:
        console.print("[ERROR] Pass --check or --set.")
        raise typer.Exit(1)
    if check and set_nameservers:
        console.print("[ERROR] Pass either --check or --set, not both.")
        raise typer.Exit(1)

    try:
        domain = validate_domain(domain)
        settings = load_config()
        account = settings.resolve_godaddy(workspace=workspace)

        if check:
            if expected_provider and expected_provider != "cloudflare":
                raise SynologySiteError("--expected-provider only supports 'cloudflare'")
            if expected_provider == "cloudflare":
                cf_account = settings.resolve_cloudflare(domain)
                expected = CloudflareAPI(cf_account).get_zone_nameservers()
            elif expected_nameservers:
                expected = [ns.strip() for ns in expected_nameservers.split(",") if ns.strip()]
            else:
                raise SynologySiteError(
                    "--check requires --expected-nameservers or --expected-provider cloudflare"
                )
            result = run_check(domain, account=account, expected_nameservers=expected)
        else:
            nameservers = [ns.strip() for ns in (set_nameservers or "").split(",") if ns.strip()]
            if not nameservers:
                raise SynologySiteError("--set requires a non-empty comma-separated list")
            confirmed = yes or Confirm.ask(
                f"Set {domain}'s nameservers to {', '.join(nameservers)}? This can take the "
                "domain's DNS offline for hours if wrong.",
                default=False,
            )
            if not confirmed:
                raise SynologySiteError("Not confirmed -- no changes made.")
            snapshot_path = run_set(
                domain,
                account=account,
                nameservers=nameservers,
                confirmed=confirmed,
                backup_dir=backup_dir,
            )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    if check:
        console.rule("GoDaddy Nameserver Check")
        ok(f"Domain: {result.domain}")
        ok(f"Current: {', '.join(result.current_nameservers)}")
        ok(f"Expected: {', '.join(result.expected_nameservers)}")
        if result.matches:
            ok("Nameservers match.")
        else:
            warn("Nameservers do NOT match.")
    else:
        console.rule("GoDaddy Nameserver Update")
        ok(f"Nameservers updated for {domain}")
        ok(f"Prior nameservers snapshotted: {snapshot_path}")
        warn("DNS propagation can take hours -- verify resolution before relying on this.")
