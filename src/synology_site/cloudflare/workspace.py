from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from synology_site.errors import SynologySiteError

CLOUDFLARE_ENV_FILENAME = "cloudflare.env"
DEFAULT_WORKSPACE_NAME = "default"


@dataclass(frozen=True)
class CloudflareAccount:
    name: str
    api_token: str | None
    account_id: str | None
    zone_id: str | None
    zone_domain: str
    tunnel_id: str | None
    tunnel_name: str

    @property
    def ready(self) -> bool:
        return all([self.api_token, self.account_id, self.zone_id, self.tunnel_id])


def _optional(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _account_from_env_file(name: str, env_file: Path) -> CloudflareAccount:
    values = {key: value for key, value in dotenv_values(env_file).items() if value is not None}
    zone_domain = _optional(values.get("CF_ZONE_DOMAIN"))
    if not zone_domain:
        msg = f"Missing CF_ZONE_DOMAIN in {env_file}"
        raise SynologySiteError(msg)
    return CloudflareAccount(
        name=name,
        api_token=_optional(values.get("CF_API_TOKEN")),
        account_id=_optional(values.get("CF_ACCOUNT_ID")),
        zone_id=_optional(values.get("CF_ZONE_ID")),
        zone_domain=zone_domain.lower(),
        tunnel_id=_optional(values.get("CF_TUNNEL_ID")),
        tunnel_name=(values.get("CF_TUNNEL_NAME") or "cloudflared").strip(),
    )


def discover_cloudflare_accounts(
    secrets_dir: str | Path = "secrets",
) -> tuple[CloudflareAccount, ...]:
    """Scan secrets/<workspace>/cloudflare.env for additional Cloudflare accounts.

    Each subdirectory of secrets_dir with a cloudflare.env file is a workspace, named after
    the directory. There is no separate manifest: the workspace's own CF_ZONE_DOMAIN is both
    its identity and the value used to match incoming domains to it.
    """
    root = Path(secrets_dir)
    if not root.is_dir():
        return ()
    accounts = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        env_file = child / CLOUDFLARE_ENV_FILENAME
        if env_file.is_file():
            accounts.append(_account_from_env_file(child.name, env_file))
    return tuple(accounts)


def resolve_cloudflare_account(
    domain: str,
    default_account: CloudflareAccount,
    extra_accounts: tuple[CloudflareAccount, ...],
    *,
    workspace: str | None = None,
) -> CloudflareAccount:
    candidates = (default_account, *extra_accounts)
    if workspace is not None:
        for account in candidates:
            if account.name == workspace:
                return account
        msg = f"Unknown Cloudflare workspace: {workspace}"
        raise SynologySiteError(msg)

    normalized_domain = domain.lower()
    matches = [
        account
        for account in candidates
        if normalized_domain == account.zone_domain
        or normalized_domain.endswith(f".{account.zone_domain}")
    ]
    if not matches:
        return default_account
    return max(matches, key=lambda account: len(account.zone_domain))
