from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass

import typer
from rich.prompt import Confirm

from synology_site.commands.check_nas import SSHFactory, smart_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.errors import SynologySiteError
from synology_site.hdd_db import DEFAULT_HDD_DB_VERSION, HDD_DB_REPO, fetch_hdd_db_files
from synology_site.output import console, next_step, ok, warn

ConfirmFn = Callable[[str], bool]
FetchFilesFn = Callable[[str], dict[str, str]]


@dataclass(frozen=True)
class HddDbFixResult:
    version: str
    remote_dir: str
    output: str


def _default_confirm(version: str) -> bool:
    console.print(
        f"About to upload and run {HDD_DB_REPO}@{version} (syno_hdd_db.sh -s -n) as root on "
        "the NAS. This edits DSM's per-drive compatibility database and synoinfo.conf."
    )
    return Confirm.ask("Proceed?", default=False)


def run_hdd_db_fix(
    settings: Settings,
    *,
    hdd_db_version: str = DEFAULT_HDD_DB_VERSION,
    workspace: str | None = None,
    ssh_factory: SSHFactory = smart_ssh_factory,
    prompted_password: str | None = None,
    confirm: ConfirmFn = _default_confirm,
    fetch_files: FetchFilesFn = fetch_hdd_db_files,
) -> HddDbFixResult | None:
    """Uploads a pinned 007revad/Synology_HDD_db release to the NAS and runs it with -s -n.

    This is the on-demand equivalent of `drive-compat-fix-plan --include-hdd-db`'s boot-time
    script -- same pinned/cached fetch (see `synology_site.hdd_db`), same flags, but run right
    now over SSH instead of scheduled. Confirmed necessary (not just `allow-third-party-drives`)
    for Storage Manager to allow *volume* creation on third-party NVMe drives on
    2025-series-or-later Plus models.
    """
    if not confirm(hdd_db_version):
        return None

    files = fetch_files(hdd_db_version)

    target = settings.resolve_target(workspace=workspace)
    connection_settings = settings.resolved_for(target)
    remote_dir = f"{target.docker_root.rstrip('/')}/hdd-db-fix"
    with ssh_factory(connection_settings, prompted_password) as ssh:
        ssh.run(f"mkdir -p {shlex.quote(remote_dir)}", check=True)
        for filename, content in files.items():
            ssh.upload_text(f"{remote_dir}/{filename}", content)
        script_path = f"{remote_dir}/syno_hdd_db.sh"
        ssh.run(f"chmod +x {shlex.quote(script_path)}", check=True)
        result = ssh.run(f"sudo -S -p '' bash {shlex.quote(script_path)} -s -n", check=True)

    return HddDbFixResult(version=hdd_db_version, remote_dir=remote_dir, output=result.stdout)


def app(
    hdd_db_version: str = typer.Option(
        DEFAULT_HDD_DB_VERSION,
        "--hdd-db-version",
        help="Pinned Synology_HDD_db release tag to run.",
    ),
    workspace: str | None = typer.Option(
        None, "--workspace", help="NAS target to run against (see secrets/<name>/)"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the confirmation prompt (for scripting)."
    ),
) -> None:
    """Uploads and runs a pinned copy of 007revad/Synology_HDD_db on the NAS right now.

    Adds your installed drives' exact model+firmware as explicit "supported" entries in DSM's
    per-model compatibility database, and re-enables `support_disk_compatibility` (the correct
    end state once real per-drive entries exist, not a bypass). This is what actually let Storage
    Manager create a *volume* -- not just a pool -- on third-party NVMe drives on a real
    DS1525+, where `allow-third-party-drives` alone left the drives "Unrecognized"/Critical.

    Fetches (or reuses a local cache under vendor/synology_hdd_db/<version>/, so a later run
    doesn't depend on the upstream repo still existing) a pinned release -- never a moving
    branch -- uploads it to <docker_root>/hdd-db-fix/ on the NAS, and runs it with -s
    (--showedits) -n (--noupdate). This bundles and executes third-party code as root; read
    vendor/synology_hdd_db/<version>/syno_hdd_db.sh before trusting it on your NAS.
    """
    try:
        settings = load_config()
        target = settings.resolve_target(workspace=workspace)
        prompted_password = None
        if not target.ssh_key_path and not target.ssh_password:
            prompted_password = getpass("NAS SSH password: ")

        confirm: ConfirmFn = (lambda _version: True) if yes else _default_confirm
        result = run_hdd_db_fix(
            settings,
            hdd_db_version=hdd_db_version,
            workspace=workspace,
            prompted_password=prompted_password,
            confirm=confirm,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    if result is None:
        warn("Cancelled")
        raise typer.Exit(0)

    console.print(result.output)
    ok(f"Ran {HDD_DB_REPO}@{result.version} on the NAS ({result.remote_dir})")
    next_step("Refresh Storage Manager -- drives should now show as supported.")
