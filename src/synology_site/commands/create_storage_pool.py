from __future__ import annotations

import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass

import typer
from rich.prompt import Confirm

from synology_site.commands.check_nas import SSHFactory, smart_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.errors import SynologySiteError
from synology_site.output import console, next_step, ok, warn
from synology_site.ssh_client import SSHClient

# Restricted on purpose: --nvme is meant for a small SSD storage pool, so only the RAID types
# that make sense for that (no redundancy, mirror, or stripe across a handful of drives) are
# offered. --hdd exposes the full set synostgpool itself supports. Values are the CLI's own
# lowercase spelling; SYNO_LEVEL_NAME maps to whatever casing synostgpool actually expects.
NVME_RAID_LEVELS = ("basic", "raid0", "raid1")
HDD_RAID_LEVELS = (
    "basic",
    "raid0",
    "raid1",
    "raid5",
    "raid6",
    "raid10",
    "raid_f1",
    "linear",
    "shr1",
    "shr2",
)
SYNO_LEVEL_NAME = {
    "basic": "basic",
    "raid0": "raid0",
    "raid1": "raid1",
    "raid5": "raid5",
    "raid6": "raid6",
    "raid10": "raid10",
    "raid_f1": "raid_f1",
    "linear": "linear",
    "shr1": "SHR1",
    "shr2": "SHR2",
}
MIN_DRIVES = {
    "basic": 1,
    "raid0": 2,
    "raid1": 2,
    "raid5": 3,
    "raid6": 4,
    "raid10": 4,
    "raid_f1": 3,
    "linear": 1,
    "shr1": 1,
    "shr2": 4,
}
MAX_DRIVES = {"basic": 1, "raid1": 4}

# This tool has been explicitly told (2026-08-05) never to run --hdd against this specific NAS:
# its regular bays already hold live pools/data. Remove a model from here only if you actually
# intend to let --hdd run against that exact NAS.
PROTECTED_HDD_MODELS = frozenset({"DS1525+"})

ConfirmFn = Callable[[tuple[str, ...], str], bool]


@dataclass(frozen=True)
class DiskInfo:
    path: str
    model: str


@dataclass(frozen=True)
class StoragePoolResult:
    devices: tuple[str, ...]
    raid_level: str


def _resolve_raid_levels(*, nvme: bool) -> tuple[str, ...]:
    return NVME_RAID_LEVELS if nvme else HDD_RAID_LEVELS


def _parse_synodisk_enum(output: str) -> list[DiskInfo]:
    disks: list[DiskInfo] = []
    for block in output.split("************ Disk Info ***************"):
        path_match = re.search(r">> Disk path:\s*(\S+)", block)
        if not path_match:
            continue
        model_match = re.search(r">> Disk model:\s*(.+)", block)
        model = model_match.group(1).strip() if model_match else "unknown"
        disks.append(DiskInfo(path=path_match.group(1).strip(), model=model))
    return disks


def _device_in_use(ssh: SSHClient, device: str) -> str | None:
    """Returns a human reason `device` looks already in use, or None if it looks free.

    Two independent, objective signals -- not a guess: an existing filesystem/partition
    signature (`blkid`), or existing RAID membership (`/proc/mdstat`). Either one is reason
    enough to refuse touching the device, since `--partition` would destroy either.
    """
    blkid = ssh.run(f"sudo -S -p '' blkid {shlex.quote(device)}")
    if blkid.ok and blkid.stdout.strip():
        return f"blkid reports an existing signature: {blkid.stdout.strip()}"
    mdstat = ssh.run("cat /proc/mdstat")
    basename = device.rsplit("/", 1)[-1]
    if mdstat.ok and re.search(rf"\b{re.escape(basename)}p\d+\b", mdstat.stdout):
        return "already appears as a RAID member in /proc/mdstat"
    return None


def plan_storage_pool(
    ssh: SSHClient,
    *,
    nvme: bool,
    hdd: bool,
    raid_level: str,
    devices: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Validates target/raid-level/devices and returns the final device list to use.

    Raises SynologySiteError instead of guessing for every unsafe or ambiguous situation: wrong
    drive count for the raid level, a device that already looks in use, an ambiguous "basic"
    (single-drive) request with more than one candidate, or -- for --hdd specifically -- a NAS
    model this tool has been told never to touch that bay type on (see PROTECTED_HDD_MODELS).
    """
    if nvme == hdd:
        raise SynologySiteError("Exactly one of --nvme or --hdd is required")

    levels = _resolve_raid_levels(nvme=nvme)
    if raid_level not in levels:
        target_flag = "--nvme" if nvme else "--hdd"
        msg = f"--raid-level for {target_flag} must be one of: {', '.join(levels)}"
        raise SynologySiteError(msg)

    if hdd:
        model_result = ssh.run("cat /proc/sys/kernel/syno_hw_version")
        model = model_result.stdout.strip()
        if model in PROTECTED_HDD_MODELS:
            msg = (
                f"Refusing to run --hdd on {model}: this NAS's regular bays already hold live "
                "data/pools and this tool has been explicitly told never to touch them. Remove "
                f"{model!r} from PROTECTED_HDD_MODELS in create_storage_pool.py if you really "
                "intend to run --hdd against this exact NAS."
            )
            raise SynologySiteError(msg)

    enum_type = "cache" if nvme else "internal"
    enum_result = ssh.run(f"sudo -S -p '' /usr/syno/bin/synodisk --enum -t {enum_type}", check=True)
    candidates = _parse_synodisk_enum(enum_result.stdout)

    if devices:
        candidate_paths = {disk.path for disk in candidates}
        unknown = [d for d in devices if d not in candidate_paths]
        if unknown:
            msg = f"--device {unknown} not found among detected {enum_type} devices"
            raise SynologySiteError(msg)
        selected = devices
    else:
        selected = tuple(disk.path for disk in candidates)

    minimum = MIN_DRIVES[raid_level]
    if len(selected) < minimum:
        msg = f"{raid_level} needs at least {minimum} drive(s); found {len(selected)}: {selected or 'none'}"
        raise SynologySiteError(msg)

    maximum = MAX_DRIVES.get(raid_level)
    if maximum and len(selected) > maximum:
        hint = " -- pass --device to pick exactly one" if not devices else ""
        msg = f"{raid_level} supports at most {maximum} drive(s); got {len(selected)}: {selected}{hint}"
        raise SynologySiteError(msg)

    blocked = [
        f"{device}: {reason}"
        for device in selected
        if (reason := _device_in_use(ssh, device)) is not None
    ]
    if blocked:
        msg = "Refusing to touch device(s) that already look in use:\n" + "\n".join(blocked)
        raise SynologySiteError(msg)

    return selected


def execute_storage_pool(
    ssh: SSHClient,
    *,
    devices: tuple[str, ...],
    raid_level: str,
    description: str,
) -> StoragePoolResult:
    """Creates the pool via `synostgpool --create` directly on the raw (unpartitioned) devices.

    No separate partitioning step: `synostgpool` partitions the drives itself internally. An
    earlier version of this ran `synodisk --partition` first and passed a `pN` partition suffix
    to synostgpool -- that's wrong on current DSM (`synodisk --partition` is deprecated in favor
    of `synopartition`/`synospace`) and isn't what `synostgpool` expects anyway; confirmed against
    the well-established community tool for this exact task (007revad/Synology_M2_volume), which
    passes bare device paths like `/dev/nvme0n1`, never a partition path.
    """
    syno_level = SYNO_LEVEL_NAME[raid_level]
    quoted_devices = " ".join(shlex.quote(d) for d in devices)
    ssh.run(
        "sudo -S -p '' /usr/syno/sbin/synostgpool --create "
        f"-l {shlex.quote(syno_level)} -c -d {shlex.quote(description)} {quoted_devices}",
        check=True,
    )
    return StoragePoolResult(devices=devices, raid_level=raid_level)


def _default_confirm(devices: tuple[str, ...], raid_level: str) -> bool:
    console.print(f"About to create a {raid_level} storage pool using:")
    for device in devices:
        console.print(f"  {device}")
    return Confirm.ask(
        "Proceed? This partitions these device(s) -- do not continue if any of them hold data "
        "you need.",
        default=False,
    )


def run_create_storage_pool(
    settings: Settings,
    *,
    nvme: bool,
    hdd: bool,
    raid_level: str,
    devices: tuple[str, ...] = (),
    description: str = "NAS storage pool",
    workspace: str | None = None,
    ssh_factory: SSHFactory = smart_ssh_factory,
    prompted_password: str | None = None,
    confirm: ConfirmFn = _default_confirm,
) -> StoragePoolResult | None:
    target = settings.resolve_target(workspace=workspace)
    connection_settings = settings.resolved_for(target)
    with ssh_factory(connection_settings, prompted_password) as ssh:
        selected = plan_storage_pool(ssh, nvme=nvme, hdd=hdd, raid_level=raid_level, devices=devices)
        if not confirm(selected, raid_level):
            return None
        return execute_storage_pool(
            ssh, devices=selected, raid_level=raid_level, description=description
        )


def app(
    nvme: bool = typer.Option(False, "--nvme", help="Target the M.2 NVMe bays."),
    hdd: bool = typer.Option(False, "--hdd", help="Target the regular SATA/HDD bays."),
    raid_level: str = typer.Option(
        ...,
        "--raid-level",
        help="--nvme: basic, raid0, raid1. --hdd also supports raid5, raid6, raid10, raid_f1, "
        "linear, shr1, shr2. 'basic' means a single drive, no RAID.",
    ),
    device: list[str] = typer.Option(
        [],
        "--device",
        help="Explicit device path(s) to use instead of auto-detecting every bay of the chosen "
        "type (repeatable). Required when --raid-level basic finds more than one candidate.",
    ),
    description: str = typer.Option("NAS storage pool", "--description"),
    workspace: str | None = typer.Option(
        None, "--workspace", help="NAS target to change (see secrets/<name>/)"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip the confirmation prompt (for scripting)."
    ),
) -> None:
    """Creates a DSM storage pool directly via `synostgpool`, bypassing Storage Manager's own
    pool-creation wizard.

    Storage Manager's wizard can refuse to even list drives that pass DSM's certified-drive
    check (see `allow-third-party-drives`) for a separate, wizard-specific reason -- creating
    the pool straight over SSH sidesteps that entirely; Storage Manager still handles the final
    "Create Volume" step on top of the pool normally afterward. Before touching anything, this
    detects the target bays via `synodisk --enum` and refuses to proceed if any of them already
    show a filesystem signature or RAID membership -- exactly one of --nvme/--hdd is required so
    there's never any ambiguity about which physical drives get partitioned.
    """
    try:
        settings = load_config()
        target = settings.resolve_target(workspace=workspace)
        prompted_password = None
        if not target.ssh_key_path and not target.ssh_password:
            prompted_password = getpass("NAS SSH password: ")

        confirm: ConfirmFn = (lambda _devices, _level: True) if yes else _default_confirm
        result = run_create_storage_pool(
            settings,
            nvme=nvme,
            hdd=hdd,
            raid_level=raid_level.strip().lower(),
            devices=tuple(device),
            description=description,
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
    ok(f"Storage pool created ({result.raid_level}) on: {', '.join(result.devices)}")
    next_step("In DSM: Storage Manager -> Storage Pool -> Create Volume on top of the new pool.")
