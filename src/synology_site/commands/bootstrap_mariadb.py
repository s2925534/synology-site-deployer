from __future__ import annotations

import contextlib
import shlex
from collections.abc import Callable
from dataclasses import dataclass, replace
from getpass import getpass
from pathlib import Path

import typer

from synology_site.commands.check_nas import default_ssh_factory
from synology_site.commands.ensure_network import ensure_network
from synology_site.config import Settings, load_config
from synology_site.database.passwords import generate_password
from synology_site.database.shared_mariadb import (
    SHARED_MARIADB_CONTAINER,
    SHARED_MARIADB_NETWORK,
    SHARED_MARIADB_VOLUME,
)
from synology_site.docker_remote import (
    detect_compose_command,
    docker_command,
    ensure_remote_directory,
    require_docker,
)
from synology_site.errors import SynologySiteError
from synology_site.output import console, next_step, ok, warn
from synology_site.ssh_client import SSHClient

# Stands up ONE shared MariaDB instance a NAS's sites can opt into instead of each
# getting their own dedicated container (`create --with-db`/`--db-mode container`).
# Sites that opt in (`--db-mode external`) get a database + user scoped to just their
# own schema via synology_site.database.shared_mariadb.provision_scoped_database --
# this command only stands up the shared engine itself, nothing app-specific.
#
# Container/network names are fixed (not configurable like other bootstrap-* project
# names) because create.py hardcodes SHARED_MARIADB_CONTAINER/SHARED_MARIADB_NETWORK
# as the connection target for every --db-mode external site -- renaming this
# instance would silently break every site already pointed at it.
# The network is created up front via ensure_network() and declared `external: true`
# in this project's own Compose file, matching the existing shared-services/
# supabase_default convention (see ensure_network.py) -- so a later `--force`
# teardown of this project never deletes the network out from under sites still
# attached to it.


@dataclass(frozen=True)
class BootstrapMariadbResult:
    project_path: str
    secrets_file: str
    container_name: str
    network_name: str


SSHFactory = Callable[[Settings, str | None], SSHClient]


def _compose_content(*, image: str, restart_policy: str) -> str:
    return (
        "services:\n"
        f"  {SHARED_MARIADB_CONTAINER}:\n"
        f"    image: {image}\n"
        f"    container_name: {SHARED_MARIADB_CONTAINER}\n"
        f"    restart: {restart_policy}\n"
        "    env_file:\n"
        "      - .env\n"
        "    volumes:\n"
        f"      - {SHARED_MARIADB_VOLUME}:/var/lib/mysql\n"
        "    networks:\n"
        f"      - {SHARED_MARIADB_NETWORK}\n"
        "    healthcheck:\n"
        '      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]\n'
        "      interval: 10s\n"
        "      timeout: 5s\n"
        "      retries: 10\n"
        "\n"
        "volumes:\n"
        f"  {SHARED_MARIADB_VOLUME}:\n"
        "\n"
        "networks:\n"
        f"  {SHARED_MARIADB_NETWORK}:\n"
        "    external: true\n"
    )


def _env_content(*, root_password: str) -> str:
    # No MARIADB_DATABASE/MARIADB_USER here -- unlike a per-site container, this
    # instance never gets its own default database. Every site's schema is created
    # separately, scoped, via provision_scoped_database.
    return f"MARIADB_ROOT_PASSWORD={root_password}\n"


def bootstrap_mariadb(
    *,
    settings: Settings,
    image: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    workspace: str | None = None,
    ssh_factory: SSHFactory = default_ssh_factory,
    secrets_dir: Path = Path("secrets"),
    prompted_password: str | None = None,
) -> BootstrapMariadbResult:
    target = settings.resolve_target(workspace=workspace)
    connection_settings = replace(
        settings,
        nas_host=target.connection_host,
        nas_port=target.port,
        nas_user=target.user,
        nas_ssh_key_path=target.ssh_key_path,
        nas_ssh_password=target.ssh_password,
        ssh_access_hostname=target.ssh_access_hostname,
        ssh_access_local_port=target.ssh_access_local_port,
    )
    project_path = f"{target.docker_root.rstrip('/')}/{SHARED_MARIADB_CONTAINER}"
    selected_image = image or settings.db_image
    env_content = _env_content(root_password=generate_password(settings.db_password_length))

    if dry_run:
        return BootstrapMariadbResult(
            project_path=project_path,
            secrets_file="",
            container_name=SHARED_MARIADB_CONTAINER,
            network_name=SHARED_MARIADB_NETWORK,
        )

    # A separate connection from the one below -- ensure_network manages its own
    # connection lifecycle (open, act, close), so it can't reuse an already-open one
    # without prematurely closing it out from under the rest of this function.
    ensure_network(
        SHARED_MARIADB_NETWORK,
        settings=settings,
        workspace=workspace,
        ssh_factory=ssh_factory,
        prompted_password=prompted_password,
    )

    with ssh_factory(connection_settings, prompted_password) as ssh:
        require_docker(ssh)
        compose = detect_compose_command(ssh)
        ensure_remote_directory(ssh, target.docker_root)

        quoted_project = shlex.quote(project_path)
        exists = ssh.run(f"test -e {quoted_project}")
        if exists.ok:
            if not force:
                msg = (
                    f"Remote project folder already exists: {project_path}. "
                    "Use --force to overwrite."
                )
                raise SynologySiteError(msg)
            ssh.run(f"cd {quoted_project} && {compose} down", check=False)
            ssh.run(f"rm -rf {quoted_project}", check=True)

        ssh.run(f"mkdir -p {quoted_project}", check=True)
        ssh.upload_text(
            f"{project_path}/docker-compose.yml",
            _compose_content(image=selected_image, restart_policy=settings.restart_policy),
        )
        remote_env_path = f"{project_path}/.env"
        ssh.upload_text(remote_env_path, env_content)
        ssh.run(f"chmod 600 {shlex.quote(remote_env_path)}", check=True)
        ssh.run(f"cd {quoted_project} && {compose} up -d", check=True)

        docker = docker_command(ssh)
        result = ssh.run(
            f"{docker} inspect -f '{{{{.State.Running}}}}' {shlex.quote(SHARED_MARIADB_CONTAINER)}"
        )
        if not result.ok or result.stdout.strip().lower() != "true":
            msg = f"Container is not running: {SHARED_MARIADB_CONTAINER}"
            raise SynologySiteError(msg)

    secrets_dir.mkdir(parents=True, exist_ok=True)
    secrets_path = secrets_dir / "mariadb.env"
    secrets_path.write_text(env_content, encoding="utf-8")
    with contextlib.suppress(OSError):
        secrets_path.chmod(0o600)

    return BootstrapMariadbResult(
        project_path=project_path,
        secrets_file=str(secrets_path),
        container_name=SHARED_MARIADB_CONTAINER,
        network_name=SHARED_MARIADB_NETWORK,
    )


def app(
    image: str | None = typer.Option(
        None, "--image", help="Overrides DB_IMAGE from settings (default mariadb:11)."
    ),
    force: bool = typer.Option(False, "--force"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    workspace: str | None = typer.Option(
        None,
        "--workspace",
        help="Force a specific workspace's NAS target (see secrets/<name>/)",
    ),
) -> None:
    try:
        settings = load_config()
        target = settings.resolve_target(workspace=workspace)
        prompted_password = None
        if not target.ssh_key_path and not target.ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        result = bootstrap_mariadb(
            settings=settings,
            image=image,
            force=force or settings.allow_overwrite,
            dry_run=dry_run or settings.dry_run,
            workspace=workspace,
            prompted_password=prompted_password,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Result")
    ok(f"Project folder: {result.project_path}")
    ok(f"Container: {result.container_name}")
    ok(f"Shared network: {result.network_name}")
    if result.secrets_file:
        ok(f"Secrets written to: {result.secrets_file} -- keep this safe, never commit it")
        warn(
            "This file contains the shared instance's MariaDB root password. It is "
            "never used by sites directly -- only to provision each site's own "
            "scoped database/user."
        )
    next_step(
        "Deploy a site against this shared instance with: "
        "synology-site create <domain> --db-mode external"
    )
