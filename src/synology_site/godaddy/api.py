from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from synology_site.errors import SynologySiteError
from synology_site.godaddy.workspace import GoDaddyAccount


@dataclass(frozen=True)
class NameserverCheckResult:
    domain: str
    current_nameservers: tuple[str, ...]
    expected_nameservers: tuple[str, ...]
    matches: bool


class GoDaddyAPI:
    def __init__(self, account: GoDaddyAccount, session: Any = requests) -> None:
        if not account.ready:
            raise SynologySiteError("GoDaddy API credentials are incomplete")
        self.account = account
        self.session = session

    @property
    def headers(self) -> dict[str, str]:
        if self.account.access_token:
            auth = f"Bearer {self.account.access_token}"
        else:
            auth = f"sso-key {self.account.api_key}:{self.account.api_secret}"
        return {"Authorization": auth, "Content-Type": "application/json"}

    def get_domain(self, domain: str) -> dict[str, Any]:
        """Read-only lookup of a domain's registration details, including its nameservers."""
        return self._request("GET", f"{self.account.base_url}/v3/domains/{domain}")

    def get_nameservers(self, domain: str) -> list[str]:
        return list(self.get_domain(domain).get("nameServers") or [])

    def update_nameservers(self, domain: str, nameservers: list[str]) -> None:
        """Writes new nameservers for domain. The highest-blast-radius call in this module --
        callers must snapshot the current nameservers and gate this behind explicit
        confirmation before ever calling it (see update_domain_nameservers below).
        """
        self._request(
            "PATCH",
            f"{self.account.base_url}/v3/domains/{domain}",
            json={"nameServers": nameservers},
        )

    def list_dns_records(
        self, domain: str, *, record_type: str | None = None, name: str | None = None
    ) -> list[dict[str, Any]]:
        """Read-only. Only meaningful for domains where GoDaddy itself hosts DNS -- delegated
        domains (nameservers pointed elsewhere) have no records here."""
        url = f"{self.account.base_url}/v3/domains/{domain}/records"
        if record_type and name:
            url = f"{url}/{record_type}/{name}"
        elif record_type:
            url = f"{url}/{record_type}"
        result = self._request("GET", url)
        return list(result) if isinstance(result, list) else []

    def replace_dns_records(
        self, domain: str, record_type: str, name: str, records: list[dict[str, Any]]
    ) -> None:
        self._request(
            "PUT",
            f"{self.account.base_url}/v3/domains/{domain}/records/{record_type}/{name}",
            json=records,
        )

    def add_dns_records(self, domain: str, records: list[dict[str, Any]]) -> None:
        self._request(
            "POST",
            f"{self.account.base_url}/v3/domains/{domain}/records",
            json=records,
        )

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        response = self.session.request(method, url, headers=self.headers, timeout=30, **kwargs)
        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = payload.get("message", "unknown error")
            except ValueError:
                detail = response.text or "unknown error"
            msg = f"GoDaddy API request failed ({response.status_code}): {detail}"
            raise SynologySiteError(msg)
        if response.status_code == 204:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            msg = "GoDaddy API returned invalid JSON"
            raise SynologySiteError(msg) from exc


def check_nameservers(
    account: GoDaddyAccount,
    *,
    domain: str,
    expected_nameservers: list[str],
    session: Any = requests,
) -> NameserverCheckResult:
    """Read-only comparison of a domain's current GoDaddy-registered nameservers against an
    expected set. Never writes anything."""
    current = GoDaddyAPI(account, session=session).get_nameservers(domain)
    normalized_current = {ns.rstrip(".").lower() for ns in current}
    normalized_expected = {ns.rstrip(".").lower() for ns in expected_nameservers}
    return NameserverCheckResult(
        domain=domain,
        current_nameservers=tuple(current),
        expected_nameservers=tuple(expected_nameservers),
        matches=normalized_current == normalized_expected,
    )


def update_domain_nameservers(
    account: GoDaddyAccount,
    *,
    domain: str,
    nameservers: list[str],
    confirmed: bool,
    session: Any = requests,
) -> None:
    """Writes new nameservers for domain. Refuses to run unless the caller explicitly passes
    confirmed=True -- there is no default, every call site must decide out loud. Callers are
    expected to have already snapshotted the current nameservers before calling this (see
    commands/godaddy_nameservers.py for the snapshot + confirmation sequence).
    """
    if not confirmed:
        raise SynologySiteError(
            "Nameserver changes are not confirmed. This can take a domain's DNS offline for "
            "hours with no instant rollback -- pass confirmed=True only after reviewing a "
            "snapshot of the current nameservers."
        )
    GoDaddyAPI(account, session=session).update_nameservers(domain, nameservers)
