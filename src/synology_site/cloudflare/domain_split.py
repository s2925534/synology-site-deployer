from __future__ import annotations


def split_domain_for_zone(domain: str, zone_domain: str) -> tuple[str, str]:
    suffix = f".{zone_domain}"
    if domain == zone_domain:
        return "", zone_domain
    if not domain.endswith(suffix):
        msg = f"{domain} is outside Cloudflare zone {zone_domain}"
        raise ValueError(msg)
    return domain[: -len(suffix)], zone_domain
