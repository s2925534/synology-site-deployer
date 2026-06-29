import pytest

from synology_site.cloudflare.domain_split import split_domain_for_zone
from synology_site.errors import SynologySiteError


def test_cloudflare_split_simple_subdomain() -> None:
    result = split_domain_for_zone("demo.example.com", "example.com")
    assert result.subdomain == "demo"
    assert result.zone_domain == "example.com"
    assert result.matches_zone is True


def test_cloudflare_split_nested_subdomain() -> None:
    result = split_domain_for_zone("app.client.example.com", "example.com")
    assert result.subdomain == "app.client"
    assert result.zone_domain == "example.com"


def test_cloudflare_split_australian_style_domain() -> None:
    result = split_domain_for_zone("tools.company.com.au", "company.com.au")
    assert result.subdomain == "tools"
    assert result.zone_domain == "company.com.au"


def test_cloudflare_split_outside_zone_warns_when_not_strict() -> None:
    result = split_domain_for_zone("demo.other.com", "example.com", strict=False)
    assert result.matches_zone is False
    assert result.warning == "demo.other.com does not end with Cloudflare zone example.com"


def test_cloudflare_split_outside_zone_fails_when_strict() -> None:
    with pytest.raises(SynologySiteError):
        split_domain_for_zone("demo.other.com", "example.com")
