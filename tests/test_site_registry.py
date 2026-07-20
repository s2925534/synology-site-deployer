from __future__ import annotations

from synology_site.site_registry import registered_ports


def test_registered_ports_maps_port_to_domain() -> None:
    markers = [
        {"domain": "a.example.com", "port": 5051, "slug": "a-example-com"},
        {"domain": "b.example.com", "port": 5052, "slug": "b-example-com"},
    ]

    assert registered_ports(markers) == {5051: "a.example.com", 5052: "b.example.com"}


def test_registered_ports_skips_markers_with_no_port() -> None:
    markers = [{"domain": "reverse-proxy-fronted.example.com", "port": None}]

    assert registered_ports(markers) == {}


def test_registered_ports_last_marker_wins_on_port_collision() -> None:
    # Two markers should never legitimately share a port -- if they do (e.g. leftover state
    # from a manual NAS edit), this just documents the tie-break rather than raising, since
    # `registered_ports` is a pure lookup, not a validator.
    markers = [
        {"domain": "old.example.com", "port": 5051},
        {"domain": "new.example.com", "port": 5051},
    ]

    assert registered_ports(markers) == {5051: "new.example.com"}
