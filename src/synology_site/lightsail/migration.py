from __future__ import annotations

import base64
import gzip
import shlex
import tarfile
import zipfile
from pathlib import Path

from synology_site.docker_remote import docker_command
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
    """
    command = (
        f"MYSQL_PWD={shlex.quote(db_password)} mariadb-dump --no-tablespaces "
        f"-h {shlex.quote(db_host)} -u{shlex.quote(db_user)} {shlex.quote(db_name)} "
        "| gzip -c | base64"
    )
    result = ssh.run(command)
    if not result.ok or not result.stdout.strip():
        command = command.replace("mariadb-dump", "mysqldump", 1)
        result = ssh.run(command, check=True)
    return gzip.decompress(base64.b64decode(result.stdout))


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
    command = (
        f"{docker} exec -i {shlex.quote(container_name)} sh -c "
        f"'MYSQL_PWD={shlex.quote(db_password)} mariadb-dump --no-tablespaces "
        f"-u{shlex.quote(db_user)} {shlex.quote(db_name)}' | gzip -c | base64"
    )
    result = ssh.run(command, check=True)
    return gzip.decompress(base64.b64decode(result.stdout))


def _drop_all_tables(
    ssh: SSHClient,
    *,
    container_name: str,
    db_name: str,
    db_user: str,
    db_password: str,
) -> None:
    docker = docker_command(ssh)
    list_command = (
        f"{docker} exec -i {shlex.quote(container_name)} sh -c "
        f"'MYSQL_PWD={shlex.quote(db_password)} mariadb -N -u{shlex.quote(db_user)} "
        f'-e "SHOW TABLES" {shlex.quote(db_name)}\''
    )
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
    drop_command = (
        f"{docker} exec -i {shlex.quote(container_name)} sh -c "
        f"'MYSQL_PWD={shlex.quote(db_password)} mariadb -u{shlex.quote(db_user)} "
        f"{shlex.quote(db_name)} -e {shlex.quote(drop_sql)}'"
    )
    ssh.run(drop_command, check=True)


def restore_container_database(
    ssh: SSHClient,
    *,
    container_name: str,
    db_name: str,
    db_user: str,
    db_password: str,
    sql_text: str,
    project_path: str,
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
    remote_dump_path = f"{project_path}/.migration-dump.sql"
    ssh.upload_text(remote_dump_path, sql_text)
    ssh.run(f"chmod 600 {shlex.quote(remote_dump_path)}", check=True)
    command = (
        f"{docker} exec -i {shlex.quote(container_name)} sh -c "
        f"'MYSQL_PWD={shlex.quote(db_password)} mariadb -u{shlex.quote(db_user)} "
        f"{shlex.quote(db_name)}' < {shlex.quote(remote_dump_path)}"
    )
    result = ssh.run(command)
    ssh.run(f"rm -f {shlex.quote(remote_dump_path)}")
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
