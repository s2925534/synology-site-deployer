from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GeneratedFile:
    path: str
    content: str
    secret: bool = False


@dataclass(frozen=True)
class ScaffoldContext:
    domain: str
    slug: str
    framework: str
    port: int
    project_path: str
    local_base_url_host: str
    restart_policy: str
    db_enabled: bool = False
    db_mode: str = "none"
    db_type: str = "mariadb"
    db_image: str = "mariadb:11"
    db_name: str | None = None
    db_user: str | None = None
    db_password: str | None = None
    db_root_password: str | None = None
    db_publish_port: bool = False
    db_host_port: int | None = None
    cloudflare_attempted: bool = True
    cloudflare_configured: bool = False
    cloudflare_manual_required: bool = True
