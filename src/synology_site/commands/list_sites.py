from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from dataclasses import replace
from getpass import getpass
from typing import Any

import typer

from synology_site.commands.check_nas import default_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.errors import SynologySiteError
from synology_site.nas.target import NasTarget
from synology_site.output import console, warn
from synology_site.ssh_client import SSHClient

SSHFactory = Callable[[Settings, str | None], SSHClient]


def list_markers_for_target(
    settings: Settings,
    target: NasTarget,
    *,
    ssh_factory: SSHFactory = default_ssh_factory,
    prompted_password: str | None = None,
) -> list[dict[str, Any]]:
    connection_settings = replace(
        settings,
        nas_host=target.host,
        nas_port=target.port,
        nas_user=target.user,
        nas_ssh_key_path=target.ssh_key_path,
        nas_ssh_password=target.ssh_password,
    )
    with ssh_factory(connection_settings, prompted_password) as ssh:
        quoted_root = shlex.quote(target.docker_root)
        result = ssh.run(
            f"find {quoted_root} -maxdepth 2 -name .synology-site.json -print",
            check=True,
        )
        markers = []
        for marker_path in result.stdout.splitlines():
            content = ssh.run(f"cat {shlex.quote(marker_path)}", check=True).stdout
            markers.append(json.loads(content))
        return markers


PasswordPrompt = Callable[[NasTarget], "str | None"]


def list_sites_across_targets(
    settings: Settings,
    targets: tuple[NasTarget, ...],
    *,
    ssh_factory: SSHFactory = default_ssh_factory,
    password_prompt: PasswordPrompt = lambda target: getpass(
        f"NAS SSH password ({target.name}): "
    ),
) -> dict[str, list[dict[str, Any]] | str]:
    """Fetch markers from each target independently -- one unreachable target must not stop
    the others from being listed."""
    results: dict[str, list[dict[str, Any]] | str] = {}
    for target in targets:
        target_password = None
        if not target.ssh_key_path and not target.ssh_password:
            target_password = password_prompt(target)
        try:
            results[target.name] = list_markers_for_target(
                settings, target, ssh_factory=ssh_factory, prompted_password=target_password
            )
        except SynologySiteError as exc:
            results[target.name] = f"unreachable: {exc}"
    return results


def app(
    all_targets: bool = typer.Option(
        False, "--all-targets", help="List sites across every configured NAS target"
    ),
    workspace: str | None = typer.Option(
        None, "--workspace", help="List sites on a specific NAS target only"
    ),
) -> None:
    try:
        settings = load_config()
        targets = (
            (settings.default_nas_target, *settings.nas_targets)
            if all_targets
            else (settings.resolve_target(workspace=workspace),)
        )
        results = list_sites_across_targets(settings, targets)
    except (SynologySiteError, json.JSONDecodeError) as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Sites")
    show_target_prefix = len(results) > 1
    any_markers = False
    for target_name, markers_or_error in results.items():
        prefix = f"[{target_name}] " if show_target_prefix else ""
        if isinstance(markers_or_error, str):
            warn(f"{prefix}{markers_or_error}")
            continue
        for marker in markers_or_error:
            any_markers = True
            console.print(
                f"[OK] {prefix}{marker.get('domain')} port={marker.get('port')} "
                f"slug={marker.get('slug')}"
            )
    if not any_markers and all(isinstance(value, list) for value in results.values()):
        console.print("[WARN] No sites found")
