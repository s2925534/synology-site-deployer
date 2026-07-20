from __future__ import annotations

import json
import shlex
from typing import Any

from synology_site.ssh_client import SSHClient


def fetch_markers(ssh: SSHClient, docker_root: str) -> list[dict[str, Any]]:
    """Every `.synology-site.json` marker under `docker_root`.

    This is the durable record of what `create`/`deploy` have ever set up on this target --
    unlike a live `docker ps` scan, a marker survives its own container being stopped, so it's
    the source of truth for "this port belongs to this site" even when that site isn't running
    right now.
    """
    quoted_root = shlex.quote(docker_root)
    result = ssh.run(f"find {quoted_root} -maxdepth 2 -name .synology-site.json -print", check=True)
    markers = []
    for marker_path in result.stdout.splitlines():
        content = ssh.run(f"cat {shlex.quote(marker_path)}", check=True).stdout
        markers.append(json.loads(content))
    return markers


def registered_ports(markers: list[dict[str, Any]]) -> dict[int, str]:
    """Port -> domain, for every marker that records a port.

    Used to reject reusing a port that already belongs to a different site's marker, even if
    that site's container isn't currently running (a live-only port scan can't see that).
    """
    result: dict[int, str] = {}
    for marker in markers:
        port = marker.get("port")
        domain = marker.get("domain")
        if isinstance(port, int) and domain:
            result[port] = str(domain)
    return result
