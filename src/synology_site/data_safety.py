"""Data-store preservation guard for deploys.

A deploy that swaps a stateful mount's backing store -- e.g. a database
datadir bind mount (`./db-data:/var/lib/mysql`) changed to a *fresh* named
volume, or a volume renamed -- does not lose data outright (nothing is
deleted), but it silently *orphans* it: the container comes up on an empty
store, the database re-initializes from scratch, and the real data sits
untouched but unused on disk. That is exactly the failure mode that stood up
an empty WordPress over a populated site.

This module makes that class of change loud and recoverable:

* `check_data_mount_safety` compares the *currently deployed* Compose file on
  the NAS against the new one about to be deployed and refuses (unless
  explicitly allowed) any change that would abandon a populated store for an
  empty/absent one.
* `snapshot_databases` tars existing database datadirs into the project's
  `backups/` directory before `up -d`, so even an allowed or unforeseen
  change is a one-command restore away.

The Compose parsing and diff logic is pure and unit-tested; the NAS
interactions (does this store hold data? read the deployed Compose; tar the
datadir) are thin wrappers around `SSHClient` so the decision logic can be
exercised without a NAS.
"""

from __future__ import annotations

import json
import posixpath
import shlex
from collections.abc import Callable
from dataclasses import dataclass

import yaml

from synology_site.errors import SynologySiteError
from synology_site.output import ok, warn
from synology_site.ssh_client import SSHClient

# Container mount targets that hold irreplaceable stateful data. A change to
# the store backing one of these is always guarded (in addition to any mount
# whose old or new store is a named volume -- you do not name-volume code).
_STATEFUL_TARGETS: tuple[str, ...] = (
    "/var/lib/mysql",
    "/var/lib/postgresql/data",
    "/var/lib/postgresql",
    "/var/lib/mongodb",
    "/data/db",
    "/bitnami/mariadb",
    "/bitnami/mysql",
    "/bitnami/postgresql",
    "/var/www/html/wp-content",
    "/var/www/html",
)

# The subset of stateful targets that are database datadirs -- these get an
# automatic pre-deploy tar snapshot (they are small relative to uploads and
# are the store a bad deploy silently re-initializes).
_DB_DATADIR_TARGETS: tuple[str, ...] = (
    "/var/lib/mysql",
    "/var/lib/postgresql/data",
    "/var/lib/postgresql",
    "/var/lib/mongodb",
    "/data/db",
    "/bitnami/mariadb",
    "/bitnami/mysql",
    "/bitnami/postgresql",
)

# Trailing tokens in Compose short-syntax volume specs that are access modes,
# not part of the source/target (e.g. `./db:/var/lib/mysql:ro`).
_MODE_TOKENS = frozenset(
    {
        "ro",
        "rw",
        "z",
        "Z",
        "cached",
        "delegated",
        "consistent",
        "private",
        "rprivate",
        "shared",
        "rshared",
        "slave",
        "rslave",
    }
)


@dataclass(frozen=True)
class StoreRef:
    """The backing store for a single container mount.

    ``kind`` is ``"bind"`` (``ident`` is an absolute host path) or ``"named"``
    (``ident`` is the resolved Docker volume name).
    """

    kind: str
    ident: str


@dataclass(frozen=True)
class MountChange:
    """A stateful mount whose backing store changed between deploys."""

    service: str
    target: str
    old: StoreRef
    new: StoreRef

    def describe(self) -> str:
        return (
            f"service '{self.service}' mount {self.target}: "
            f"{_render_store(self.old)} -> {_render_store(self.new)}"
        )


def _render_store(store: StoreRef) -> str:
    label = "bind" if store.kind == "bind" else "named volume"
    return f"{label} {store.ident}"


def _is_stateful_target(target: str) -> bool:
    return target.rstrip("/") in _STATEFUL_TARGETS


def _is_db_datadir(target: str) -> bool:
    return target.rstrip("/") in _DB_DATADIR_TARGETS


def _resolve_store(source: str, compose_dir: str, named_names: dict[str, str]) -> StoreRef | None:
    """Map a Compose volume source to a StoreRef, or None for anonymous volumes."""
    if source.startswith(("/", ".", "~")):
        abs_path = (
            source
            if source.startswith("/")
            else posixpath.normpath(posixpath.join(compose_dir, source))
        )
        return StoreRef("bind", abs_path)
    return StoreRef("named", named_names.get(source, source))


def parse_data_mounts(compose_text: str, compose_dir: str) -> dict[tuple[str, str], StoreRef]:
    """Parse a Compose file into ``{(service, container_target): StoreRef}``.

    ``compose_dir`` is the directory the Compose file lives in on the host, used
    to resolve relative bind sources to absolute paths -- the same resolution
    Docker Compose itself does -- so two files that both say ``./db-data`` from
    the same directory compare equal, and one that moved it does not.
    Anonymous volumes (a bare container path) are skipped.
    """
    try:
        data = yaml.safe_load(compose_text) or {}
    except yaml.YAMLError as exc:
        raise SynologySiteError(f"Could not parse Compose file: {exc}") from exc
    if not isinstance(data, dict):
        return {}

    top_volumes = data.get("volumes") or {}
    named_names: dict[str, str] = {}
    if isinstance(top_volumes, dict):
        for key, spec in top_volumes.items():
            name = key
            if isinstance(spec, dict) and spec.get("name"):
                name = str(spec["name"])
            named_names[str(key)] = name

    mounts: dict[tuple[str, str], StoreRef] = {}
    services = data.get("services") or {}
    if not isinstance(services, dict):
        return mounts
    for service, config in services.items():
        if not isinstance(config, dict):
            continue
        for entry in config.get("volumes") or []:
            parsed = _parse_volume_entry(entry, str(compose_dir), named_names)
            if parsed is None:
                continue
            target, store = parsed
            mounts[(str(service), target)] = store
    return mounts


def _parse_volume_entry(
    entry: object, compose_dir: str, named_names: dict[str, str]
) -> tuple[str, StoreRef] | None:
    if isinstance(entry, str):
        parts = entry.split(":")
        if len(parts) >= 2 and parts[-1] in _MODE_TOKENS:
            parts = parts[:-1]
        if len(parts) < 2:
            return None  # anonymous volume (container path only)
        source, target = parts[0], parts[1]
        store = _resolve_store(source, compose_dir, named_names)
        return (target.rstrip("/") or target, store) if store else None
    if isinstance(entry, dict):
        target = entry.get("target")
        if not target:
            return None
        mount_type = entry.get("type")
        source = entry.get("source")
        if mount_type == "bind" and source:
            store = _resolve_store(str(source), compose_dir, named_names)
        elif mount_type in (None, "volume") and source:
            store = StoreRef("named", named_names.get(str(source), str(source)))
        else:
            return None  # anonymous volume / tmpfs / unsupported
        target_s = str(target)
        return (target_s.rstrip("/") or target_s, store) if store else None
    return None


def detect_orphaning_changes(
    old_mounts: dict[tuple[str, str], StoreRef],
    new_mounts: dict[tuple[str, str], StoreRef],
    store_has_data: Callable[[StoreRef], bool],
) -> list[MountChange]:
    """Return stateful mounts that abandon a populated store for an empty one.

    A change is reported only when all of the following hold:
      * the same ``(service, target)`` exists in both deploys,
      * its backing store changed (bind<->named, renamed volume, moved path),
      * the mount is stateful (a known data target, or either side is a named
        volume -- code lives in tracked bind mounts, not named volumes),
      * the *old* store currently holds data, and the *new* store does not.

    ``store_has_data`` answers the "holds data?" question (a real deploy checks
    the NAS; tests inject a set).
    """
    changes: list[MountChange] = []
    for key in old_mounts.keys() & new_mounts.keys():
        old, new = old_mounts[key], new_mounts[key]
        if (old.kind, old.ident) == (new.kind, new.ident):
            continue
        service, target = key
        guarded = (
            _is_stateful_target(target) or old.kind == "named" or new.kind == "named"
        )
        if not guarded:
            continue
        if store_has_data(old) and not store_has_data(new):
            changes.append(MountChange(service=service, target=target, old=old, new=new))
    return changes


# --------------------------------------------------------------------------
# NAS-backed operations
# --------------------------------------------------------------------------


def _read_deployed_compose(ssh: SSHClient, project_path: str) -> tuple[str, str] | None:
    """Return (compose_text, compose_dir) for the currently deployed project.

    Uses the ``.synology-site.json`` marker to find the exact Compose file the
    last deploy used (it may live under ``repo/...``); falls back to a
    top-level ``docker-compose.yml``. Returns None if nothing is deployed yet.
    """
    compose_rel = "docker-compose.yml"
    marker = ssh.run(f"cat {shlex.quote(project_path + '/.synology-site.json')}")
    if marker.ok and marker.stdout.strip():
        try:
            recorded = json.loads(marker.stdout).get("compose_file")
        except json.JSONDecodeError:
            recorded = None
        if recorded:
            compose_rel = str(recorded)

    compose_path = posixpath.normpath(posixpath.join(project_path, compose_rel))
    result = ssh.run(f"cat {shlex.quote(compose_path)}")
    if not result.ok or not result.stdout.strip():
        return None
    return result.stdout, posixpath.dirname(compose_path)


def _make_store_probe(ssh: SSHClient, docker_cmd: str) -> Callable[[StoreRef], bool]:
    """A cached 'does this store hold data?' probe against the NAS.

    A bind store has data if its directory exists and is non-empty. A named
    volume is treated as holding data when it exists -- Docker only creates one
    fresh (and a database only re-initializes) when it does not yet exist,
    which is precisely the empty case we must catch.
    """
    cache: dict[tuple[str, str], bool] = {}

    def probe(store: StoreRef) -> bool:
        cache_key = (store.kind, store.ident)
        if cache_key in cache:
            return cache[cache_key]
        if store.kind == "bind":
            quoted = shlex.quote(store.ident)
            result = ssh.run(
                f'test -d {quoted} && test -n "$(ls -A {quoted} 2>/dev/null | head -1)"'
            )
        else:
            result = ssh.run(f"{docker_cmd} volume inspect {shlex.quote(store.ident)}")
        cache[cache_key] = result.ok
        return result.ok

    return probe


def check_data_mount_safety(
    ssh: SSHClient,
    *,
    docker_cmd: str,
    project_path: str,
    new_compose_text: str,
    new_compose_dir: str,
    allow_data_mount_change: bool,
) -> None:
    """Abort the deploy if it would orphan a populated stateful store.

    Read-only: reads the deployed Compose and probes stores; mutates nothing.
    Raises ``SynologySiteError`` (listing every offending mount) unless
    ``allow_data_mount_change`` is set, in which case it only warns.
    """
    deployed = _read_deployed_compose(ssh, project_path)
    if deployed is None:
        return  # first deploy -- no existing data to orphan
    old_text, old_dir = deployed

    old_mounts = parse_data_mounts(old_text, old_dir)
    new_mounts = parse_data_mounts(new_compose_text, new_compose_dir)
    if not old_mounts:
        return

    changes = detect_orphaning_changes(old_mounts, new_mounts, _make_store_probe(ssh, docker_cmd))
    if not changes:
        return

    lines = "\n".join(f"  - {change.describe()}" for change in changes)
    if allow_data_mount_change:
        warn(
            "Deploy changes a stateful mount away from existing data "
            "(--allow-data-mount-change was passed, continuing):\n" + lines
        )
        return
    raise SynologySiteError(
        "Refusing to deploy: this Compose file would move a stateful mount off "
        "its existing, populated store onto an empty/absent one, orphaning the "
        "current data (a database would re-initialize empty):\n"
        f"{lines}\n\n"
        "Keep the mount pointed at the current store, or pass "
        "--allow-data-mount-change to override (the existing data is left on "
        "disk either way; nothing is deleted)."
    )


def snapshot_databases(
    ssh: SSHClient,
    *,
    docker_cmd: str,
    project_path: str,
) -> list[str]:
    """Tar existing database datadirs into ``<project>/backups/`` before up -d.

    Best-effort safety net: reads the deployed Compose, snapshots any DB
    datadir bind mount (and attempts named-volume datadirs via a throwaway
    container). Returns human-readable notes; never raises -- a failed backup
    warns but does not block the deploy (the mount-safety guard is the primary
    protection).
    """
    deployed = _read_deployed_compose(ssh, project_path)
    if deployed is None:
        return []
    old_text, old_dir = deployed
    mounts = parse_data_mounts(old_text, old_dir)

    probe = _make_store_probe(ssh, docker_cmd)
    backups_dir = posixpath.join(project_path, "backups")
    notes: list[str] = []
    made_dir = False
    for (service, target), store in sorted(mounts.items()):
        if not _is_db_datadir(target) or not probe(store):
            continue
        if not made_dir:
            ssh.run(f"mkdir -p {shlex.quote(backups_dir)}")
            made_dir = True
        note = _snapshot_store(ssh, docker_cmd, store, service, backups_dir)
        if note:
            notes.append(note)
    return notes


def _snapshot_store(
    ssh: SSHClient, docker_cmd: str, store: StoreRef, service: str, backups_dir: str
) -> str | None:
    stamp = "$(date +%Y%m%d-%H%M%S)"
    if store.kind == "bind":
        parent = posixpath.dirname(store.ident.rstrip("/")) or "/"
        base = posixpath.basename(store.ident.rstrip("/"))
        archive = f"{backups_dir}/{service}-{base}-predeploy-{stamp}.tar.gz"
        cmd = (
            f"cd {shlex.quote(parent)} && "
            f"tar czf {shlex.quote(archive)} {shlex.quote(base)}"
        )
    else:
        archive = f"{backups_dir}/{service}-{store.ident}-predeploy-{stamp}.tar.gz"
        cmd = (
            f"{docker_cmd} run --rm "
            f"-v {shlex.quote(store.ident)}:/__src:ro "
            f"-v {shlex.quote(backups_dir)}:/__bak "
            f"busybox tar czf /__bak/{shlex.quote(posixpath.basename(archive))} -C /__src ."
        )
    result = ssh.run(cmd)
    if result.ok:
        ok(f"Snapshotted {service} datadir ({_render_store(store)}) to backups/")
        return f"{service}: {_render_store(store)}"
    warn(
        f"Could not snapshot {service} datadir ({_render_store(store)}) before deploy: "
        f"{(result.stderr or result.stdout or '').strip()}"
    )
    return None
