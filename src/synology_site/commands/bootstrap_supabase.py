from __future__ import annotations

import contextlib
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path

import typer

from synology_site.commands.check_nas import default_ssh_factory
from synology_site.config import Settings, load_config
from synology_site.database.passwords import generate_password
from synology_site.docker_remote import (
    detect_compose_command,
    ensure_remote_directory,
    require_docker,
)
from synology_site.errors import SynologySiteError
from synology_site.output import console, next_step, ok, warn
from synology_site.ssh_client import SSHClient
from synology_site.supabase.env_overrides import apply_env_overrides
from synology_site.supabase.jwt_keys import mint_supabase_keys

# Automates infra/README.md step 2 ("Deploy self-hosted Supabase") for
# ResiLinked: clones Supabase's own docker/ folder (not vendored here --
# they maintain it, copying it in would drift), regenerates the
# security-critical secrets properly (ANON_KEY/SERVICE_ROLE_KEY must be
# JWTs signed with JWT_SECRET, not random strings), and brings it up.

SUPABASE_REPO_URL = "https://github.com/supabase/supabase"
TEN_YEARS_SECONDS = 60 * 60 * 24 * 365 * 10


@dataclass(frozen=True)
class BootstrapSupabaseResult:
    project_path: str
    secrets_file: str
    dashboard_username: str


SSHFactory = Callable[[Settings, str | None], SSHClient]


def bootstrap_supabase(
    *,
    settings: Settings,
    project_dir_name: str = "supabase",
    dashboard_username: str = "supabase",
    postgres_port: int = 5433,
    traefik_override_file: Path | None = None,
    force: bool = False,
    dry_run: bool = False,
    ssh_factory: SSHFactory = default_ssh_factory,
    secrets_dir: Path = Path("secrets"),
    now: int | None = None,
    prompted_password: str | None = None,
) -> BootstrapSupabaseResult:
    project_path = f"{settings.nas_docker_root.rstrip('/')}/{project_dir_name}"
    issued_at = now if now is not None else int(time.time())
    expires_at = issued_at + TEN_YEARS_SECONDS

    with ssh_factory(settings, prompted_password) as ssh:
        require_docker(ssh)
        compose = detect_compose_command(ssh)
        ensure_remote_directory(ssh, settings.nas_docker_root)

        if dry_run:
            return BootstrapSupabaseResult(
                project_path=project_path, secrets_file="", dashboard_username=dashboard_username
            )

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
            # Postgres inside the container writes volumes/db/data as its own
            # container UID, which the SSH user can't remove without sudo --
            # same as Docker itself needing sudo on this NAS.
            ssh.run(f"sudo -S -p '' rm -rf {quoted_project}", check=True)

        clone_dir = f"{project_path}-src"
        quoted_clone = shlex.quote(clone_dir)
        ssh.run(f"rm -rf {quoted_clone}", check=False)
        ssh.run(
            f"git clone --depth 1 {shlex.quote(SUPABASE_REPO_URL)} {quoted_clone}", check=True
        )
        ssh.run(f"mkdir -p {quoted_project}", check=True)
        ssh.run(f"cp -r {quoted_clone}/docker/. {quoted_project}/", check=True)
        ssh.run(f"rm -rf {quoted_clone}", check=True)
        # git doesn't track empty directories -- docker-compose.yml bind-mounts
        # ./volumes/storage and ./volumes/db/data as data-persistence dirs with
        # no tracked file inside them (unlike their sibling volume dirs, which
        # hold real config/SQL files), so the clone omits them and those
        # containers' bind mounts fail unless we create them ourselves.
        ssh.run(f"mkdir -p {quoted_project}/volumes/storage", check=True)
        ssh.run(f"mkdir -p {quoted_project}/volumes/db/data", check=True)

        env_example = ssh.run(f"cat {quoted_project}/.env.example", check=True).stdout

        postgres_password = generate_password(settings.db_password_length)
        jwt_secret = generate_password(max(40, settings.db_password_length))
        secret_key_base = generate_password(64)
        vault_enc_key = generate_password(32)
        dashboard_password = generate_password(24)
        anon_key, service_role_key = mint_supabase_keys(
            jwt_secret, issued_at=issued_at, expires_at=expires_at
        )

        overrides = {
            "POSTGRES_PASSWORD": postgres_password,
            # Default (5432) commonly collides with a NAS's own native
            # services (e.g. Synology packages that run their own local
            # Postgres). Nothing needs this published on the host anyway --
            # apps on the supabase_default network reach Postgres via
            # supabase-db/supabase-pooler's container names, not this port.
            "POSTGRES_PORT": str(postgres_port),
            "JWT_SECRET": jwt_secret,
            "ANON_KEY": anon_key,
            "SERVICE_ROLE_KEY": service_role_key,
            "DASHBOARD_USERNAME": dashboard_username,
            "DASHBOARD_PASSWORD": dashboard_password,
            "SECRET_KEY_BASE": secret_key_base,
            "VAULT_ENC_KEY": vault_enc_key,
        }
        final_env = apply_env_overrides(env_example, overrides)
        remote_env_path = f"{project_path}/.env"
        ssh.upload_text(remote_env_path, final_env)
        ssh.run(f"chmod 600 {shlex.quote(remote_env_path)}", check=True)

        compose_file_args = ""
        if traefik_override_file is not None:
            if not traefik_override_file.is_file():
                msg = f"Traefik override file not found: {traefik_override_file}"
                raise SynologySiteError(msg)
            ssh.upload_text(
                f"{project_path}/docker-compose.override.yml",
                traefik_override_file.read_text(encoding="utf-8"),
            )
            # Supabase's own .env pins COMPOSE_FILE=docker-compose.yml, which
            # silently disables Compose's normal docker-compose.override.yml
            # auto-discovery -- so the override must be passed explicitly.
            compose_file_args = " -f docker-compose.yml -f docker-compose.override.yml"

        ssh.run(f"cd {quoted_project} && {compose}{compose_file_args} up -d", check=True)

    secrets_dir.mkdir(parents=True, exist_ok=True)
    secrets_path = secrets_dir / f"{project_dir_name}.env"
    secrets_path.write_text(final_env, encoding="utf-8")
    with contextlib.suppress(OSError):
        secrets_path.chmod(0o600)

    return BootstrapSupabaseResult(
        project_path=project_path,
        secrets_file=str(secrets_path),
        dashboard_username=dashboard_username,
    )


def app(
    project_dir_name: str = typer.Option("supabase", "--project-dir-name"),
    dashboard_username: str = typer.Option("supabase", "--dashboard-username"),
    postgres_port: int = typer.Option(
        5433, "--postgres-port", help="Host port for direct Postgres access (avoid 5432 if a "
        "NAS package already uses it)"
    ),
    traefik_override: Path | None = typer.Option(  # noqa: B008
        None,
        "--traefik-override",
        exists=True,
        dir_okay=False,
        help="Local docker-compose.override.yml adding Traefik labels to Supabase's "
        "kong/studio services, uploaded into the project directory before startup",
    ),
    force: bool = typer.Option(False, "--force"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    try:
        settings = load_config()
        prompted_password = None
        if not settings.nas_ssh_key_path and not settings.nas_ssh_password:
            prompted_password = getpass("NAS SSH password: ")
        result = bootstrap_supabase(
            settings=settings,
            project_dir_name=project_dir_name,
            dashboard_username=dashboard_username,
            postgres_port=postgres_port,
            traefik_override_file=traefik_override,
            force=force or settings.allow_overwrite,
            dry_run=dry_run or settings.dry_run,
            prompted_password=prompted_password,
        )
    except SynologySiteError as exc:
        console.print(f"[ERROR] {exc}")
        raise typer.Exit(1) from exc

    console.rule("Result")
    ok(f"Project folder: {result.project_path}")
    if result.secrets_file:
        ok(f"Secrets written to: {result.secrets_file} -- keep this safe, never commit it")
        warn(
            "This file has the Postgres password, JWT secret, anon/service-role keys, and "
            "Studio dashboard credentials in plaintext."
        )
    next_step(
        "Check container health with `docker ps` on the NAS (supabase-db, supabase-kong, ...)"
    )
