from __future__ import annotations

from dataclasses import dataclass

from synology_site.lightsail.discovery import LightsailDiscovery


@dataclass(frozen=True)
class DnsRecordInfo:
    record_type: str
    name: str
    content: str
    proxied: bool


def render_dry_run_report(
    discovery: LightsailDiscovery,
    *,
    target_domain: str,
    target_mode: str,
    dns_records: tuple[DnsRecordInfo, ...] | None,
    dns_checked: bool,
) -> str:
    lines: list[str] = []
    lines.append(
        f"# Lightsail -> NAS Migration Dry Run: {discovery.source_domain} -> {target_domain}"
    )
    lines.append("")
    lines.append(f"Target mode: `{target_mode}`. Read-only discovery, no writes performed.")
    lines.append("")

    lines.append("## Instance Shape")
    lines.append("")
    layout = (
        "Bitnami (/opt/bitnami/wordpress)"
        if discovery.is_bitnami
        else "stock (hand-rolled Nginx, not Bitnami)"
    )
    lines.append(f"- Layout: {layout}")
    lines.append(f"- Nginx config: `{discovery.nginx_config_path or 'not found'}`")
    lines.append(f"- Document root: `{discovery.doc_root or 'not found'}`")
    lines.append(f"- PHP version: {discovery.php_version or 'unknown'}")
    lines.append(f"- WP-CLI installed: {'yes' if discovery.wp_cli_present else 'no'}")
    lines.append(f"- WordPress version: {discovery.wordpress_version or 'unknown'}")
    lines.append("")

    if discovery.other_server_names_on_box:
        lines.append("## Shared Instance Warning")
        lines.append("")
        others = ", ".join(f"`{name}`" for name in discovery.other_server_names_on_box)
        lines.append(
            f"This box also serves other live hostnames: {others}. This instance cannot be "
            "decommissioned once the source domain moves -- every migration step must stay "
            "scoped to the source domain's own files/DB only."
        )
        lines.append("")

    lines.append("## Database")
    lines.append("")
    if discovery.db_config is None:
        lines.append("- Could not read `wp-config.php` (document root unknown or unreadable).")
    else:
        db = discovery.db_config
        lines.append(f"- DB_NAME: `{db.db_name or 'unknown'}`")
        lines.append(f"- DB_USER: `{db.db_user or 'unknown'}`")
        lines.append(f"- DB_HOST: `{db.db_host or 'unknown'}`")
        lines.append(
            f"- DB_PASSWORD defined: {'yes' if db.password_defined else 'no'} "
            "(value never read or reported)"
        )
    lines.append("")

    lines.append("## Media / wp-content/uploads")
    lines.append("")
    if discovery.s3_offload_plugins:
        offloaders = ", ".join(f"`{name}`" for name in discovery.s3_offload_plugins)
        lines.append(
            f"- S3 offload plugin(s) detected: {offloaders}. Media may not be fully present on "
            "local disk -- confirm the bucket/prefix before assuming a plain rsync is sufficient."
        )
    else:
        lines.append("- No known S3 offload plugin detected; media is likely plain local files.")
    lines.append(f"- `wp-content/uploads` size: {discovery.uploads_size or 'unknown'}")
    lines.append("")

    lines.append("## Plugins")
    lines.append("")
    if discovery.plugins:
        for plugin in discovery.plugins:
            lines.append(f"- {plugin}")
    else:
        lines.append("- None found (or document root unreadable)")
    lines.append("")

    lines.append("## Themes")
    lines.append("")
    if discovery.themes:
        for theme in discovery.themes:
            lines.append(f"- {theme}")
    else:
        lines.append("- None found (or document root unreadable)")
    lines.append("")

    lines.append("## Cron")
    lines.append("")
    disable_wp_cron = discovery.disable_wp_cron
    if disable_wp_cron is None:
        lines.append(
            "- `DISABLE_WP_CRON` not set in `wp-config.php` -- WordPress pseudo-cron is active."
        )
    elif disable_wp_cron:
        lines.append(
            "- `DISABLE_WP_CRON` is `true` -- a real system cron/task must drive `wp-cron.php`."
        )
    else:
        lines.append(
            "- `DISABLE_WP_CRON` is explicitly `false` -- WordPress pseudo-cron is active."
        )
    if discovery.crontab_entries:
        lines.append("- System crontab entries:")
        for entry in discovery.crontab_entries:
            lines.append(f"  - `{entry}`")
    else:
        lines.append("- No system crontab entries found for this user.")
    lines.append("")

    lines.append("## Cloudflare DNS")
    lines.append("")
    if not dns_checked:
        lines.append(
            "- Skipped: no Cloudflare API credentials configured for this domain "
            "(Zone:Read is enough for this check)."
        )
    elif not dns_records:
        lines.append("- No existing DNS records found for this hostname.")
    else:
        for record in dns_records:
            lines.append(
                f"- {record.record_type} `{record.name}` -> `{record.content}` "
                f"(proxied: {'yes' if record.proxied else 'no'})"
            )
    lines.append("")

    lines.append("## Open Items")
    lines.append("")
    lines.append(
        "- NAS-side checks (disk headroom, which NAS target workspace this lands on) are not "
        "automated by this dry run yet -- confirm manually before running `--execute`."
    )
    if target_mode == "existing-site-replace":
        lines.append(
            "- `existing-site-replace` requires a serialization-safe search-replace "
            "(e.g. `wp search-replace`) once imported on the NAS -- a plain SQL `REPLACE()` "
            "will corrupt serialized page-builder data if any plugin listed above stores it. "
            "`--execute` already handles this automatically."
        )
    lines.append(
        "- `--execute` performs the actual migration (DB dump/restore, wp-content transfer, "
        "Compose scaffold for new-site, Cloudflare cutover) -- this dry run only reports what "
        "it would need to do."
    )
    lines.append("")

    return "\n".join(lines)
