from __future__ import annotations

import typer

from synology_site.config import load_config
from synology_site.errors import SynologySiteError
from synology_site.godaddy.api import GoDaddyAPI
from synology_site.output import console, ok
from synology_site.validators import validate_domain

# Standalone DNS record management for domains where GoDaddy itself still hosts DNS (nameservers
# NOT delegated to Cloudflare/AWS/etc). For delegated domains, DNS lives at the delegate instead
# -- this command has nothing to manage there. Lower blast radius than nameserver changes (a
# single record, not the whole domain's resolution), so no confirmation gate here, matching how
# Cloudflare DNS records are already managed elsewhere in this tool without one.


def _parse_record(spec: str) -> dict[str, object]:
    parts = [part.strip() for part in spec.split(",")]
    if len(parts) < 3:
        msg = f"Invalid record spec (want type,name,data[,ttl]): {spec!r}"
        raise SynologySiteError(msg)
    record_type, name, data = parts[0], parts[1], parts[2]
    record: dict[str, object] = {"type": record_type.upper(), "name": name, "data": data}
    if len(parts) >= 4 and parts[3]:
        record["ttl"] = int(parts[3])
    return record


def app(
    domain: str,
    list_records: bool = typer.Option(False, "--list", help="Read-only: list all DNS records."),
    add: list[str] = typer.Option(  # noqa: B008
        [], "--add", help="type,name,data[,ttl] -- repeatable. Adds new record(s)."
    ),
    replace: list[str] = typer.Option(  # noqa: B008
        [],
        "--replace",
        help="type,name,data[,ttl] -- repeatable. Replaces all records of that type/name.",
    ),
    workspace: str | None = typer.Option(
        None, "--workspace", help="Force a specific GoDaddy workspace (see secrets/<name>/)"
    ),
) -> None:
    if not list_records and not add and not replace:
        console.print("[ERROR] Pass --list, --add, or --replace.")
        raise typer.Exit(1)

    try:
        domain = validate_domain(domain)
        settings = load_config()
        account = settings.resolve_godaddy(workspace=workspace)
        api = GoDaddyAPI(account)

        if list_records:
            records = api.list_dns_records(domain)
        if add:
            api.add_dns_records(domain, [_parse_record(spec) for spec in add])
        for spec in replace:
            record = _parse_record(spec)
            api.replace_dns_records(domain, record["type"], record["name"], [record])
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("GoDaddy DNS")
    if list_records:
        for record in records:
            ok(f"{record.get('type')} {record.get('name')} -> {record.get('data')}")
    if add:
        ok(f"Added {len(add)} record(s)")
    if replace:
        ok(f"Replaced {len(replace)} record(s)")
