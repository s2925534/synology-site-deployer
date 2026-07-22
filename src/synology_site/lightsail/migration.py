from __future__ import annotations

import base64
import gzip
import io
import shlex
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from synology_site.docker_remote import detect_compose_command, docker_command
from synology_site.errors import SynologySiteError
from synology_site.ssh_client import SSHClient

# Every function here that touches the Lightsail source only ever reads against it, with one
# deliberate, documented exception: create_full_site_archive (the --transfer-mode full-archive
# path) writes a staging bundle + a zip to the source's own disk to build one self-contained
# archive, and *always* removes both again (try/finally) before returning or raising, so the
# source ends the call in exactly the state it started -- see that function's docstring.
# Every other function (dump_host_database, dump_container_database, fetch_wp_content, ...)
# streams data straight through the SSH channel and never touches the source's filesystem at all.


def dump_host_database(
    ssh: SSHClient,
    *,
    db_name: str,
    db_user: str,
    db_password: str,
    db_host: str = "localhost",
) -> bytes:
    """Dumps a database running directly on the SSH host (the Lightsail source has no Docker DB
    container -- MariaDB/MySQL runs as a plain system service). Read-only against the source.
    Returns raw (ungzipped) SQL bytes. Uses MYSQL_PWD rather than -p<password> so the password
    doesn't appear in mariadb-dump's own argv (see lightsail-migration-mvp.md for the residual
    exposure this doesn't fully close -- the wrapping shell's argv still carries it for the
    pipeline's duration, an accepted trade-off on these single-operator hosts).

    Picks the dump binary via an explicit `command -v` check rather than trying mariadb-dump
    and inferring failure from its output: a command piped into `| gzip -c | base64` still
    exits 0 even when the piped-from command itself failed (gzip/base64 of empty/garbage input
    is itself valid), so failure can't be detected from the pipeline's own exit code or from
    whether the base64 text happens to be non-empty -- both stayed "successful-looking" against
    a real host that had no `mariadb-dump` binary at all (only `mysqldump`), silently producing
    an empty dump that a caller could easily mistake for a real (if small) one.
    """
    binary = "mariadb-dump" if ssh.run("command -v mariadb-dump").ok else "mysqldump"
    command = (
        f"MYSQL_PWD={shlex.quote(db_password)} {binary} --no-tablespaces "
        f"-h {shlex.quote(db_host)} -u{shlex.quote(db_user)} {shlex.quote(db_name)} "
        "| gzip -c | base64"
    )
    result = ssh.run(command, check=True)
    decompressed = gzip.decompress(base64.b64decode(result.stdout))
    if not decompressed.strip():
        msg = f"{binary} produced no output for database {db_name!r} -- check credentials/access"
        raise SynologySiteError(msg)
    return decompressed


def dump_container_database(
    ssh: SSHClient,
    *,
    container_name: str,
    db_name: str,
    db_user: str,
    db_password: str,
) -> bytes:
    """Dumps a database living inside a running Docker container -- used to back up the
    *target*'s current DB before an existing-site-replace overwrite."""
    docker = docker_command(ssh)
    inner = (
        f"MYSQL_PWD={shlex.quote(db_password)} mariadb-dump --no-tablespaces "
        f"-u{shlex.quote(db_user)} {shlex.quote(db_name)}"
    )
    command = (
        f"{docker} exec -i {shlex.quote(container_name)} sh -c {shlex.quote(inner)} "
        "| gzip -c | base64"
    )
    result = ssh.run(command, check=True)
    decompressed = gzip.decompress(base64.b64decode(result.stdout))
    if not decompressed.strip():
        msg = f"mariadb-dump produced no output for database {db_name!r} in {container_name!r}"
        raise SynologySiteError(msg)
    return decompressed


def _drop_all_tables(
    ssh: SSHClient,
    *,
    container_name: str,
    db_name: str,
    db_user: str,
    db_password: str,
) -> None:
    docker = docker_command(ssh)
    list_inner = (
        f"MYSQL_PWD={shlex.quote(db_password)} mariadb -N -u{shlex.quote(db_user)} "
        f"-e {shlex.quote('SHOW TABLES')} {shlex.quote(db_name)}"
    )
    list_command = f"{docker} exec -i {shlex.quote(container_name)} sh -c {shlex.quote(list_inner)}"
    tables = [
        line.strip()
        for line in ssh.run(list_command, check=True).stdout.splitlines()
        if line.strip()
    ]
    if not tables:
        return
    drop_sql = "SET FOREIGN_KEY_CHECKS=0; " + "".join(
        f"DROP TABLE IF EXISTS `{table}`; " for table in tables
    )
    # The whole inner `sh -c` argument is wrapped in exactly one shlex.quote() call here --
    # not hand-typed outer quotes around individually-quoted pieces. drop_sql contains
    # backticks/semicolons/spaces, so shlex.quote(drop_sql) alone needs its own surrounding
    # quotes; nesting that inside a second, manually-written pair of quotes breaks the shell's
    # parsing (the inner quote prematurely closes the outer one), and the now-unquoted
    # backtick-wrapped table names get interpreted as command substitution instead of literal
    # SQL -- confirmed against the real target, which failed with exit 127 ("command not
    # found") for exactly this reason before this fix.
    drop_inner = (
        f"MYSQL_PWD={shlex.quote(db_password)} mariadb -u{shlex.quote(db_user)} "
        f"{shlex.quote(db_name)} -e {shlex.quote(drop_sql)}"
    )
    drop_command = f"{docker} exec -i {shlex.quote(container_name)} sh -c {shlex.quote(drop_inner)}"
    ssh.run(drop_command, check=True)


def restore_container_database(
    ssh: SSHClient,
    *,
    container_name: str,
    db_name: str,
    db_user: str,
    db_password: str,
    sql_text: str,
    drop_existing_tables: bool = False,
) -> None:
    """Imports sql_text into an existing schema inside a running container. Never swaps in
    different DB credentials -- container_name/db_name/db_user/db_password must already be the
    target's own. drop_existing_tables is set only for existing-site-replace (new-site's schema
    is already empty from create_site()'s fresh provisioning).
    """
    docker = docker_command(ssh)
    if drop_existing_tables:
        _drop_all_tables(
            ssh,
            container_name=container_name,
            db_name=db_name,
            db_user=db_user,
            db_password=db_password,
        )
    inner = (
        f"MYSQL_PWD={shlex.quote(db_password)} mariadb -u{shlex.quote(db_user)} "
        f"{shlex.quote(db_name)}"
    )
    command = f"{docker} exec -i {shlex.quote(container_name)} sh -c {shlex.quote(inner)}"
    # Fed via ssh.run's own stdin= parameter, not a shell `< file` redirect: when
    # docker_command() resolves to a sudo-prefixed binary (as it does on Synology NAS targets),
    # `sudo -S` reads its password from the command's own stdin -- a `< file` redirect steals
    # that stdin away from sudo before mariadb ever sees it, so sudo fails with "no password
    # was provided" (confirmed against the real target). ssh.run's stdin= instead writes the
    # sudo password first, then this payload, over the same channel -- no redirect involved, no
    # conflict, and no temp file to upload/chmod/clean up either.
    result = ssh.run(command, stdin=sql_text)
    if not result.ok:
        msg = f"Database restore failed for {db_name}: {result.stderr or result.stdout}"
        raise SynologySiteError(msg)


def fetch_wp_content(ssh: SSHClient, doc_root: str, local_tmp_dir: Path) -> Path:
    """Downloads doc_root/wp-content as a tar+gzip+base64 blob over the SSH channel and decodes
    it locally. Read-only against the source. Memory-bound (the whole tarball is held in process
    memory and written to a temp dir) -- fine for sites in the ~100-200MB range like the real
    migration target; a known limitation for much larger sites, not solved here.
    """
    command = f"tar czf - -C {shlex.quote(doc_root)} wp-content | base64"
    result = ssh.run(command, check=True)
    archive_path = local_tmp_dir / "wp-content.tar.gz"
    archive_path.write_bytes(base64.b64decode(result.stdout))
    with tarfile.open(archive_path) as tar:
        tar.extractall(local_tmp_dir, filter="data")
    return local_tmp_dir / "wp-content"


def push_wp_content(ssh: SSHClient, local_wp_content_dir: Path, project_path: str) -> list[str]:
    return ssh.upload_directory(local_wp_content_dir, f"{project_path}/wp-content")


def create_full_site_archive(
    ssh: SSHClient,
    *,
    doc_root: str,
    nginx_config_path: str | None,
    sql_dump_bytes: bytes,
) -> bytes:
    """Builds one self-contained zip of the whole WordPress site for --transfer-mode
    full-archive: doc_root (WP core + wp-content) plus a `_migration_bundle/` folder holding the
    DB dump and, best-effort, the Nginx vhost config and any Let's Encrypt cert/key found for the
    domain. The cert/nginx config are captured for reference in the migration backup only --
    not required by the NAS target (Cloudflare Tunnel terminates TLS there; Traefik replaces
    Nginx), and their absence never fails the archive.

    Unlike every other function in this module, this one writes to the source's disk (the bundle
    folder + the zip itself) -- but only ever temporarily. The `finally` block below always
    removes both again, whether this call succeeds or raises, so the source ends the call in
    exactly the state it started.
    """
    bundle_dir = f"{doc_root}/_migration_bundle"
    archive_path = f"/tmp/{Path(doc_root).name}-site-bundle.zip"
    if not ssh.run("command -v zip").ok:
        raise SynologySiteError(
            "`zip` is not installed on the source -- install it (e.g. `apt-get install zip`) "
            "or re-run with --transfer-mode direct instead."
        )
    try:
        ssh.run(f"mkdir -p {shlex.quote(bundle_dir)}", check=True)
        ssh.upload_text(
            f"{bundle_dir}/database.sql",
            sql_dump_bytes.decode("utf-8", errors="replace"),
        )
        if nginx_config_path:
            ssh.run(
                f"cp {shlex.quote(nginx_config_path)} "
                f"{shlex.quote(bundle_dir)}/nginx.conf 2>/dev/null || true"
            )
        ssh.run(
            f"cp -rL /etc/letsencrypt/live/*/ {shlex.quote(bundle_dir)}/certs/ 2>/dev/null || true"
        )
        zip_command = (
            f"cd {shlex.quote(str(Path(doc_root).parent))} && "
            f"zip -qr {shlex.quote(archive_path)} {shlex.quote(Path(doc_root).name)} "
            f"&& base64 {shlex.quote(archive_path)}"
        )
        result = ssh.run(zip_command, check=True)
        return base64.b64decode(result.stdout)
    finally:
        ssh.run(f"rm -rf {shlex.quote(bundle_dir)}")
        ssh.run(f"rm -f {shlex.quote(archive_path)}")


def extract_full_site_archive(archive_bytes: bytes, local_tmp_dir: Path) -> Path:
    """Unzips a create_full_site_archive() blob locally and returns the extracted doc_root
    (containing wp-content, the rest of WP core, and `_migration_bundle/`). Only wp-content is
    actually pushed to the NAS by callers -- WP core comes from the wordpress:apache image
    there, not from this archive.
    """
    archive_path = local_tmp_dir / "site-bundle.zip"
    archive_path.write_bytes(archive_bytes)
    with zipfile.ZipFile(archive_path) as zf:
        zf.extractall(local_tmp_dir)
    extracted_dirs = [path for path in local_tmp_dir.iterdir() if path.is_dir()]
    if len(extracted_dirs) != 1:
        msg = "Expected exactly one top-level directory in the site archive"
        raise SynologySiteError(msg)
    return extracted_dirs[0]


# --- Generalized existing-deployment inspection ---------------------------------------------
#
# The `wordpress` scaffold this tool generates (app/.env, wp-content bind-mounted, a numeric
# port in the marker) is one possible shape for an existing-site-replace target -- but a target
# may equally have been deployed by hand or via the generic `deploy` command, with its own
# Compose file that doesn't follow that layout at all (DB creds partly hardcoded in the compose
# file rather than .env, wp-content as a named Docker volume instead of a bind mount, no
# published port at all if it's Traefik-routed). `inspect_existing_wordpress_deployment` reads
# whatever is *actually* there via `docker compose config`, which fully resolves ${VAR}
# interpolation using Compose's own env-file handling -- no hand-rolled substitution needed.

WP_CONTENT_TARGET = "/var/www/html/wp-content"


@dataclass(frozen=True)
class ExistingWordPressDeployment:
    container_name: str
    db_host: str
    db_name: str
    db_user: str
    db_password: str
    table_prefix: str
    wp_content_is_volume: bool
    wp_content_source: str
    github_sync_repo: str | None = None


def inspect_existing_wordpress_deployment(
    ssh: SSHClient, *, project_path: str, compose_file: str = "docker-compose.yml"
) -> ExistingWordPressDeployment:
    """Read-only: introspects an already-deployed WordPress site's actual Compose configuration.
    Works whether or not the target follows this tool's own `wordpress` scaffold layout.
    """
    compose = detect_compose_command(ssh)
    quoted_dir = shlex.quote(project_path)
    quoted_file = shlex.quote(compose_file)
    result = ssh.run(f"cd {quoted_dir} && {compose} -f {quoted_file} config", check=True)
    config = yaml.safe_load(result.stdout) or {}
    services = config.get("services") or {}

    service_name, service = _find_wordpress_service(services)
    env = _normalize_environment(service.get("environment"))

    db_name = env.get("WORDPRESS_DB_NAME")
    db_user = env.get("WORDPRESS_DB_USER")
    db_password = env.get("WORDPRESS_DB_PASSWORD")
    db_host = env.get("WORDPRESS_DB_HOST")
    if not all([db_name, db_user, db_password, db_host]):
        msg = (
            "Could not determine WORDPRESS_DB_HOST/NAME/USER/PASSWORD for the existing "
            f"deployment at {project_path} (checked {compose_file}'s resolved environment)"
        )
        raise SynologySiteError(msg)

    volume_names = set((config.get("volumes") or {}).keys())
    wp_content_is_volume, wp_content_source = _resolve_wp_content_mount(service, volume_names)

    return ExistingWordPressDeployment(
        container_name=service.get("container_name") or service_name,
        db_host=db_host,
        db_name=db_name,
        db_user=db_user,
        db_password=db_password,
        table_prefix=env.get("WORDPRESS_TABLE_PREFIX", "wp_"),
        wp_content_is_volume=wp_content_is_volume,
        wp_content_source=wp_content_source,
        github_sync_repo=env.get("GITHUB_SYNC_REPO"),
    )


def _find_wordpress_service(services: dict) -> tuple[str, dict]:
    for name, service in services.items():
        env = _normalize_environment(service.get("environment"))
        if "WORDPRESS_DB_NAME" in env or str(service.get("image", "")).startswith("wordpress"):
            return name, service
    raise SynologySiteError("Could not find a WordPress service in the resolved Compose config")


def _normalize_environment(environment: object) -> dict[str, str]:
    if isinstance(environment, dict):
        return {key: str(value) for key, value in environment.items() if value is not None}
    if isinstance(environment, list):
        result: dict[str, str] = {}
        for item in environment:
            if isinstance(item, str) and "=" in item:
                key, value = item.split("=", 1)
                result[key] = value
        return result
    return {}


def _resolve_wp_content_mount(service: dict, volume_names: set[str]) -> tuple[bool, str]:
    for volume_entry in service.get("volumes") or []:
        if isinstance(volume_entry, dict):
            if volume_entry.get("target") == WP_CONTENT_TARGET:
                return volume_entry.get("type") == "volume", volume_entry.get("source", "")
        elif isinstance(volume_entry, str) and volume_entry.endswith(f":{WP_CONTENT_TARGET}"):
            source = volume_entry.split(":", 1)[0]
            return source in volume_names, source
    msg = f"Could not find a {WP_CONTENT_TARGET} volume/bind mount in the resolved Compose config"
    raise SynologySiteError(msg)


def dump_wp_content_volume(ssh: SSHClient, *, container_name: str, local_tmp_dir: Path) -> Path:
    """Like fetch_wp_content, but for wp-content stored in a named Docker volume rather than a
    host bind mount -- reads it via `docker exec` into the WordPress container that already has
    the volume mounted at WP_CONTENT_TARGET, running as www-data (the same user that serves the
    site), rather than a throwaway container. A throwaway container defaults to running as root,
    which corrupts file ownership on the write side (see push_wp_content_to_volume) -- reading
    via the real app container keeps both operations consistent and avoids pulling a second
    image (e.g. alpine) onto the target at all.
    """
    docker = docker_command(ssh)
    command = (
        f"{docker} exec -u www-data {shlex.quote(container_name)} "
        f"tar czf - -C {shlex.quote(WP_CONTENT_TARGET)} . | base64"
    )
    result = ssh.run(command, check=True)
    if not result.stdout.strip():
        msg = (
            f"Reading wp-content from container {container_name!r} produced no output -- "
            "check the container is running and www-data can read its own wp-content."
        )
        raise SynologySiteError(msg)
    archive_path = local_tmp_dir / "wp-content-volume.tar.gz"
    archive_path.write_bytes(base64.b64decode(result.stdout))
    extract_dir = local_tmp_dir / "wp-content-from-volume"
    extract_dir.mkdir()
    with tarfile.open(archive_path) as tar:
        tar.extractall(extract_dir, filter="data")
    return extract_dir


def push_wp_content_to_volume(
    ssh: SSHClient, local_wp_content_dir: Path, *, container_name: str
) -> None:
    """Replaces a named Docker volume's contents with local_wp_content_dir, via `docker exec -i`
    into the WordPress container itself (running as www-data) rather than a throwaway container
    bind-mounting the volume. The local directory is tarred + base64-encoded in memory and fed
    over the same channel `ssh.run`'s stdin= already uses for the sudo password (see
    restore_container_database) -- no temp file upload, no separate image pull, and files land
    owned by www-data instead of root. A previous version ran a throwaway `alpine` container
    (default root user) for this, which left every restored file root-owned and unwritable by
    the actual serving process -- confirmed against the real target via WordPress/Elementor
    "Permission denied" errors trying to update its own cache files after migration.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for entry in sorted(local_wp_content_dir.iterdir()):
            tar.add(entry, arcname=entry.name)
    encoded = base64.b64encode(buffer.getvalue()).decode()
    docker = docker_command(ssh)
    inner = (
        f"find {shlex.quote(WP_CONTENT_TARGET)} -mindepth 1 -delete; "
        f"base64 -d | tar xzf - -C {shlex.quote(WP_CONTENT_TARGET)}"
    )
    command = (
        f"{docker} exec -i -u www-data {shlex.quote(container_name)} sh -c {shlex.quote(inner)}"
    )
    result = ssh.run(command, stdin=encoded)
    if not result.ok:
        detail = result.stderr or result.stdout
        msg = f"Failed to populate wp-content for container {container_name!r}: {detail}"
        raise SynologySiteError(msg)
