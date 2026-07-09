from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from synology_site.ssh_client import SSHClient

# Plugin slugs known to offload wp-content/uploads to S3 (or an S3-compatible bucket). Their
# presence means media may not live on local disk at all, so a plain rsync of wp-content/uploads
# would silently miss it -- the dry run flags this rather than assuming local media is complete.
KNOWN_S3_OFFLOAD_PLUGINS = frozenset(
    {
        "amazon-s3-and-cloudfront",
        "wp-offload-media-lite",
        "wp-offload-s3-lite",
        "wp-offload-s3",
        "human-made-s3-uploads",
        "wp-stateless",
        "media-cloud",
    }
)

_ROOT_RE = re.compile(r"root\s+([^;]+);")
_SERVER_NAME_RE = re.compile(r"server_name\s+([^;]+);")
_WP_VERSION_RE = re.compile(r"\$wp_version\s*=\s*'([^']+)'")
_PHP_VERSION_RE = re.compile(r"PHP\s+(\d+\.\d+)")


def _define_value(content: str, constant: str) -> str | None:
    pattern = re.compile(
        r"define\(\s*['\"]" + re.escape(constant) + r"['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)"
    )
    match = pattern.search(content)
    return match.group(1) if match else None


def _define_bool(content: str, constant: str) -> bool | None:
    pattern = re.compile(
        r"define\(\s*['\"]" + re.escape(constant) + r"['\"]\s*,\s*(true|false)\s*\)",
        re.IGNORECASE,
    )
    match = pattern.search(content)
    if not match:
        return None
    return match.group(1).lower() == "true"


@dataclass(frozen=True)
class WordPressDbConfig:
    db_name: str | None
    db_user: str | None
    db_host: str | None
    password_defined: bool


@dataclass(frozen=True)
class LightsailDiscovery:
    source_domain: str
    is_bitnami: bool
    nginx_config_path: str | None
    doc_root: str | None
    other_server_names_on_box: tuple[str, ...]
    php_version: str | None
    wp_cli_present: bool
    wordpress_version: str | None
    db_config: WordPressDbConfig | None
    plugins: tuple[str, ...]
    themes: tuple[str, ...]
    s3_offload_plugins: tuple[str, ...]
    uploads_size: str | None
    disable_wp_cron: bool | None
    crontab_entries: tuple[str, ...]


def _find_nginx_config(ssh: SSHClient, source_domain: str) -> str | None:
    quoted = shlex.quote(source_domain)
    # -R (not -r) dereferences symlinks -- sites-enabled entries are typically symlinks into
    # sites-available, and plain -r silently skips them, which would otherwise make a live
    # config invisible here and fall back to some unrelated sites-available match instead.
    result = ssh.run(
        f"grep -Rl {quoted} /etc/nginx/sites-enabled /etc/nginx/sites-available 2>/dev/null"
    )
    candidates = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not candidates:
        return None
    enabled = [path for path in candidates if "/sites-enabled/" in path]
    return enabled[0] if enabled else candidates[0]


def _other_server_names(ssh: SSHClient, source_domain: str) -> tuple[str, ...]:
    result = ssh.run("grep -h server_name /etc/nginx/sites-enabled/* 2>/dev/null")
    names: set[str] = set()
    for line in result.stdout.splitlines():
        match = _SERVER_NAME_RE.search(line)
        if not match:
            continue
        for name in match.group(1).split():
            name = name.strip().rstrip(";")
            if name and name != "_" and source_domain not in name:
                names.add(name)
    return tuple(sorted(names))


def _detect_php_version(ssh: SSHClient) -> str | None:
    result = ssh.run("php -v")
    if not result.ok or not result.stdout:
        result = ssh.run("/opt/bitnami/php/bin/php -v")
    match = _PHP_VERSION_RE.search(result.stdout)
    return match.group(1) if match else None


def _list_dir_entries(ssh: SSHClient, path: str) -> tuple[str, ...]:
    result = ssh.run(f"ls -1 {shlex.quote(path)} 2>/dev/null")
    if not result.stdout:
        return ()
    return tuple(sorted(line.strip() for line in result.stdout.splitlines() if line.strip()))


def _crontab_entries(ssh: SSHClient) -> tuple[str, ...]:
    result = ssh.run("crontab -l 2>/dev/null")
    lines = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)
    return tuple(lines)


def run_lightsail_discovery(ssh: SSHClient, source_domain: str) -> LightsailDiscovery:
    """Read-only discovery over an already-connected SSH session. Never writes anything.

    Every step is best-effort: a missing tool, an unreadable file, or a command that returns
    nothing just yields None/empty for that field rather than aborting the whole discovery, since
    the dry run's job is to report what it can find, not to require a fully-cooperative box.
    """
    is_bitnami = ssh.run("test -d /opt/bitnami/wordpress").ok

    nginx_config_path = _find_nginx_config(ssh, source_domain)
    doc_root: str | None = None
    if nginx_config_path:
        content = ssh.run(f"cat {shlex.quote(nginx_config_path)}").stdout
        root_match = _ROOT_RE.search(content)
        if root_match:
            doc_root = root_match.group(1).strip()

    other_server_names = _other_server_names(ssh, source_domain)
    php_version = _detect_php_version(ssh)
    wp_cli_present = ssh.run("command -v wp").ok

    wordpress_version: str | None = None
    db_config: WordPressDbConfig | None = None
    plugins: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()
    uploads_size: str | None = None
    disable_wp_cron: bool | None = None

    if doc_root:
        version_content = ssh.run(
            f"cat {shlex.quote(doc_root)}/wp-includes/version.php 2>/dev/null"
        ).stdout
        version_match = _WP_VERSION_RE.search(version_content)
        wordpress_version = version_match.group(1) if version_match else None

        wp_config_content = ssh.run(
            f"cat {shlex.quote(doc_root)}/wp-config.php 2>/dev/null"
        ).stdout
        if wp_config_content:
            db_config = WordPressDbConfig(
                db_name=_define_value(wp_config_content, "DB_NAME"),
                db_user=_define_value(wp_config_content, "DB_USER"),
                db_host=_define_value(wp_config_content, "DB_HOST"),
                password_defined="DB_PASSWORD" in wp_config_content,
            )
            disable_wp_cron = _define_bool(wp_config_content, "DISABLE_WP_CRON")

        plugins = _list_dir_entries(ssh, f"{doc_root}/wp-content/plugins")
        themes = _list_dir_entries(ssh, f"{doc_root}/wp-content/themes")
        uploads_size = ssh.run(
            f"du -sh {shlex.quote(doc_root)}/wp-content/uploads 2>/dev/null"
        ).stdout.strip() or None

    s3_offload_plugins = tuple(sorted(set(plugins) & KNOWN_S3_OFFLOAD_PLUGINS))
    crontab_entries = _crontab_entries(ssh)

    return LightsailDiscovery(
        source_domain=source_domain,
        is_bitnami=is_bitnami,
        nginx_config_path=nginx_config_path,
        doc_root=doc_root,
        other_server_names_on_box=other_server_names,
        php_version=php_version,
        wp_cli_present=wp_cli_present,
        wordpress_version=wordpress_version,
        db_config=db_config,
        plugins=plugins,
        themes=themes,
        s3_offload_plugins=s3_offload_plugins,
        uploads_size=uploads_size,
        disable_wp_cron=disable_wp_cron,
        crontab_entries=crontab_entries,
    )
