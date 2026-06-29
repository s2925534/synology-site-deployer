from __future__ import annotations

import json
import shlex
from getpass import getpass

import typer

from synology_site.commands.check_nas import default_ssh_factory
from synology_site.config import load_config
from synology_site.errors import SynologySiteError
from synology_site.output import console


def app() -> None:
    try:
        settings = load_config()
        prompted_password = None
        if not settings.nas_ssh_key_path and not settings.nas_ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        with default_ssh_factory(settings, prompted_password) as ssh:
            quoted_root = shlex.quote(settings.nas_docker_root)
            result = ssh.run(
                f"find {quoted_root} -maxdepth 2 -name .synology-site.json -print",
                check=True,
            )
            markers = []
            for marker_path in result.stdout.splitlines():
                content = ssh.run(f"cat {shlex.quote(marker_path)}", check=True).stdout
                markers.append(json.loads(content))
    except (SynologySiteError, json.JSONDecodeError) as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Sites")
    if not markers:
        console.print("[WARN] No sites found")
        return
    for marker in markers:
        console.print(
            f"[OK] {marker.get('domain')} port={marker.get('port')} slug={marker.get('slug')}"
        )
