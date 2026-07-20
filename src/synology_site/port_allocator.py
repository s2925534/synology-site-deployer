from __future__ import annotations

import re

from synology_site.docker_remote import docker_command
from synology_site.errors import SynologySiteError
from synology_site.site_registry import fetch_markers, registered_ports
from synology_site.ssh_client import SSHClient

_PORT_PATTERNS = [
    re.compile(r"(?:(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]|\*)\:)(?P<port>\d+)->"),
    re.compile(r"(?:(?:0\.0\.0\.0|127\.0\.0\.1|\[::\]|\*)\:)(?P<port>\d+)\s"),
    re.compile(r":(?P<port>\d+)\s"),
]


def parse_used_ports(*outputs: str) -> set[int]:
    ports: set[int] = set()
    for output in outputs:
        for line in output.splitlines():
            for pattern in _PORT_PATTERNS:
                for match in pattern.finditer(line):
                    port = int(match.group("port"))
                    if 1 <= port <= 65535:
                        ports.add(port)
    return ports


def collect_used_ports(ssh: SSHClient) -> set[int]:
    outputs: list[str] = []
    docker = docker_command(ssh)
    for command in [
        f"{docker} ps --format '{{{{.Ports}}}}'",
        "ss -ltn",
        "netstat -ltn",
    ]:
        result = ssh.run(command)
        if result.ok:
            outputs.append(result.stdout)
    return parse_used_ports(*outputs)


def choose_port(start: int, end: int, used_ports: set[int] | None = None) -> int:
    used = used_ports or set()
    for port in range(start, end + 1):
        if port not in used:
            return port
    msg = f"No available port found in range {start}-{end}"
    raise SynologySiteError(msg)


def describe_port_conflict(
    port: int,
    *,
    used_ports: set[int],
    registered: dict[int, str],
    domain: str | None = None,
) -> str | None:
    """None if `port` is free to hand out; otherwise a message explaining why not.

    Two independent sources feed this, and are reported distinctly since they call for
    different fixes: `used_ports` (a live docker ps/ss/netstat scan -- catches anything
    listening right now, including sites never deployed by this tool at all) and
    `registered` (every known `.synology-site.json` marker's own port -- catches a site
    that owns this port but happens to be stopped right now, which a live-only scan can't
    see). A port registered to `domain` itself is not a conflict (that's the normal
    redeploy-in-place case).
    """
    if port in used_ports:
        return f"Requested port {port} is already in use on the NAS"
    owner = registered.get(port)
    if owner is not None and owner != domain:
        return (
            f"Requested port {port} is already registered to {owner} (from its "
            ".synology-site.json marker), even though nothing is currently running on it -- "
            "pick a different port to avoid a future collision when that site is restarted."
        )
    return None


def find_available_port(
    ssh: SSHClient,
    *,
    start: int,
    end: int,
    requested: int | None = None,
    docker_root: str | None = None,
    domain: str | None = None,
) -> int:
    used_ports = collect_used_ports(ssh)
    registered: dict[int, str] = {}
    if docker_root is not None:
        try:
            registered = registered_ports(fetch_markers(ssh, docker_root))
        except SynologySiteError:
            # Best-effort safety net on top of the live scan above, not a hard dependency --
            # a marker read failing shouldn't block a deploy the live scan alone would allow.
            registered = {}

    if requested is not None:
        conflict = describe_port_conflict(
            requested, used_ports=used_ports, registered=registered, domain=domain
        )
        if conflict is not None:
            raise SynologySiteError(conflict)
        return requested
    return choose_port(start, end, used_ports | set(registered))
