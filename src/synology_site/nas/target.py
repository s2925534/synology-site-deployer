from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from synology_site.errors import SynologySiteError

NAS_ENV_FILENAME = "nas.env"
DEFAULT_TARGET_NAME = "default"

# "synology" toggles the DSM-specific docker binary/sudo/autostart lookups already in
# docker_remote.py. "generic-linux" skips those and assumes a plain `docker`/`docker compose`
# on PATH -- for a VPS, a Raspberry Pi, or any other Docker-over-SSH host that isn't a Synology.
SYSTEM_TYPES = {"synology", "generic-linux"}


@dataclass(frozen=True)
class NasTarget:
    name: str
    host: str
    port: int
    user: str
    ssh_key_path: str | None
    ssh_password: str | None
    docker_root: str
    local_base_url_host: str
    default_start_port: int
    default_end_port: int
    system_type: str = "synology"
    tailscale_enabled: bool = False
    tailscale_host: str | None = None
    ssh_access_hostname: str | None = None
    ssh_access_local_port: int = 0

    @property
    def connection_host(self) -> str:
        if self.tailscale_enabled:
            if not self.tailscale_host:
                msg = f"TAILSCALE_NAS_HOST is required for NAS target {self.name}"
                raise SynologySiteError(msg)
            return self.tailscale_host
        return self.host

    @property
    def health_check_host(self) -> str:
        """Host used to reach a Docker-published port for an active health-check request.

        Docker publishes ports on 0.0.0.0, so they're reachable on every interface the NAS
        has, including its Tailscale one -- unlike `local_base_url_host` (a fixed LAN address
        used for Cloudflare tunnel origins and human-facing "here's your local URL" messages,
        which stay LAN-scoped on purpose), a *gating* health check needs to succeed from
        wherever the deploy is actually running from. Mirrors `connection_host`'s SSH fallback
        so update/deploy don't fail their own post-deploy verification when the caller is off
        the NAS's LAN and only reachable via Tailscale.
        """
        if self.tailscale_enabled and self.tailscale_host:
            return self.tailscale_host
        return self.local_base_url_host


def _optional(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _bool(value: str | None, *, default: bool = False) -> bool:
    raw = _optional(value)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _target_from_env_file(name: str, env_file: Path, *, default: NasTarget) -> NasTarget:
    """Parse nas.env, falling back to the default target's values for anything not set.

    A workspace only needs to override the fields that actually differ (typically just
    NAS_HOST/NAS_USER/credentials) rather than duplicating every setting.
    """
    values = {key: value for key, value in dotenv_values(env_file).items() if value is not None}

    def _get(key: str, fallback: str) -> str:
        return _optional(values.get(key)) or fallback

    host_override = _optional(values.get("NAS_HOST"))
    inherits_default_host = host_override is None
    tailscale_enabled = _bool(
        values.get("TAILSCALE_ENABLED"),
        default=default.tailscale_enabled if inherits_default_host else False,
    )
    tailscale_host = _optional(values.get("TAILSCALE_NAS_HOST")) or (
        default.tailscale_host if inherits_default_host else None
    )
    ssh_access_hostname = _optional(values.get("SSH_ACCESS_HOSTNAME")) or (
        default.ssh_access_hostname if inherits_default_host else None
    )
    ssh_access_local_port = int(
        _optional(values.get("SSH_ACCESS_LOCAL_PORT"))
        or (default.ssh_access_local_port if inherits_default_host else 0)
    )
    system_type = _get("SYSTEM_TYPE", default.system_type).lower()
    if system_type not in SYSTEM_TYPES:
        msg = (
            f"Invalid SYSTEM_TYPE in {env_file}: {system_type} "
            f"(expected one of {sorted(SYSTEM_TYPES)})"
        )
        raise SynologySiteError(msg)
    if tailscale_enabled and not tailscale_host:
        msg = f"TAILSCALE_NAS_HOST is required when TAILSCALE_ENABLED=true in {env_file}"
        raise SynologySiteError(msg)

    return NasTarget(
        name=name,
        host=host_override or default.host,
        port=int(_get("NAS_PORT", str(default.port))),
        user=_get("NAS_USER", default.user),
        ssh_key_path=_optional(values.get("NAS_SSH_KEY_PATH")) or default.ssh_key_path,
        ssh_password=_optional(values.get("NAS_SSH_PASSWORD")) or default.ssh_password,
        docker_root=_get("NAS_DOCKER_ROOT", default.docker_root),
        local_base_url_host=_get("LOCAL_BASE_URL_HOST", default.local_base_url_host),
        default_start_port=int(_get("DEFAULT_START_PORT", str(default.default_start_port))),
        default_end_port=int(_get("DEFAULT_END_PORT", str(default.default_end_port))),
        system_type=system_type,
        tailscale_enabled=tailscale_enabled,
        tailscale_host=tailscale_host,
        ssh_access_hostname=ssh_access_hostname,
        ssh_access_local_port=ssh_access_local_port,
    )


def discover_nas_targets(secrets_dir: str | Path, *, default: NasTarget) -> tuple[NasTarget, ...]:
    """Scan secrets/<workspace>/nas.env for additional NAS/host targets.

    Each subdirectory of secrets_dir with a nas.env file is a target, named after the directory
    -- the same directory a matching cloudflare.env, if any, already lives in. There is no
    separate manifest, matching the Cloudflare workspace convention.
    """
    root = Path(secrets_dir)
    if not root.is_dir():
        return ()
    targets = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        env_file = child / NAS_ENV_FILENAME
        if env_file.is_file():
            targets.append(_target_from_env_file(child.name, env_file, default=default))
    return tuple(targets)


def resolve_nas_target(
    default_target: NasTarget,
    extra_targets: tuple[NasTarget, ...],
    *,
    workspace: str | None = None,
) -> NasTarget:
    """Look up a target by workspace name, falling back to the default target.

    Unlike Cloudflare account resolution, there's no natural signal in a bare domain that
    identifies which physical NAS to use, so this is name-based only. It also falls back
    silently (not an error) when the resolved workspace name has no nas.env of its own, since
    most workspaces only override Cloudflare credentials and keep using the default NAS --
    whether the workspace name is valid at all is validated once, centrally, by the caller.
    """
    if workspace is None:
        return default_target
    for target in extra_targets:
        if target.name == workspace:
            return target
    return default_target
