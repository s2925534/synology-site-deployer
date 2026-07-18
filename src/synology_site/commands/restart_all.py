from __future__ import annotations

import posixpath
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass

import typer

from synology_site.commands.check_nas import smart_ssh_factory
from synology_site.commands.doctor import expected_working_dir
from synology_site.commands.list_sites import list_markers_for_target
from synology_site.config import Settings, load_config
from synology_site.docker_remote import (
    ContainerInfo,
    compose_services,
    detect_compose_command,
    list_containers_with_projects,
    read_system_load,
)
from synology_site.errors import SynologySiteError
from synology_site.nas.target import NasTarget
from synology_site.output import console, error, ok, warn
from synology_site.ssh_client import SSHClient

SSHFactory = Callable[[Settings, str | None], SSHClient]
PasswordPrompt = Callable[[NasTarget], "str | None"]
Sleep = Callable[[float], None]

# A real incident on this fleet: bringing every stack up in one wide `compose up -d` sweep drove
# load average to 75 and took the Docker daemon down hard enough to need a physical power cycle.
# These defaults are deliberately conservative -- one Compose *service* at a time, with a real
# pause between each, and a hard abort if load climbs into dangerous territory mid-run.
DEFAULT_STAGGER_SECONDS = 15.0
DEFAULT_MAX_LOAD = 20.0


@dataclass(frozen=True)
class ProjectPlan:
    working_dir: str
    compose_file: str
    label: str


@dataclass(frozen=True)
class RestartStep:
    target_name: str
    working_dir: str
    service: str
    ok: bool
    detail: str


def discover_projects(
    markers: list[dict[str, object]],
    containers: list[ContainerInfo],
    docker_root: str,
) -> list[ProjectPlan]:
    """Every Compose project that should exist: both ones with a container already (running or
    not) and ones that are only configured (a marker exists but no container was ever created --
    the "never-started" class `doctor` also flags). Unioning both is what makes a single
    `restart-all` run able to both recover a crashed fleet and finish deployments that never
    actually started."""
    markers_by_working_dir = {
        expected_working_dir(docker_root, marker): marker for marker in markers
    }
    working_dirs = {container.working_dir for container in containers if container.working_dir}
    working_dirs |= set(markers_by_working_dir.keys())

    plans = []
    for working_dir in sorted(working_dirs):
        marker = markers_by_working_dir.get(working_dir)
        if marker is not None:
            label = str(marker.get("domain") or marker.get("slug") or working_dir)
            raw_compose_file = str(marker.get("compose_file") or "docker-compose.yml")
            compose_file = posixpath.basename(raw_compose_file)
        else:
            label = posixpath.basename(working_dir) or working_dir
            compose_file = "docker-compose.yml"
        plans.append(ProjectPlan(working_dir=working_dir, compose_file=compose_file, label=label))
    return plans


def filter_projects(plans: list[ProjectPlan], only: list[str] | None) -> list[ProjectPlan]:
    if not only:
        return plans
    wanted = {value.lower() for value in only}
    return [
        plan
        for plan in plans
        if plan.label.lower() in wanted or posixpath.basename(plan.working_dir).lower() in wanted
    ]


def restart_all(
    settings: Settings,
    targets: tuple[NasTarget, ...],
    *,
    ssh_factory: SSHFactory = smart_ssh_factory,
    password_prompt: PasswordPrompt = lambda _target: None,
    only: list[str] | None = None,
    stagger_seconds: float = DEFAULT_STAGGER_SECONDS,
    max_load: float = DEFAULT_MAX_LOAD,
    dry_run: bool = False,
    sleep: Sleep = time.sleep,
) -> list[RestartStep]:
    steps: list[RestartStep] = []
    for target in targets:
        target_password = None
        if not target.ssh_key_path and not target.ssh_password:
            target_password = password_prompt(target)

        try:
            markers = list_markers_for_target(
                settings, target, ssh_factory=ssh_factory, prompted_password=target_password
            )
        except SynologySiteError as exc:
            steps.append(RestartStep(target.name, "*", "*", False, f"target unreachable: {exc}"))
            continue

        try:
            connection_settings = settings.resolved_for(target)
            with ssh_factory(connection_settings, target_password) as ssh:
                containers = list_containers_with_projects(ssh)
                plans = filter_projects(
                    discover_projects(markers, containers, target.docker_root), only
                )

                if dry_run:
                    for plan in plans:
                        steps.append(
                            RestartStep(
                                target.name,
                                plan.working_dir,
                                "*",
                                True,
                                f"[dry-run] would reconcile {plan.label} "
                                f"({plan.working_dir}, {plan.compose_file})",
                            )
                        )
                    continue

                compose_cmd = detect_compose_command(ssh)
                aborted = False
                for plan in plans:
                    if aborted:
                        steps.append(
                            RestartStep(
                                target.name,
                                plan.working_dir,
                                "*",
                                False,
                                "skipped: aborted earlier in this run due to high load",
                            )
                        )
                        continue

                    try:
                        services = compose_services(
                            ssh, compose_cmd, plan.working_dir, compose_file=plan.compose_file
                        )
                    except SynologySiteError as exc:
                        steps.append(
                            RestartStep(
                                target.name,
                                plan.working_dir,
                                "*",
                                False,
                                f"could not read services from {plan.compose_file}: {exc}",
                            )
                        )
                        continue

                    for service in services:
                        load = read_system_load(ssh)
                        if load.load1 >= max_load:
                            steps.append(
                                RestartStep(
                                    target.name,
                                    plan.working_dir,
                                    service,
                                    False,
                                    f"aborted: load average (1m) is {load.load1:g}, "
                                    f">= --max-load {max_load:g}",
                                )
                            )
                            aborted = True
                            break

                        quoted_dir = shlex.quote(plan.working_dir)
                        quoted_file = shlex.quote(plan.compose_file)
                        quoted_service = shlex.quote(service)
                        result = ssh.run(
                            f"cd {quoted_dir} && {compose_cmd} -f {quoted_file} "
                            f"up -d {quoted_service} 2>&1"
                        )
                        detail = (result.stdout or result.stderr).strip().splitlines()
                        steps.append(
                            RestartStep(
                                target.name,
                                plan.working_dir,
                                service,
                                result.ok,
                                detail[-1] if detail else "",
                            )
                        )
                        sleep(stagger_seconds)
        except SynologySiteError as exc:
            steps.append(RestartStep(target.name, "*", "*", False, f"target unreachable: {exc}"))
            continue

    return steps


def app(
    all_targets: bool = typer.Option(
        False, "--all-targets", help="Restart across every configured NAS target"
    ),
    workspace: str | None = typer.Option(
        None, "--workspace", help="Restart on a specific NAS target only"
    ),
    only: list[str] | None = typer.Option(  # noqa: B008
        None,
        "--only",
        help="Restrict to one project (by domain or slug). Repeatable. "
        "Omit to restart every project.",
    ),
    stagger_seconds: float = typer.Option(
        DEFAULT_STAGGER_SECONDS,
        "--stagger-seconds",
        help="Pause between starting each individual Compose service",
    ),
    max_load: float = typer.Option(
        DEFAULT_MAX_LOAD,
        "--max-load",
        help="Abort the run if 1-minute load average reaches this before starting a service",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be restarted without doing it"
    ),
) -> None:
    """Bring every project on the NAS up, one Compose service at a time, pausing between each and
    aborting on high load -- safe by construction, unlike a bare `docker compose up -d` across
    many projects at once, which took this fleet's Docker daemon down hard enough to need a
    physical power cycle. Includes projects that were configured (a marker + Compose file exist)
    but never actually started, not just ones that are already stopped."""
    try:
        settings = load_config()
        targets = (
            (settings.default_nas_target, *settings.nas_targets)
            if all_targets
            else (settings.resolve_target(workspace=workspace),)
        )
        steps = restart_all(
            settings,
            targets,
            password_prompt=lambda target: getpass(f"NAS SSH password ({target.name}): "),
            only=list(only) if only else None,
            stagger_seconds=stagger_seconds,
            max_load=max_load,
            dry_run=dry_run or settings.dry_run,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Restart All")
    if not steps:
        warn("Nothing to restart")
        return

    show_target_prefix = len({step.target_name for step in steps}) > 1
    failures = [step for step in steps if not step.ok]
    for step in steps:
        prefix = f"[{step.target_name}] " if show_target_prefix else ""
        label = f"{step.working_dir}" + (f" :: {step.service}" if step.service != "*" else "")
        if step.ok:
            ok(f"{prefix}{label} {step.detail}".rstrip())
        else:
            (error if "aborted" in step.detail else warn)(f"{prefix}{label} {step.detail}")

    console.print()
    console.print(f"{len(steps)} step(s): {len(steps) - len(failures)} ok, {len(failures)} failed")
    if any("aborted" in step.detail for step in failures):
        raise typer.Exit(1)
