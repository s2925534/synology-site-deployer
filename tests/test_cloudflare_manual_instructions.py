from synology_site.cloudflare.manual_instructions import build_manual_instructions


def test_manual_cloudflare_instructions_simple_domain() -> None:
    text = build_manual_instructions(
        "demo.example.com",
        "example.com",
        "192.0.2.10",
        5051,
        "my-nas-tunnel",
    )

    assert "Cloudflare manual setup required" in text
    assert "Subdomain: demo" in text
    assert "Domain: example.com" in text
    assert "Service type: HTTP" in text
    assert "Service URL: 192.0.2.10:5051" in text
    assert "demo.example.com    Tunnel    my-nas-tunnel    Proxied" in text
    assert "Cloudflare Error 1033" in text
    assert "http://192.0.2.10:5051" in text


def test_manual_cloudflare_instructions_nested_subdomain() -> None:
    text = build_manual_instructions(
        "app.client.example.com",
        "example.com",
        "192.0.2.10",
        5051,
        "my-nas-tunnel",
    )

    assert "Subdomain: app.client" in text
    assert "Domain: example.com" in text


def test_manual_cloudflare_instructions_australian_style_domain() -> None:
    text = build_manual_instructions(
        "tools.company.com.au",
        "company.com.au",
        "192.0.2.10",
        5051,
        "my-nas-tunnel",
    )

    assert "Subdomain: tools" in text
    assert "Domain: company.com.au" in text


def test_manual_cloudflare_instructions_warns_outside_zone() -> None:
    text = build_manual_instructions(
        "demo.other.com",
        "example.com",
        "192.0.2.10",
        5051,
        "my-nas-tunnel",
    )

    assert "[WARN] demo.other.com does not end with Cloudflare zone example.com" in text
