from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass

import typer
from rich.prompt import Confirm

from synology_site.commands.check_nas import smart_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.errors import SynologySiteError
from synology_site.output import console, ok, warn
from synology_site.ssh_client import SSHClient

SSHFactory = Callable[[Settings, str | None], SSHClient]

# Both copies matter: /etc is what DSM reads right now, /etc.defaults is what some DSM
# upgrades/resets regenerate /etc from -- editing only one leaves the fix liable to be
# silently reverted later.
SYNOINFO_PATHS = ("/etc/synoinfo.conf", "/etc.defaults/synoinfo.conf")
BACKUP_SUFFIX = ".bak.synology-site-drive-fix"
STORAGE_DAEMON = "synostoraged"


@dataclass(frozen=True)
class DriveCompatibilityResult:
    before: str | None
    after: str


def _read_flag(ssh: SSHClient) -> str | None:
    result = ssh.run(
        f"grep -o 'support_disk_compatibility=\"[^\"]*\"' {shlex.quote(SYNOINFO_PATHS[0])}"
    )
    if not result.ok or not result.stdout.strip():
        return None
    return result.stdout.strip().split("=", 1)[1].strip('"')


def _restart_storage_daemon(ssh: SSHClient) -> None:
    # Neither service-control binary lives on the default PATH (confirmed on a real
    # DS1525+ under DSM 7.4) -- synosystemctl is the DSM 7 mechanism, synoservicectl is
    # the older one kept as a fallback for other DSM versions.
    script = (
        "if command -v /usr/syno/bin/synosystemctl >/dev/null 2>&1; then "
        f"/usr/syno/bin/synosystemctl restart {STORAGE_DAEMON}; "
        "elif command -v /usr/syno/bin/synoservicectl >/dev/null 2>&1; then "
        f"/usr/syno/bin/synoservicectl --restart {STORAGE_DAEMON}; "
        "else exit 127; fi"
    )
    result = ssh.run(f"sudo -S -p '' bash -c {shlex.quote(script)}")
    if not result.ok:
        detail = result.stderr.strip() or result.stdout.strip()
        msg = (
            "synoinfo.conf was updated but the storage daemon could not be restarted "
            f"automatically (exit {result.exit_code}): {detail}. Reboot the NAS, or restart "
            f"{STORAGE_DAEMON} by hand, for the change to take effect in Storage Manager."
        )
        raise SynologySiteError(msg)


def set_drive_compatibility_enforcement(
    ssh: SSHClient,
    *,
    enforce: bool,
) -> DriveCompatibilityResult:
    """Toggles DSM's `support_disk_compatibility` flag and restarts the storage daemon.

    With enforcement on (DSM's default), Storage Manager doesn't just warn about drives
    missing from Synology's certified-drive database -- for models with M.2/NVMe storage
    pool support it hides them from "available drives" entirely, so pool creation fails
    with "No drives are available or meet the requirements" even though the hardware
    supports it (confirmed against a real DS1525+ refusing two Samsung 9100 Pro NVMe
    SSDs). Turning enforcement off restores them as selectable, still marked "unverified"
    in the UI. Backs up both synoinfo.conf copies once, on the first change only, so the
    original value survives even after toggling back and forth.
    """
    target = "yes" if enforce else "no"
    before = _read_flag(ssh)

    script_parts = ["set -e"]
    for path in SYNOINFO_PATHS:
        quoted = shlex.quote(path)
        backup = shlex.quote(f"{path}{BACKUP_SUFFIX}")
        script_parts.append(f"[ -f {backup} ] || cp {quoted} {backup}")
        script_parts.append(
            "sed -i 's/support_disk_compatibility=\"[^\"]*\"/"
            f'support_disk_compatibility="{target}"/\' {quoted}'
        )
    script = " && ".join(script_parts)
    ssh.run(f"sudo -S -p '' bash -c {shlex.quote(script)}", check=True)

    after = _read_flag(ssh) or target
    _restart_storage_daemon(ssh)
    return DriveCompatibilityResult(before=before, after=after)


def run_allow_third_party_drives(
    settings: Settings,
    *,
    enforce: bool,
    workspace: str | None = None,
    ssh_factory: SSHFactory = smart_ssh_factory,
    prompted_password: str | None = None,
) -> DriveCompatibilityResult:
    target = settings.resolve_target(workspace=workspace)
    connection_settings = settings.resolved_for(target)
    with ssh_factory(connection_settings, prompted_password) as ssh:
        return set_drive_compatibility_enforcement(ssh, enforce=enforce)


def app(
    revert: bool = typer.Option(
        False,
        "--revert",
        help='Restore DSM\'s default certified-drive enforcement (support_disk_compatibility='
        '"yes") instead of disabling it.',
    ),
    status: bool = typer.Option(
        False, "--status", help="Only report the current setting; make no changes."
    ),
    workspace: str | None = typer.Option(
        None, "--workspace", help="NAS target to change (see secrets/<name>/)"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the confirmation prompt (for scripting)."
    ),
) -> None:
    """Lets Storage Manager use third-party (non-Synology-certified) drives in a pool.

    Without this, DSM 7's disk-compatibility check doesn't just warn about unverified
    drives -- on models with M.2/NVMe storage pool support it hides them from "available
    drives" entirely, so pool creation fails with "No drives are available or meet the
    requirements" even though the hardware is fine. This edits
    /etc/synoinfo.conf and /etc.defaults/synoinfo.conf's support_disk_compatibility flag
    and restarts the storage daemon so Storage Manager picks it up immediately -- no
    reboot needed. Both files are backed up once, before the first change. Pass --revert
    to restore Synology-only enforcement afterward.
    """
    try:
        settings = load_config()
        target = settings.resolve_target(workspace=workspace)
        prompted_password = None
        if not target.ssh_key_path and not target.ssh_password:
            prompted_password = getpass("NAS SSH password: ")

        if status:
            connection_settings = settings.resolved_for(target)
            with smart_ssh_factory(connection_settings, prompted_password) as ssh:
                current = _read_flag(ssh)
            state = "unknown"
            if current == "yes":
                state = "enabled -- only Synology-certified drives are selectable"
            elif current == "no":
                state = "disabled -- third-party drives are selectable"
            console.print(f"support_disk_compatibility={current or '?'} ({state})")
            raise typer.Exit(0)

        action = "Restore certified-drive enforcement" if revert else "Allow third-party drives"
        if not yes and not Confirm.ask(
            f"{action} on {target.name} and restart {STORAGE_DAEMON}?",
            default=True,
        ):
            warn("Cancelled")
            raise typer.Exit(0)

        result = run_allow_third_party_drives(
            settings,
            enforce=revert,
            workspace=workspace,
            prompted_password=prompted_password,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    ok(f"support_disk_compatibility: {result.before or '?'} -> {result.after}")
    ok(f"{STORAGE_DAEMON} restarted -- refresh Storage Manager in the browser")
    if not revert:
        warn(
            "Drives are now selectable but still shown as unverified/uncertified in DSM -- "
            "S.M.A.R.T./health monitoring may be limited for them."
        )
