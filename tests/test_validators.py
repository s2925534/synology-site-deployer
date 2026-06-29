import pytest

from synology_site.errors import SynologySiteError
from synology_site.validators import validate_domain


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("demo.example.com", "demo.example.com"),
        ("APP-01.Example.com", "app-01.example.com"),
        ("tools.company.com.au", "tools.company.com.au"),
    ],
)
def test_validate_domain_accepts_valid_domains(domain: str, expected: str) -> None:
    assert validate_domain(domain) == expected


@pytest.mark.parametrize(
    "domain",
    [
        "",
        "bad domain.example.com",
        "bad_domain.example.com",
        ".example.com",
        "example.com.",
        "demo..example.com",
        "-demo.example.com",
        "demo-.example.com",
        "localhost",
        f"{'a' * 64}.example.com",
    ],
)
def test_validate_domain_rejects_invalid_domains(domain: str) -> None:
    with pytest.raises(SynologySiteError):
        validate_domain(domain)
