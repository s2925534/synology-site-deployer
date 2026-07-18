from __future__ import annotations

import posixpath
from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass

import typer

from synology_site.commands.check_nas import smart_ssh_factory
from synology_site.commands.list_sites import list_markers_for_target
from synology_site.config import Settings, load_config
from synology_site.docker_remote import (
    ContainerInfo,
    MemoryInfo,
    SystemLoad,
    list_containers_with_projects,
    read_memory_info,
    read_system_load,
)
from synology_site.errors import SynologySiteError
from synology_site.nas.target import NasTarget
from synology_site.output import console, error, ok, warn
from synology_site.ssh_client import SSHClient

SSHFactory = Callable[[Settings, str | None], SSHClient]
PasswordPrompt = Callable[[NasTarget], "str | None"]

# Thresholds picked from a real incident: a full-fleet restart on an 8GB DS1525+ pushed load
# average to 75 and swap to 85% full, which took the Docker daemon down hard enough to need a
# physical power cycle. "warn" is meant to catch things well before they reach that territory.
LOAD_WARN = 10.0
LOAD_CRITICAL = 25.0
SWAP_WARN_PERCENT = 50.0
SWAP_CRITICAL_PERCENT = 80.0
AVAILABLE_MB_WARN = 2048
AVAILABLE_MB_CRITICAL = 1024


@dataclass(frozen=True)
class DoctorFinding:
    target_name: str
    category: str
    severity: str  # "warn" | "critical"
    summary: str


def expected_working_dir(docker_root: str, marker: dict[str, object]) -> str:
    """Where a marker's Compose project should be running from, on disk.

    `compose_file` in the marker is relative to the marker's own directory (e.g.
    `repo/docker-compose.yml` for a project cloned into a `repo/` subdirectory) -- this mirrors
    that same relative resolution so the result matches Docker's own
    `com.docker.compose.project.working_dir` label exactly, letting the two be compared directly.
    """
    slug = str(marker.get("slug") or "")
    compose_file = str(marker.get("compose_file") or "docker-compose.yml")
    base = f"{docker_root.rstrip('/')}/{slug}"
    rel_dir = posixpath.dirname(compose_file)
    if not rel_dir or rel_dir == ".":
        return base
    return posixpath.normpath(f"{base}/{rel_dir}")


def find_never_started_sites(
    markers: list[dict[str, object]],
    containers: list[ContainerInfo],
    docker_root: str,
) -> list[dict[str, object]]:
    """Markers with no container -- in any state, not even a stopped one -- at their expected
    working directory. Distinct from a site that's merely stopped: this one was never actually
    brought up despite `create`/`deploy` apparently having configured it (marker + Cloudflare
    route present)."""
    known_working_dirs = {
        container.working_dir for container in containers if container.working_dir
    }
    return [
        marker
        for marker in markers
        if expected_working_dir(docker_root, marker) not in known_working_dirs
    ]


def find_missing_restart_policy(containers: list[ContainerInfo]) -> list[ContainerInfo]:
    return [
        container
        for container in containers
        if container.name and not container.has_auto_restart
    ]


def find_project_name_collisions(containers: list[ContainerInfo]) -> dict[str, set[str]]:
    """Compose project names that resolve from more than one distinct working directory.

    Compose derives a project's default name from its working directory's basename when no
    explicit `name:` is set -- two unrelated projects both checked out into a directory literally
    called `repo` collide on the same default name, which makes each one's `up`/`down` see the
    others' containers as "orphans" and, with `--remove-orphans`, could remove them outright.
    """
    by_project: dict[str, set[str]] = {}
    for container in containers:
        if not container.project or not container.working_dir:
            continue
        by_project.setdefault(container.project, set()).add(container.working_dir)
    return {project: dirs for project, dirs in by_project.items() if len(dirs) > 1}


def check_resources(load: SystemLoad, memory: MemoryInfo) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    if load.load1 >= LOAD_CRITICAL:
        findings.append(
            ("critical", f"load average (1m) is {load.load1:g} -- system is likely overloaded")
        )
    elif load.load1 >= LOAD_WARN:
        findings.append(("warn", f"load average (1m) is {load.load1:g} -- elevated"))

    if memory.swap_percent >= SWAP_CRITICAL_PERCENT:
        findings.append(
            (
                "critical",
                f"swap is {memory.swap_percent:.0f}% full "
                f"({memory.swap_used_mb}/{memory.swap_total_mb} MB) -- high risk of instability",
            )
        )
    elif memory.swap_percent >= SWAP_WARN_PERCENT:
        findings.append(("warn", f"swap is {memory.swap_percent:.0f}% full"))

    if memory.available_mb <= AVAILABLE_MB_CRITICAL:
        findings.append(("critical", f"only {memory.available_mb} MB memory available"))
    elif memory.available_mb <= AVAILABLE_MB_WARN:
        findings.append(("warn", f"only {memory.available_mb} MB memory available"))

    return findings


def run_doctor(
    settings: Settings,
    targets: tuple[NasTarget, ...],
    *,
    ssh_factory: SSHFactory = smart_ssh_factory,
    password_prompt: PasswordPrompt = lambda _target: None,
) -> list[DoctorFinding]:
    findings: list[DoctorFinding] = []
    for target in targets:
        target_password = None
        if not target.ssh_key_path and not target.ssh_password:
            target_password = password_prompt(target)

        try:
            markers = list_markers_for_target(
                settings, target, ssh_factory=ssh_factory, prompted_password=target_password
            )
        except SynologySiteError as exc:
            findings.append(
                DoctorFinding(target.name, "connectivity", "critical", f"target unreachable: {exc}")
            )
            continue

        try:
            connection_settings = settings.resolved_for(target)
            with ssh_factory(connection_settings, target_password) as ssh:
                containers = list_containers_with_projects(ssh)
                load = read_system_load(ssh)
                memory = read_memory_info(ssh)
        except SynologySiteError as exc:
            findings.append(
                DoctorFinding(target.name, "connectivity", "critical", f"target unreachable: {exc}")
            )
            continue

        for marker in find_never_started_sites(markers, containers, target.docker_root):
            domain = str(marker.get("domain") or marker.get("slug") or "unknown")
            findings.append(
                DoctorFinding(
                    target.name,
                    "never-started",
                    "warn",
                    f"{domain}: configured (marker + compose file present) but no container "
                    "has ever been created for it",
                )
            )

        for container in find_missing_restart_policy(containers):
            policy = container.restart_policy or "none"
            findings.append(
                DoctorFinding(
                    target.name,
                    "no-restart-policy",
                    "warn",
                    f"{container.name}: no auto-restart policy (restart={policy}) -- "
                    "won't come back on its own after a crash or reboot",
                )
            )

        for project, dirs in find_project_name_collisions(containers).items():
            findings.append(
                DoctorFinding(
                    target.name,
                    "project-name-collision",
                    "warn",
                    f"Compose project name '{project}' is shared by {len(dirs)} unrelated "
                    f"directories ({', '.join(sorted(dirs))}) -- add an explicit `name:` to "
                    "each Compose file to avoid cross-project orphan warnings",
                )
            )

        for severity, detail in check_resources(load, memory):
            findings.append(DoctorFinding(target.name, "resources", severity, detail))

    return findings


def app(
    all_targets: bool = typer.Option(
        False, "--all-targets", help="Run diagnostics across every configured NAS target"
    ),
    workspace: str | None = typer.Option(
        None, "--workspace", help="Run diagnostics on a specific NAS target only"
    ),
) -> None:
    """Read-only: audits the NAS for the failure classes a real incident on this fleet exposed --
    never-started sites, missing restart policies, Compose project-name collisions, and
    load/memory pressure. Never writes anything."""
    try:
        settings = load_config()
        targets = (
            (settings.default_nas_target, *settings.nas_targets)
            if all_targets
            else (settings.resolve_target(workspace=workspace),)
        )
        findings = run_doctor(
            settings,
            targets,
            password_prompt=lambda target: getpass(f"NAS SSH password ({target.name}): "),
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Doctor")
    if not findings:
        ok("No issues found")
        return

    show_target_prefix = len({finding.target_name for finding in findings}) > 1
    critical = [finding for finding in findings if finding.severity == "critical"]
    for finding in findings:
        prefix = f"[{finding.target_name}] " if show_target_prefix else ""
        if finding.severity == "critical":
            error(f"{prefix}{finding.summary}")
        else:
            warn(f"{prefix}{finding.summary}")

    console.print()
    console.print(
        f"{len(findings)} finding(s): {len(critical)} critical, "
        f"{len(findings) - len(critical)} warning(s)"
    )
    if critical:
        raise typer.Exit(1)
