from __future__ import annotations


def domain_to_slug(domain: str) -> str:
    return domain.replace(".", "-").lower()
