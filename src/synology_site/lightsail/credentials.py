from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from synology_site.errors import SynologySiteError
from synology_site.ssh_client import SSHClient

# Deliberately separate from discovery.py: run_lightsail_discovery/WordPressDbConfig are used by
# --dry-run and intentionally never read the real DB_PASSWORD value (only whether it's defined).
# extract_wordpress_credentials is execute-only -- it's the one place in this codebase allowed to
# read that secret off the source box, and it must never be called from the dry-run path.

_TABLE_PREFIX_RE = re.compile(r"\$table_prefix\s*=\s*['\"]([^'\"]*)['\"]")


def _define_value(content: str, constant: str) -> str | None:
    pattern = re.compile(
        r"define\(\s*['\"]" + re.escape(constant) + r"['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)"
    )
    match = pattern.search(content)
    return match.group(1) if match else None


@dataclass(frozen=True)
class LightsailWordPressCredentials:
    db_name: str
    db_user: str
    db_password: str
    db_host: str
    table_prefix: str


def extract_wordpress_credentials(ssh: SSHClient, doc_root: str) -> LightsailWordPressCredentials:
    content = ssh.run(f"cat {shlex.quote(doc_root)}/wp-config.php", check=True).stdout
    db_name = _define_value(content, "DB_NAME")
    db_user = _define_value(content, "DB_USER")
    db_password = _define_value(content, "DB_PASSWORD")
    db_host = _define_value(content, "DB_HOST") or "localhost"
    if not db_name or not db_user or not db_password:
        msg = "Could not extract DB_NAME/DB_USER/DB_PASSWORD from wp-config.php"
        raise SynologySiteError(msg)
    prefix_match = _TABLE_PREFIX_RE.search(content)
    table_prefix = prefix_match.group(1) if prefix_match else "wp_"
    return LightsailWordPressCredentials(
        db_name=db_name,
        db_user=db_user,
        db_password=db_password,
        db_host=db_host,
        table_prefix=table_prefix,
    )
