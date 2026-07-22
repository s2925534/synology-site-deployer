from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

GODADDY_ENV_FILENAME = "godaddy.env"
DEFAULT_WORKSPACE_NAME = "default"


@dataclass(frozen=True)
class GoDaddyAccount:
    name: str
    access_token: str | None
    api_key: str | None
    api_secret: str | None
    environment: str = "production"

    @property
    def ready(self) -> bool:
        return bool(self.access_token) or bool(self.api_key and self.api_secret)

    @property
    def base_url(self) -> str:
        if self.environment == "ote":
            return "https://api.ote-godaddy.com"
        return "https://api.godaddy.com"


def _optional(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    return value.strip()


def _account_from_env_file(name: str, env_file: Path) -> GoDaddyAccount:
    values = {key: value for key, value in dotenv_values(env_file).items() if value is not None}
    return GoDaddyAccount(
        name=name,
        access_token=_optional(values.get("GD_ACCESS_TOKEN")),
        api_key=_optional(values.get("GD_API_KEY")),
        api_secret=_optional(values.get("GD_API_SECRET")),
        environment=(values.get("GD_ENVIRONMENT") or "production").strip().lower(),
    )


def discover_godaddy_accounts(
    secrets_dir: str | Path = "secrets",
) -> tuple[GoDaddyAccount, ...]:
    """Scan secrets/<workspace>/godaddy.env for additional GoDaddy accounts.

    Unlike Cloudflare's zone-per-workspace convention, a GoDaddy account isn't scoped to one
    domain -- there's no local domain-to-account mapping to maintain, the API itself is the
    source of truth for which domains an account can manage (a 404/403 on the wrong account is
    a clearer signal than a guessed mapping). Resolution is by explicit --workspace only.
    """
    root = Path(secrets_dir)
    if not root.is_dir():
        return ()
    accounts = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        env_file = child / GODADDY_ENV_FILENAME
        if env_file.is_file():
            accounts.append(_account_from_env_file(child.name, env_file))
    return tuple(accounts)


def resolve_godaddy_account(
    default_account: GoDaddyAccount,
    extra_accounts: tuple[GoDaddyAccount, ...],
    *,
    workspace: str | None = None,
) -> GoDaddyAccount:
    if workspace is not None:
        for account in extra_accounts:
            if account.name == workspace:
                return account
    return default_account
