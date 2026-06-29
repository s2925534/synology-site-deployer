from __future__ import annotations


def choose_port(start: int, _end: int, used_ports: set[int] | None = None) -> int:
    used = used_ports or set()
    if start in used:
        msg = f"Port {start} is already in use"
        raise ValueError(msg)
    return start
