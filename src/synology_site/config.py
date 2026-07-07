from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from synology_site.cloudflare.workspace import (
    DEFAULT_WORKSPACE_NAME,
    CloudflareAccount,
    discover_cloudflare_accounts,
    resolve_cloudflare_account,
)
from synology_site.errors import SynologySiteError
from synology_site.nas.target import (
    DEFAULT_TARGET_NAME,
    NasTarget,
    discover_nas_targets,
    resolve_nas_target,
)


@dataclass(frozen=True)
class Settings:
    nas_host: str
    nas_port: int
    nas_user: str
    nas_docker_root: str
    nas_ssh_key_path: str | None
    nas_ssh_password: str | None
    local_base_url_host: str
    default_start_port: int
    default_end_port: int
    default_framework: str
    restart_policy: str
    cf_api_token: str | None
    cf_account_id: str | None
    cf_zone_id: str | None
    cf_zone_domain: str
    cf_tunnel_id: str | None
    cf_tunnel_name: str
    db_mode: str
    db_type: str
    db_image: str
    db_password_length: int
    db_publish_port: bool
    db_host_port: int | None
    allow_overwrite: bool
    dry_run: bool
    default_site_domain: str | None = None
    tailscale_enabled: bool = False
    tailscale_host: str | None = None
    ssh_access_hostname: str | None = None
    ssh_access_local_port: int = 0
    notify_webhook_url: str | None = None
    notify_webhook_events: str = "success,failure"
    cloudflare_accounts: tuple[CloudflareAccount, ...] = ()
    nas_targets: tuple[NasTarget, ...] = ()

    @property
    def nas_connection_host(self) -> str:
        if self.tailscale_enabled:
            if not self.tailscale_host:
                msg = "TAILSCALE_NAS_HOST is required when TAILSCALE_ENABLED=true"
                raise SynologySiteError(msg)
            return self.tailscale_host
        return self.nas_host

    @property
    def default_cloudflare_account(self) -> CloudflareAccount:
        return CloudflareAccount(
            name=DEFAULT_WORKSPACE_NAME,
            api_token=self.cf_api_token,
            account_id=self.cf_account_id,
            zone_id=self.cf_zone_id,
            zone_domain=self.cf_zone_domain,
            tunnel_id=self.cf_tunnel_id,
            tunnel_name=self.cf_tunnel_name,
        )

    @property
    def default_nas_target(self) -> NasTarget:
        return NasTarget(
            name=DEFAULT_TARGET_NAME,
            host=self.nas_host,
            port=self.nas_port,
            user=self.nas_user,
            ssh_key_path=self.nas_ssh_key_path,
            ssh_password=self.nas_ssh_password,
            docker_root=self.nas_docker_root,
            local_base_url_host=self.local_base_url_host,
            default_start_port=self.default_start_port,
            default_end_port=self.default_end_port,
            tailscale_enabled=self.tailscale_enabled,
            tailscale_host=self.tailscale_host,
            ssh_access_hostname=self.ssh_access_hostname,
            ssh_access_local_port=self.ssh_access_local_port,
        )

    @property
    def known_workspace_names(self) -> set[str]:
        return (
            {DEFAULT_WORKSPACE_NAME}
            | {account.name for account in self.cloudflare_accounts}
            | {target.name for target in self.nas_targets}
        )

    def validate_workspace(self, workspace: str | None) -> None:
        if workspace is not None and workspace not in self.known_workspace_names:
            msg = f"Unknown workspace: {workspace}"
            raise SynologySiteError(msg)

    def resolve_cloudflare(self, domain: str, *, workspace: str | None = None) -> CloudflareAccount:
        self.validate_workspace(workspace)
        return resolve_cloudflare_account(
            domain,
            self.default_cloudflare_account,
            self.cloudflare_accounts,
            workspace=workspace,
        )

    def resolve_target(self, *, workspace: str | None = None) -> NasTarget:
        self.validate_workspace(workspace)
        return resolve_nas_target(
            self.default_nas_target,
            self.nas_targets,
            workspace=workspace,
        )


def _read_env_file(path: str | Path = ".env") -> dict[str, str]:
    values = dotenv_values(path)
    return {key: value for key, value in values.items() if value is not None}


def _merged_env(path: str | Path = ".env") -> dict[str, str]:
    values = _read_env_file(path)
    if Path(path) == Path(".env"):
        values.update({key: value for key, value in os.environ.items() if value is not None})
    return values


def _optional(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _required(values: dict[str, str], key: str) -> str:
    value = _optional(values.get(key))
    if not value:
        msg = f"Missing required configuration value: {key}"
        raise SynologySiteError(msg)
    return value


def _int(values: dict[str, str], key: str, default: int | None = None) -> int:
    raw = _optional(values.get(key))
    if raw is None:
        if default is None:
            msg = f"Missing required integer configuration value: {key}"
            raise SynologySiteError(msg)
        return default
    try:
        return int(raw)
    except ValueError as exc:
        msg = f"Invalid integer for {key}: {raw}"
        raise SynologySiteError(msg) from exc


def _bool(values: dict[str, str], key: str, default: bool = False) -> bool:
    raw = _optional(values.get(key))
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def load_config(path: str | Path = ".env", secrets_dir: str | Path = "secrets") -> Settings:
    values = _merged_env(path)
    start_port = _int(values, "DEFAULT_START_PORT", 5050)
    end_port = _int(values, "DEFAULT_END_PORT", 5999)
    if start_port > end_port:
        msg = "DEFAULT_START_PORT must be less than or equal to DEFAULT_END_PORT"
        raise SynologySiteError(msg)

    db_mode = values.get("DB_MODE", "none").strip().lower()
    if db_mode not in {"none", "container", "external"}:
        msg = "DB_MODE must be one of: none, container, external"
        raise SynologySiteError(msg)

    db_host_port = _optional(values.get("DB_HOST_PORT"))

    nas_host = _required(values, "NAS_HOST")
    nas_port = _int(values, "NAS_PORT", 22)
    nas_user = _required(values, "NAS_USER")
    nas_docker_root = _required(values, "NAS_DOCKER_ROOT")
    nas_ssh_key_path = _optional(values.get("NAS_SSH_KEY_PATH"))
    nas_ssh_password = _optional(values.get("NAS_SSH_PASSWORD"))
    local_base_url_host = _required(values, "LOCAL_BASE_URL_HOST")
    tailscale_enabled = _bool(values, "TAILSCALE_ENABLED", False)
    tailscale_host = _optional(values.get("TAILSCALE_NAS_HOST"))
    if tailscale_enabled and not tailscale_host:
        msg = "TAILSCALE_NAS_HOST is required when TAILSCALE_ENABLED=true"
        raise SynologySiteError(msg)
    ssh_access_hostname = _optional(values.get("SSH_ACCESS_HOSTNAME"))
    ssh_access_local_port = _int(values, "SSH_ACCESS_LOCAL_PORT", 0)
    notify_events = values.get("NOTIFY_WEBHOOK_EVENTS", "success,failure").strip().lower()
    default_nas_target = NasTarget(
        name=DEFAULT_TARGET_NAME,
        host=nas_host,
        port=nas_port,
        user=nas_user,
        ssh_key_path=nas_ssh_key_path,
        ssh_password=nas_ssh_password,
        docker_root=nas_docker_root,
        local_base_url_host=local_base_url_host,
        default_start_port=start_port,
        default_end_port=end_port,
        tailscale_enabled=tailscale_enabled,
        tailscale_host=tailscale_host,
        ssh_access_hostname=ssh_access_hostname,
        ssh_access_local_port=ssh_access_local_port,
    )

    return Settings(
        nas_host=nas_host,
        nas_port=nas_port,
        nas_user=nas_user,
        nas_docker_root=nas_docker_root,
        nas_ssh_key_path=nas_ssh_key_path,
        nas_ssh_password=nas_ssh_password,
        local_base_url_host=local_base_url_host,
        default_start_port=start_port,
        default_end_port=end_port,
        default_framework=values.get("DEFAULT_FRAMEWORK", "flask").strip().lower(),
        restart_policy=values.get("DEFAULT_CONTAINER_RESTART_POLICY", "unless-stopped").strip(),
        cf_api_token=_optional(values.get("CF_API_TOKEN")),
        cf_account_id=_optional(values.get("CF_ACCOUNT_ID")),
        cf_zone_id=_optional(values.get("CF_ZONE_ID")),
        cf_zone_domain=_required(values, "CF_ZONE_DOMAIN").lower(),
        cf_tunnel_id=_optional(values.get("CF_TUNNEL_ID")),
        cf_tunnel_name=values.get("CF_TUNNEL_NAME", "cloudflared").strip(),
        db_mode=db_mode,
        db_type=values.get("DB_TYPE", "mariadb").strip().lower(),
        db_image=values.get("DB_IMAGE", "mariadb:11").strip(),
        db_password_length=_int(values, "DB_PASSWORD_LENGTH", 32),
        db_publish_port=_bool(values, "DB_PUBLISH_PORT", False),
        db_host_port=int(db_host_port) if db_host_port else None,
        allow_overwrite=_bool(values, "ALLOW_OVERWRITE", False),
        dry_run=_bool(values, "DRY_RUN", False),
        default_site_domain=_optional(values.get("DEFAULT_SITE_DOMAIN")),
        tailscale_enabled=tailscale_enabled,
        tailscale_host=tailscale_host,
        ssh_access_hostname=ssh_access_hostname,
        ssh_access_local_port=ssh_access_local_port,
        notify_webhook_url=_optional(values.get("NOTIFY_WEBHOOK_URL")),
        notify_webhook_events=notify_events,
        cloudflare_accounts=discover_cloudflare_accounts(secrets_dir),
        nas_targets=discover_nas_targets(secrets_dir, default=default_nas_target),
    )
