from __future__ import annotations

from synology_site.commands.uptime_kuma_monitor import build_uptime_kuma_monitor_instructions


def test_build_uptime_kuma_monitor_instructions_with_known_kuma_url() -> None:
    instructions = build_uptime_kuma_monitor_instructions(
        "app.example.com",
        kuma_url="http://192.0.2.10:5051",
        interval_seconds=30,
        retries=2,
    )

    assert "http://192.0.2.10:5051" in instructions
    assert "https://app.example.com" in instructions
    assert "30 seconds" in instructions
    assert "Retries: 2" in instructions
    assert "Docker Container" in instructions
    assert "docker.sock" in instructions


def test_build_uptime_kuma_monitor_instructions_without_known_kuma_url() -> None:
    instructions = build_uptime_kuma_monitor_instructions(
        "app.example.com",
        kuma_url=None,
        interval_seconds=60,
        retries=3,
    )

    assert "synology-site list" in instructions
    assert "https://app.example.com" in instructions
