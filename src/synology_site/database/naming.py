from __future__ import annotations


def database_name(domain: str) -> str:
    return domain.replace(".", "_").replace("-", "_").lower()
