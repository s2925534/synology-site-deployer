from __future__ import annotations

import re

from synology_site.errors import SynologySiteError
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
    for command in [
        "docker ps --format '{{.Ports}}'",
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


def find_available_port(
    ssh: SSHClient,
    *,
    start: int,
    end: int,
    requested: int | None = None,
) -> int:
    used_ports = collect_used_ports(ssh)
    if requested is not None:
        if requested in used_ports:
            msg = f"Requested port {requested} is already in use on the NAS"
            raise SynologySiteError(msg)
        return requested
    return choose_port(start, end, used_ports)
