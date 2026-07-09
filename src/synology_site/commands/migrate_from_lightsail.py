from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path

import typer

from synology_site.cloudflare.api import CloudflareAPI
from synology_site.config import Settings, load_config
from synology_site.errors import SynologySiteError
from synology_site.lightsail.discovery import LightsailDiscovery, run_lightsail_discovery
from synology_site.lightsail.report import DnsRecordInfo, render_dry_run_report
from synology_site.lightsail.source import (
    LightsailSource,
    discover_lightsail_sources,
    resolve_lightsail_source,
)
from synology_site.naming import domain_to_slug
from synology_site.output import console, next_step, ok, warn
from synology_site.ssh_client import SSHClient
from synology_site.validators import validate_domain

TARGET_MODES = {"new-site", "existing-site-replace"}

SSHFactory = Callable[[LightsailSource, str | None], SSHClient]


def default_lightsail_ssh_factory(
    source: LightsailSource, prompted_password: str | None = None
) -> SSHClient:
    password = source.ssh_password or prompted_password
    return SSHClient(
        source.host,
        source.port,
        source.user,
        key_path=source.ssh_key_path,
        password=password,
    )


@dataclass(frozen=True)
class DryRunResult:
    discovery: LightsailDiscovery
    report_path: Path
    report: str


def _lookup_dns_records(
    settings: Settings, source_domain: str
) -> tuple[bool, tuple[DnsRecordInfo, ...]]:
    account = settings.resolve_cloudflare(source_domain)
    if not account.ready:
        return False, ()
    api = CloudflareAPI(account)
    records = api.get_dns_records(source_domain)
    return True, tuple(
        DnsRecordInfo(
            record_type=record.get("type", "?"),
            name=record.get("name", source_domain),
            content=record.get("content", "?"),
            proxied=bool(record.get("proxied", False)),
        )
        for record in records
    )


def run_dry_run(
    *,
    source: LightsailSource,
    source_domain: str,
    target_domain: str,
    target_mode: str,
    settings: Settings,
    output_dir: Path = Path("migration-reports"),
    ssh_factory: SSHFactory = default_lightsail_ssh_factory,
    prompted_password: str | None = None,
    dns_lookup: Callable[
        [Settings, str], tuple[bool, tuple[DnsRecordInfo, ...]]
    ] = _lookup_dns_records,
) -> DryRunResult:
    if target_mode not in TARGET_MODES:
        msg = f"--target-mode must be one of {sorted(TARGET_MODES)}"
        raise SynologySiteError(msg)

    source_domain = validate_domain(source_domain)
    target_domain = validate_domain(target_domain)

    with ssh_factory(source, prompted_password) as ssh:
        discovery = run_lightsail_discovery(ssh, source_domain)

    dns_checked, dns_records = dns_lookup(settings, source_domain)

    report = render_dry_run_report(
        discovery,
        target_domain=target_domain,
        target_mode=target_mode,
        dns_records=dns_records,
        dns_checked=dns_checked,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    source_slug = domain_to_slug(source_domain)
    target_slug = domain_to_slug(target_domain)
    report_path = output_dir / f"{source_slug}-to-{target_slug}-dry-run.md"
    report_path.write_text(report, encoding="utf-8")

    return DryRunResult(discovery=discovery, report_path=report_path, report=report)


def app(
    source_domain: str = typer.Option(
        ..., "--source-domain", help="Domain currently on Lightsail."
    ),
    target_domain: str = typer.Option(..., "--target-domain", help="Domain to land on the NAS."),
    target_mode: str = typer.Option(
        ...,
        "--target-mode",
        help="'new-site' (same domain, fresh NAS deploy) or 'existing-site-replace' "
        "(clone onto an already-running-but-empty NAS site).",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Read-only discovery over SSH + Cloudflare API. No writes."
    ),
    execute: bool = typer.Option(
        False, "--execute", help="Not implemented yet -- see docs/lightsail-migration-mvp.md."
    ),
    source_workspace: str | None = typer.Option(
        None,
        "--source-workspace",
        help="Override which secrets/<name>/lightsail.env to use "
        "(default: the source domain's own slug).",
    ),
    output_dir: Path = typer.Option(Path("migration-reports"), "--output-dir"),  # noqa: B008
) -> None:
    try:
        if execute:
            raise SynologySiteError(
                "--execute is not implemented yet. Only --dry-run (read-only discovery) is "
                "currently supported -- see docs/lightsail-migration-mvp.md."
            )
        if not dry_run:
            raise SynologySiteError("Pass --dry-run (the only currently supported mode).")

        settings = load_config()
        sources = discover_lightsail_sources("secrets")
        source = resolve_lightsail_source(
            validate_domain(source_domain), sources, workspace=source_workspace
        )
        prompted_password = None
        if not source.ssh_key_path and not source.ssh_password:
            prompted_password = getpass(f"SSH password for {source.user}@{source.host}: ")

        result = run_dry_run(
            source=source,
            source_domain=source_domain,
            target_domain=target_domain,
            target_mode=target_mode,
            settings=settings,
            output_dir=output_dir,
            prompted_password=prompted_password,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Lightsail Migration Dry Run")
    ok(f"Discovery complete for {source_domain}")
    if result.discovery.other_server_names_on_box:
        warn(
            "Shared instance: also serves "
            + ", ".join(result.discovery.other_server_names_on_box)
        )
    ok(f"Report written: {result.report_path}")
    next_step("Review the report, then see docs/lightsail-migration-mvp.md for next steps.")
