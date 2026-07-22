from __future__ import annotations

from dataclasses import dataclass

from synology_site import __version__
from synology_site.database.naming import database_name, database_user
from synology_site.database.shared_mariadb import SHARED_MARIADB_CONTAINER, SHARED_MARIADB_NETWORK
from synology_site.naming import (
    db_container_name,
    db_volume_name,
    network_name,
    redis_container_name,
    redis_volume_name,
)

# "none" -- no frontend framework, just the backend (default).
# "livewire" / "inertia-vue" / "inertia-react" -- single container, glue lives inside the same
#   Laravel app (Livewire components, or Inertia pages rendered by Laravel controllers).
# "vue" / "react" / "angular" -- a fully decoupled SPA: independently-built frontend + a Laravel
#   API backend (via Breeze's "api" stack, Sanctum-ready), served together through nginx
#   (static assets + /api proxy to PHP-FPM). Requires --php-server fpm-nginx, since artisan's
#   single dev server has no static-file/proxy split.
SINGLE_CONTAINER_FRONTENDS = {"livewire", "inertia-vue", "inertia-react"}
DECOUPLED_SPA_FRONTENDS = {"vue", "react", "angular"}
FRONTENDS = {"none", *SINGLE_CONTAINER_FRONTENDS, *DECOUPLED_SPA_FRONTENDS}


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
    php_server: str = "artisan"
    frontend: str = "none"
    redis_enabled: bool = False
    queue_enabled: bool = False
    scheduler_enabled: bool = False
    wp_table_prefix: str = "wp_"
    wordpress_image_tag: str = "apache"


def common_template_values(context: ScaffoldContext, *, internal_port: int) -> dict[str, object]:
    """Template values shared by every scaffold, independent of the target framework.

    `db_mode` is one of "none" (no database), "container" (this site gets its own
    dedicated MariaDB container, the original/default behavior), or "external" (the app
    instead connects to the single shared MariaDB instance bootstrapped once via
    `bootstrap-mariadb` -- no per-site db service is generated, and the app additionally
    joins `shared_db_network` alongside its own private `db_network`).
    """
    db_name = context.db_name or database_name(context.domain)
    db_user = context.db_user or database_user(context.domain)
    db_container = (
        SHARED_MARIADB_CONTAINER
        if context.db_mode == "external"
        else db_container_name(context.domain)
    )
    # Whether this site's own private network (db_network) is actually needed:
    # true for a dedicated db container or redis, but a pure external-db site with no
    # redis needs only the shared network, so it doesn't get an unused empty network.
    needs_private_network = context.db_mode == "container" or context.redis_enabled
    needs_shared_network = context.db_mode == "external"
    return {
        "version": __version__,
        "domain": context.domain,
        "slug": context.slug,
        "framework": context.framework,
        "port": context.port,
        "internal_port": internal_port,
        "project_path": context.project_path,
        "local_base_url_host": context.local_base_url_host,
        "local_url": f"http://{context.local_base_url_host}:{context.port}",
        "public_url": f"https://{context.domain}",
        "restart_policy": context.restart_policy,
        "db_enabled": context.db_enabled,
        "db_mode": context.db_mode,
        "db_type": context.db_type,
        "db_image": context.db_image,
        "db_container": db_container,
        "db_name": db_name,
        "db_user": db_user,
        "db_password": context.db_password or "",
        "db_root_password": context.db_root_password or "",
        "db_volume": db_volume_name(context.domain),
        "db_network": network_name(context.domain),
        "shared_db_network": SHARED_MARIADB_NETWORK,
        "needs_private_network": needs_private_network,
        "needs_shared_network": needs_shared_network,
        "db_publish_port": context.db_publish_port,
        "db_host_port": context.db_host_port,
        "redis_enabled": context.redis_enabled,
        "redis_container": redis_container_name(context.domain),
        "redis_volume": redis_volume_name(context.domain),
        "queue_enabled": context.queue_enabled,
        "scheduler_enabled": context.scheduler_enabled,
        "cloudflare_attempted": context.cloudflare_attempted,
        "cloudflare_configured": context.cloudflare_configured,
        "cloudflare_manual_required": context.cloudflare_manual_required,
        "wp_table_prefix": context.wp_table_prefix,
        "wordpress_image_tag": context.wordpress_image_tag,
    }
