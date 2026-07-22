from __future__ import annotations

import gzip
import io
import json
import shlex
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path
from typing import Any

import requests
import typer
from dotenv import dotenv_values
from rich.prompt import Confirm

from synology_site.cloudflare.api import CloudflareAPI, configure_cloudflare_route
from synology_site.commands.check_nas import smart_ssh_factory
from synology_site.commands.create import CreateResult, create_site
from synology_site.config import Settings, load_config
from synology_site.database.naming import database_name, database_user
from synology_site.database.shared_mariadb import SHARED_MARIADB_CONTAINER
from synology_site.docker_remote import docker_command
from synology_site.errors import SynologySiteError
from synology_site.godaddy.api import check_nameservers
from synology_site.lightsail.credentials import extract_wordpress_credentials
from synology_site.lightsail.discovery import LightsailDiscovery, run_lightsail_discovery
from synology_site.lightsail.migration import (
    create_full_site_archive,
    dump_container_database,
    dump_host_database,
    dump_wp_content_volume,
    extract_full_site_archive,
    fetch_wp_content,
    inspect_existing_wordpress_deployment,
    push_wp_content,
    push_wp_content_to_volume,
    restore_container_database,
)
from synology_site.lightsail.report import DnsRecordInfo, render_dry_run_report
from synology_site.lightsail.source import (
    LightsailSource,
    discover_lightsail_sources,
    resolve_lightsail_source,
)
from synology_site.naming import db_container_name, domain_to_slug
from synology_site.output import console, next_step, ok, warn
from synology_site.ssh_client import SSHClient
from synology_site.validators import validate_domain

TARGET_MODES = {"new-site", "existing-site-replace"}
TRANSFER_MODES = {"direct", "full-archive"}
WP_CLI_URL = "https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar"

SSHFactory = Callable[[LightsailSource, str | None], SSHClient]
TargetSSHFactory = Callable[[Settings, str | None], SSHClient]


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


@dataclass(frozen=True)
class ExecuteResult:
    domain: str
    target_mode: str
    project_path: str
    local_url: str
    backup_paths: tuple[Path, ...] = ()
    cloudflare_configured: bool = False


def _read_remote_env(ssh: SSHClient, remote_path: str) -> dict[str, str]:
    content = ssh.run(f"cat {shlex.quote(remote_path)}", check=True).stdout
    return {
        key: value
        for key, value in dotenv_values(stream=io.StringIO(content)).items()
        if value is not None
    }


def _default_wp_cli_download() -> bytes:
    response = requests.get(WP_CLI_URL, timeout=30)
    response.raise_for_status()
    return response.content


def _render_cloudflare_rollback_doc(
    domain: str,
    prior_dns_records: list[dict[str, Any]],
    prior_ingress: list[dict[str, Any]],
) -> str:
    return (
        f"# Cloudflare Rollback -- {domain}\n\n"
        "Captured immediately before `migrate-from-lightsail --execute` changed this domain's "
        "Cloudflare DNS/tunnel routing. If the migration needs to be reverted, restore the exact "
        "prior state below via the Cloudflare dashboard (DNS tab + Zero Trust > Tunnels > "
        "Configure > Public Hostname) or by replaying these values through the Cloudflare API.\n\n"
        "## Prior DNS record(s)\n\n"
        f"```json\n{json.dumps(prior_dns_records, indent=2)}\n```\n\n"
        "## Prior tunnel ingress rules\n\n"
        f"```json\n{json.dumps(prior_ingress, indent=2)}\n```\n\n"
        "## To revert\n\n"
        "1. In the Cloudflare dashboard, delete/replace the DNS record(s) for this hostname with "
        "the exact type/content/proxied values captured above.\n"
        "2. In the tunnel's Public Hostname configuration, remove the entry this migration added "
        "and restore any ingress rule this hostname previously had (see JSON above -- if it was "
        "absent before, no ingress entry should exist for it after reverting).\n"
    )


def _snapshot_and_cutover_cloudflare(
    *,
    settings: Settings,
    target_domain: str,
    target_workspace: str | None,
    local_url: str,
    strict_cloudflare: bool,
    backup_dir: Path,
    cloudflare_session: Any,
) -> tuple[bool, Path | None]:
    account = settings.resolve_cloudflare(target_domain, workspace=target_workspace)
    if not account.ready:
        if strict_cloudflare:
            raise SynologySiteError("Cloudflare API credentials are incomplete")
        warn("Cloudflare API credentials are incomplete. Manual DNS/tunnel setup is required.")
        return False, None

    api = CloudflareAPI(account, session=cloudflare_session)
    prior_dns_records = api.get_dns_records(target_domain)
    prior_ingress = api.get_tunnel_ingress()

    target_slug_dir = backup_dir / domain_to_slug(target_domain)
    target_slug_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = target_slug_dir / "cloudflare-before.json"
    snapshot_path.write_text(
        json.dumps(
            {"dns_records": prior_dns_records, "tunnel_ingress": prior_ingress}, indent=2
        ),
        encoding="utf-8",
    )
    rollback_path = target_slug_dir / "cloudflare-rollback.md"
    rollback_path.write_text(
        _render_cloudflare_rollback_doc(target_domain, prior_dns_records, prior_ingress),
        encoding="utf-8",
    )

    configure_cloudflare_route(account, hostname=target_domain, service_url=local_url,
                                session=cloudflare_session)
    _warn_on_godaddy_nameserver_mismatch(settings, target_domain, workspace=target_workspace)
    return True, snapshot_path


def _warn_on_godaddy_nameserver_mismatch(
    settings: Settings,
    domain: str,
    *,
    workspace: str | None,
    cloudflare_session: Any = requests,
    godaddy_session: Any = requests,
) -> None:
    """Best-effort, read-only: warns if a configured GoDaddy account's nameservers for `domain`
    don't match the Cloudflare zone just cut over to. Never raises -- any failure (no GoDaddy
    account, domain not found there, network error) is swallowed; this is informational only
    and must never block a migration that otherwise succeeded.
    """
    try:
        godaddy_account = settings.resolve_godaddy(workspace=workspace)
        if not godaddy_account.ready:
            return
        cf_account = settings.resolve_cloudflare(domain, workspace=workspace)
        if not cf_account.ready:
            return
        expected = CloudflareAPI(cf_account, session=cloudflare_session).get_zone_nameservers()
        result = check_nameservers(
            godaddy_account,
            domain=domain,
            expected_nameservers=expected,
            session=godaddy_session,
        )
        if not result.matches:
            warn(
                f"GoDaddy nameservers for {domain} don't match this Cloudflare zone -- "
                f"current: {', '.join(result.current_nameservers)}; "
                f"expected: {', '.join(result.expected_nameservers)}. "
                "Run `synology-site godaddy-nameservers` to review/fix."
            )
    except Exception:  # noqa: BLE001
        pass


def run_execute(  # noqa: PLR0913
    *,
    source: LightsailSource,
    source_domain: str,
    target_domain: str,
    target_mode: str,
    settings: Settings,
    confirmed: bool,
    target_db_mode: str = "external",
    transfer_mode: str = "direct",
    force: bool = False,
    strict_cloudflare: bool = False,
    target_workspace: str | None = None,
    backup_dir: Path = Path("migration-backups"),
    secrets_dir: Path = Path("secrets"),
    source_ssh_factory: SSHFactory = default_lightsail_ssh_factory,
    target_ssh_factory: TargetSSHFactory = smart_ssh_factory,
    health_get: Callable[..., Any] = requests.get,
    cloudflare_session: Any = requests,
    source_prompted_password: str | None = None,
    target_prompted_password: str | None = None,
    wp_cli_download: Callable[[], bytes] = _default_wp_cli_download,
) -> ExecuteResult:
    if target_mode not in TARGET_MODES:
        msg = f"--target-mode must be one of {sorted(TARGET_MODES)}"
        raise SynologySiteError(msg)
    if transfer_mode not in TRANSFER_MODES:
        msg = f"--transfer-mode must be one of {sorted(TRANSFER_MODES)}"
        raise SynologySiteError(msg)
    source_domain = validate_domain(source_domain)
    target_domain = validate_domain(target_domain)

    if target_mode == "existing-site-replace" and not confirmed:
        raise SynologySiteError(
            "existing-site-replace overwrites the target's current database and wp-content. "
            "Pass --yes (after reviewing the backup that will be taken) to proceed."
        )

    target = settings.resolve_target(workspace=target_workspace)
    connection_settings = settings.resolved_for(target)

    with source_ssh_factory(source, source_prompted_password) as source_ssh:
        discovery = run_lightsail_discovery(source_ssh, source_domain)
        if discovery.s3_offload_plugins:
            msg = (
                "S3-offloaded media detected ("
                + ", ".join(discovery.s3_offload_plugins)
                + "). --execute does not talk to AWS/S3 -- sync wp-content/uploads manually "
                "first, then re-run. See docs/lightsail-migration-mvp.md."
            )
            raise SynologySiteError(msg)
        if not discovery.doc_root:
            raise SynologySiteError("Could not determine the source's WordPress document root")

        creds = extract_wordpress_credentials(source_ssh, discovery.doc_root)
        sql_dump_bytes = dump_host_database(
            source_ssh,
            db_name=creds.db_name,
            db_user=creds.db_user,
            db_password=creds.db_password,
            db_host=creds.db_host,
        )

        with tempfile.TemporaryDirectory() as tmp:
            if transfer_mode == "full-archive":
                archive_bytes = create_full_site_archive(
                    source_ssh,
                    doc_root=discovery.doc_root,
                    nginx_config_path=discovery.nginx_config_path,
                    sql_dump_bytes=sql_dump_bytes,
                )
                extracted_root = extract_full_site_archive(archive_bytes, Path(tmp))
                wp_content_dir = extracted_root / "wp-content"
                bundle_dir = extracted_root / "_migration_bundle"
                if bundle_dir.is_dir():
                    reference_dir = backup_dir / domain_to_slug(target_domain) / "source-bundle"
                    reference_dir.parent.mkdir(parents=True, exist_ok=True)
                    if reference_dir.exists():
                        shutil.rmtree(reference_dir)
                    shutil.copytree(bundle_dir, reference_dir)
            else:
                wp_content_dir = fetch_wp_content(source_ssh, discovery.doc_root, Path(tmp))

            if target_mode == "new-site":
                image_tag = (
                    f"php{discovery.php_version}-apache" if discovery.php_version else "apache"
                )
                create_result: CreateResult = create_site(
                    target_domain,
                    settings=settings,
                    framework="wordpress",
                    force=force,
                    db_mode=target_db_mode,
                    wp_table_prefix=creds.table_prefix,
                    wordpress_image_tag=image_tag,
                    workspace=target_workspace,
                    ssh_factory=target_ssh_factory,
                    health_get=health_get,
                    prompted_password=target_prompted_password,
                    secrets_dir=secrets_dir,
                )
                with target_ssh_factory(
                    connection_settings, target_prompted_password
                ) as target_ssh:
                    target_env = _read_remote_env(
                        target_ssh, f"{create_result.project_path}/app/.env"
                    )
                    target_db_container = (
                        SHARED_MARIADB_CONTAINER
                        if target_db_mode == "external"
                        else db_container_name(target_domain)
                    )
                    restore_container_database(
                        target_ssh,
                        container_name=target_db_container,
                        db_name=database_name(target_domain),
                        db_user=database_user(target_domain),
                        db_password=target_env["WORDPRESS_DB_PASSWORD"],
                        sql_text=sql_dump_bytes.decode("utf-8"),
                        drop_existing_tables=False,
                    )
                    push_wp_content(target_ssh, wp_content_dir, create_result.project_path)

                cloudflare_configured, snapshot_path = _snapshot_and_cutover_cloudflare(
                    settings=settings,
                    target_domain=target_domain,
                    target_workspace=target_workspace,
                    local_url=create_result.local_url,
                    strict_cloudflare=strict_cloudflare,
                    backup_dir=backup_dir,
                    cloudflare_session=cloudflare_session,
                )
                return ExecuteResult(
                    domain=target_domain,
                    target_mode=target_mode,
                    project_path=create_result.project_path,
                    local_url=create_result.local_url,
                    backup_paths=(snapshot_path,) if snapshot_path else (),
                    cloudflare_configured=cloudflare_configured,
                )

            # existing-site-replace. The target may or may not follow this tool's own
            # `wordpress` scaffold layout (app/.env, bind-mounted wp-content) -- it may just as
            # well be hand-deployed or `deploy`-managed, with its own Compose file that doesn't.
            # Try the fast native path first; fall back to introspecting whatever's actually
            # there via `docker compose config` (fully resolves ${VAR} interpolation itself).
            project_path = f"{target.docker_root.rstrip('/')}/{domain_to_slug(target_domain)}"
            with target_ssh_factory(connection_settings, target_prompted_password) as target_ssh:
                marker = json.loads(
                    target_ssh.run(
                        f"cat {shlex.quote(project_path)}/.synology-site.json", check=True
                    ).stdout
                )
                target_port = marker.get("port")
                compose_file = marker.get("compose_file", "docker-compose.yml")
                github_sync_repo: str | None = None

                native_env_path = f"{project_path}/app/.env"
                if target_ssh.run(f"test -f {shlex.quote(native_env_path)}").ok:
                    target_env = _read_remote_env(target_ssh, native_env_path)
                    target_db_container = target_env["WORDPRESS_DB_HOST"]
                    target_db_name = target_env["WORDPRESS_DB_NAME"]
                    target_db_user = target_env["WORDPRESS_DB_USER"]
                    target_db_password = target_env["WORDPRESS_DB_PASSWORD"]
                    target_table_prefix = target_env.get("WORDPRESS_TABLE_PREFIX", "wp_")
                    app_container = domain_to_slug(target_domain)
                    wp_content_is_volume = False
                else:
                    deployment = inspect_existing_wordpress_deployment(
                        target_ssh, project_path=project_path, compose_file=compose_file
                    )
                    target_db_container = deployment.db_host
                    target_db_name = deployment.db_name
                    target_db_user = deployment.db_user
                    target_db_password = deployment.db_password
                    target_table_prefix = deployment.table_prefix
                    app_container = deployment.container_name
                    wp_content_is_volume = deployment.wp_content_is_volume
                    github_sync_repo = deployment.github_sync_repo

                if target_table_prefix != creds.table_prefix:
                    msg = (
                        f"Source table prefix ({creds.table_prefix!r}) differs from the "
                        f"target's ({target_table_prefix!r}) -- not supported yet."
                    )
                    raise SynologySiteError(msg)

                backup_dir.mkdir(parents=True, exist_ok=True)
                target_slug_dir = backup_dir / domain_to_slug(target_domain)
                target_slug_dir.mkdir(parents=True, exist_ok=True)

                backup_sql = dump_container_database(
                    target_ssh,
                    container_name=target_db_container,
                    db_name=target_db_name,
                    db_user=target_db_user,
                    db_password=target_db_password,
                )
                backup_sql_path = target_slug_dir / "pre-overwrite-dump.sql.gz"
                backup_sql_path.write_bytes(gzip.compress(backup_sql))

                with tempfile.TemporaryDirectory() as backup_tmp:
                    if wp_content_is_volume:
                        existing_wp_content = dump_wp_content_volume(
                            target_ssh,
                            container_name=app_container,
                            local_tmp_dir=Path(backup_tmp),
                        )
                    else:
                        existing_wp_content = fetch_wp_content(
                            target_ssh, project_path, Path(backup_tmp)
                        )
                    backup_wp_content_dir = target_slug_dir / "wp-content"
                    if backup_wp_content_dir.exists():
                        shutil.rmtree(backup_wp_content_dir)
                    shutil.copytree(existing_wp_content, backup_wp_content_dir)

                restore_container_database(
                    target_ssh,
                    container_name=target_db_container,
                    db_name=target_db_name,
                    db_user=target_db_user,
                    db_password=target_db_password,
                    sql_text=sql_dump_bytes.decode("utf-8"),
                    drop_existing_tables=True,
                )

                if wp_content_is_volume:
                    push_wp_content_to_volume(
                        target_ssh,
                        wp_content_dir,
                        container_name=app_container,
                    )
                else:
                    target_ssh.run(f"rm -rf {shlex.quote(project_path)}/wp-content", check=True)
                    push_wp_content(target_ssh, wp_content_dir, project_path)

                # wp-cli.phar is copied straight into the running container's own filesystem via
                # `docker cp` -- this works regardless of how wp-content is mounted (bind mount
                # or named volume), unlike stashing it inside wp-content itself (which only
                # worked when wp-content was a host bind mount).
                docker = docker_command(target_ssh)
                wp_cli_host_path = f"/tmp/wp-cli-{domain_to_slug(target_domain)}.phar"
                wp_cli_container_path = "/tmp/wp-cli.phar"
                target_ssh.upload_bytes(wp_cli_host_path, wp_cli_download())
                target_ssh.run(
                    f"{docker} cp {shlex.quote(wp_cli_host_path)} "
                    f"{shlex.quote(app_container)}:{shlex.quote(wp_cli_container_path)}",
                    check=True,
                )
                target_ssh.run(f"rm -f {shlex.quote(wp_cli_host_path)}")
                search_replace = target_ssh.run(
                    f"{docker} exec -u www-data {shlex.quote(app_container)} php "
                    f"{shlex.quote(wp_cli_container_path)} search-replace "
                    f"{shlex.quote(source_domain)} {shlex.quote(target_domain)} "
                    "--all-tables --path=/var/www/html"
                )
                target_ssh.run(
                    f"{docker} exec {shlex.quote(app_container)} "
                    f"rm -f {shlex.quote(wp_cli_container_path)}"
                )
                if not search_replace.ok:
                    detail = search_replace.stderr or search_replace.stdout
                    raise SynologySiteError(f"wp-cli search-replace failed: {detail}")

            warn(
                "Jetpack and Google Site Kit (if active) need manual reconnection after this "
                "clone -- their connection is tied to site identity, which changed."
            )
            if github_sync_repo:
                warn(
                    f"This target has a GitHub-sync plugin wired to {github_sync_repo!r} -- "
                    "publishing or editing a post there will push it to that repo. Confirm "
                    "this is still wanted before publishing anything on the migrated content."
                )
            local_url = (
                f"http://{target.local_base_url_host}:{target_port}"
                if target_port is not None
                else f"https://{target_domain}"
            )
            return ExecuteResult(
                domain=target_domain,
                target_mode=target_mode,
                project_path=project_path,
                local_url=local_url,
                backup_paths=(backup_sql_path, backup_wp_content_dir),
                cloudflare_configured=False,
            )


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
        False,
        "--execute",
        help="Perform the actual migration -- see docs/lightsail-migration-mvp.md.",
    ),
    source_workspace: str | None = typer.Option(
        None,
        "--source-workspace",
        help="Override which secrets/<name>/lightsail.env to use "
        "(default: the source domain's own slug).",
    ),
    target_workspace: str | None = typer.Option(
        None,
        "--target-workspace",
        help="Force a specific NAS/Cloudflare workspace for the target "
        "(see secrets/<name>/). --execute only.",
    ),
    target_db_mode: str = typer.Option(
        "external",
        "--target-db-mode",
        help="'container' (dedicated MariaDB) or 'external' (shared MariaDB instance) for "
        "the target WordPress stack. --target-mode new-site only.",
    ),
    transfer_mode: str = typer.Option(
        "direct",
        "--transfer-mode",
        help="'direct' (default -- DB dump and wp-content stream straight over SSH, nothing "
        "ever written to the source's disk) or 'full-archive' (bundles the DB dump + "
        "wp-content + a best-effort copy of the Nginx vhost config and TLS cert/key into one "
        "zip on the source first, transfers that, then always deletes it from the source "
        "again -- the reference copies land in --backup-dir/<target-slug>/source-bundle/).",
    ),
    force: bool = typer.Option(
        False, "--force", help="Overwrite an existing NAS project directory. new-site only."
    ),
    strict_cloudflare: bool = typer.Option(False, "--strict-cloudflare"),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Skip the confirmation prompt before an existing-site-replace overwrite.",
    ),
    output_dir: Path = typer.Option(Path("migration-reports"), "--output-dir"),  # noqa: B008
    backup_dir: Path = typer.Option(Path("migration-backups"), "--backup-dir"),  # noqa: B008
) -> None:
    try:
        if execute and dry_run:
            raise SynologySiteError("Pass either --dry-run or --execute, not both.")
        if not execute and not dry_run:
            raise SynologySiteError("Pass --dry-run or --execute.")

        settings = load_config()
        sources = discover_lightsail_sources("secrets")
        source = resolve_lightsail_source(
            validate_domain(source_domain), sources, workspace=source_workspace
        )
        source_prompted_password = None
        if not source.ssh_key_path and not source.ssh_password:
            source_prompted_password = getpass(f"SSH password for {source.user}@{source.host}: ")

        if dry_run:
            dry_run_result = run_dry_run(
                source=source,
                source_domain=source_domain,
                target_domain=target_domain,
                target_mode=target_mode,
                settings=settings,
                output_dir=output_dir,
                prompted_password=source_prompted_password,
            )
        else:
            target = settings.resolve_target(workspace=target_workspace)
            target_prompted_password = None
            if not target.ssh_key_path and not target.ssh_password:
                target_prompted_password = getpass("NAS SSH password: ")

            confirmed = yes
            if target_mode == "existing-site-replace" and not yes:
                confirmed = Confirm.ask(
                    f"This overwrites {target_domain}'s current database and wp-content on the "
                    "NAS (a backup is taken first). Continue?",
                    default=False,
                )

            execute_result = run_execute(
                source=source,
                source_domain=source_domain,
                target_domain=target_domain,
                target_mode=target_mode,
                settings=settings,
                confirmed=confirmed,
                target_db_mode=target_db_mode,
                transfer_mode=transfer_mode,
                force=force,
                strict_cloudflare=strict_cloudflare,
                target_workspace=target_workspace,
                backup_dir=backup_dir,
                source_prompted_password=source_prompted_password,
                target_prompted_password=target_prompted_password,
            )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    if dry_run:
        console.rule("Lightsail Migration Dry Run")
        ok(f"Discovery complete for {source_domain}")
        if dry_run_result.discovery.other_server_names_on_box:
            warn(
                "Shared instance: also serves "
                + ", ".join(dry_run_result.discovery.other_server_names_on_box)
            )
        ok(f"Report written: {dry_run_result.report_path}")
        next_step("Review the report, then see docs/lightsail-migration-mvp.md for next steps.")
        return

    console.rule("Lightsail Migration Execute")
    ok(f"{execute_result.target_mode} migration complete: {execute_result.domain}")
    ok(f"Project: {execute_result.project_path}")
    ok(f"Local URL: {execute_result.local_url}")
    for path in execute_result.backup_paths:
        ok(f"Backup: {path}")
    if execute_result.target_mode == "new-site":
        if execute_result.cloudflare_configured:
            ok(
                f"Cloudflare route configured: {execute_result.domain} -> "
                f"{execute_result.local_url}"
            )
        else:
            warn("Cloudflare route not configured -- set it up manually.")
    next_step(f"Open {execute_result.local_url}")
