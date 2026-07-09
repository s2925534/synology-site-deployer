from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from synology_site.errors import SynologySiteError
from synology_site.naming import domain_to_slug

LIGHTSAIL_ENV_FILENAME = "lightsail.env"


@dataclass(frozen=True)
class LightsailSource:
    name: str
    host: str
    port: int
    user: str
    ssh_key_path: str | None
    ssh_password: str | None


def _optional(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _source_from_env_file(name: str, env_file: Path) -> LightsailSource:
    values = {key: value for key, value in dotenv_values(env_file).items() if value is not None}
    host = _optional(values.get("LIGHTSAIL_HOST"))
    user = _optional(values.get("LIGHTSAIL_USER"))
    if not host or not user:
        msg = f"LIGHTSAIL_HOST and LIGHTSAIL_USER are required in {env_file}"
        raise SynologySiteError(msg)
    port = _optional(values.get("LIGHTSAIL_PORT"))
    return LightsailSource(
        name=name,
        host=host,
        port=int(port) if port else 22,
        user=user,
        ssh_key_path=_optional(values.get("LIGHTSAIL_SSH_KEY_PATH")),
        ssh_password=_optional(values.get("LIGHTSAIL_SSH_PASSWORD")),
    )


def discover_lightsail_sources(
    secrets_dir: str | Path = "secrets",
) -> tuple[LightsailSource, ...]:
    """Scan secrets/<workspace>/lightsail.env for known Lightsail migration sources.

    Each subdirectory of secrets_dir with a lightsail.env file is a source, named after the
    directory -- by convention the same directory a matching cloudflare.env/aws.env for that
    domain already lives in, and named after the source domain's own slug (e.g. veloso-dev for
    veloso.dev), so a bare --source-domain resolves without an extra flag in the common case.
    """
    root = Path(secrets_dir)
    if not root.is_dir():
        return ()
    sources = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        env_file = child / LIGHTSAIL_ENV_FILENAME
        if env_file.is_file():
            sources.append(_source_from_env_file(child.name, env_file))
    return tuple(sources)


def resolve_lightsail_source(
    source_domain: str,
    sources: tuple[LightsailSource, ...],
    *,
    workspace: str | None = None,
) -> LightsailSource:
    """Look up the Lightsail source for a domain, by explicit workspace or by slug convention.

    Falls back to matching the source domain's own slug (domain_to_slug) against known
    workspace names -- no separate manifest, same convention as Cloudflare/NAS workspaces.
    """
    lookup_name = workspace or domain_to_slug(source_domain)
    for source in sources:
        if source.name == lookup_name:
            return source
    msg = (
        f"No Lightsail source configured for {source_domain!r} "
        f"(expected secrets/{lookup_name}/{LIGHTSAIL_ENV_FILENAME})"
    )
    raise SynologySiteError(msg)
