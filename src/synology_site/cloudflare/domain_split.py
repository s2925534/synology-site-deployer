from __future__ import annotations

from dataclasses import dataclass

from synology_site.errors import SynologySiteError
from synology_site.validators import validate_domain


@dataclass(frozen=True)
class CloudflareDomainSplit:
    domain: str
    zone_domain: str
    subdomain: str
    matches_zone: bool
    warning: str | None = None


def split_domain_for_zone(
    domain: str,
    zone_domain: str,
    *,
    strict: bool = True,
) -> CloudflareDomainSplit:
    normalized_domain = validate_domain(domain)
    normalized_zone = validate_domain(zone_domain)
    suffix = f".{normalized_zone}"

    if normalized_domain == normalized_zone:
        return CloudflareDomainSplit(
            domain=normalized_domain,
            zone_domain=normalized_zone,
            subdomain="",
            matches_zone=True,
        )

    if normalized_domain.endswith(suffix):
        return CloudflareDomainSplit(
            domain=normalized_domain,
            zone_domain=normalized_zone,
            subdomain=normalized_domain[: -len(suffix)],
            matches_zone=True,
        )

    warning = f"{normalized_domain} does not end with Cloudflare zone {normalized_zone}"
    if strict:
        raise SynologySiteError(warning)
    return CloudflareDomainSplit(
        domain=normalized_domain,
        zone_domain=normalized_zone,
        subdomain=normalized_domain,
        matches_zone=False,
        warning=warning,
    )
