from __future__ import annotations

from synology_site.validators import validate_domain


def database_name(domain: str) -> str:
    return validate_domain(domain).replace(".", "_").replace("-", "_")


def database_user(domain: str) -> str:
    return f"{database_name(domain)}_user"
