from __future__ import annotations

import re

from synology_site.errors import SynologySiteError

_DOMAIN_RE = re.compile(r"^[a-z0-9.-]+$", re.IGNORECASE)


def apply_default_site_domain(name: str, default_site_domain: str | None) -> str:
    """Expand a bare subdomain label (no dots) into a full domain.

    e.g. "app" + "veloso.dev" -> "app.veloso.dev". Names that already look
    like a full domain (contain a dot) are left untouched.
    """
    candidate = name.strip()
    if default_site_domain and "." not in candidate:
        return f"{candidate}.{default_site_domain}"
    return candidate


def validate_domain(domain: str) -> str:
    normalized = domain.strip().lower()
    if not normalized:
        raise SynologySiteError("Domain is required")
    if normalized != domain.lower():
        raise SynologySiteError("Domain must not contain leading or trailing whitespace")
    if not _DOMAIN_RE.fullmatch(normalized):
        raise SynologySiteError("Domain may only contain letters, numbers, dots, and hyphens")
    if normalized.startswith(".") or normalized.endswith("."):
        raise SynologySiteError("Domain must not start or end with a dot")
    if ".." in normalized:
        raise SynologySiteError("Domain must not contain empty labels")
    if len(normalized) > 253:
        raise SynologySiteError("Domain is longer than the DNS limit")

    labels = normalized.split(".")
    if len(labels) < 2:
        raise SynologySiteError("Domain must include at least two labels")
    for label in labels:
        if len(label) > 63:
            raise SynologySiteError("Domain labels must be 63 characters or fewer")
        if label.startswith("-") or label.endswith("-"):
            raise SynologySiteError("Domain labels must not start or end with a hyphen")
    return normalized
