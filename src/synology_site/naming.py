from __future__ import annotations

from synology_site.validators import validate_domain


def domain_to_slug(domain: str) -> str:
    return validate_domain(domain).replace(".", "-")


def app_container_name(domain: str) -> str:
    return domain_to_slug(domain)


def db_container_name(domain: str) -> str:
    return f"{domain_to_slug(domain)}-db"


def db_volume_name(domain: str) -> str:
    return f"{domain_to_slug(domain)}-db-data"


def network_name(domain: str) -> str:
    return f"{domain_to_slug(domain)}-network"
