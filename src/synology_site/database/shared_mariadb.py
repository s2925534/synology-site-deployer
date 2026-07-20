from __future__ import annotations

import shlex
from pathlib import Path

from synology_site.docker_remote import docker_command
from synology_site.errors import SynologySiteError
from synology_site.ssh_client import SSHClient

# Fixed names for the single shared MariaDB instance a NAS can run instead of one
# MariaDB container per --with-db site. Bootstrapped once via `bootstrap-mariadb`;
# every site opting into `--db-mode external` joins this same container/network
# rather than getting its own.
SHARED_MARIADB_CONTAINER = "shared-mariadb"
SHARED_MARIADB_NETWORK = "shared-mariadb-network"
SHARED_MARIADB_VOLUME = "shared-mariadb-data"


def read_shared_root_password(secrets_dir: Path = Path("secrets")) -> str:
    """Reads MARIADB_ROOT_PASSWORD from secrets/mariadb.env (written by bootstrap-mariadb).

    Never read from Compose/CLI arguments -- this is the shared instance's root
    credential, scoped-grant provisioning is the only thing that ever needs it.
    """
    path = secrets_dir / "mariadb.env"
    if not path.is_file():
        msg = (
            f"{path} not found. Run `synology-site bootstrap-mariadb` first to stand up "
            "the shared MariaDB instance before deploying a site with --db-mode external."
        )
        raise SynologySiteError(msg)
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("MARIADB_ROOT_PASSWORD="):
            password = line.split("=", 1)[1].strip()
            if password:
                return password
    msg = f"MARIADB_ROOT_PASSWORD not found in {path}"
    raise SynologySiteError(msg)


def _quoted_identifier(name: str) -> str:
    """Backtick-quotes a MariaDB identifier (database/user name).

    Every caller derives `name` from `database_name()`/`database_user()`, which already
    restrict output to `[a-z0-9_]` (a validated domain with `.`/`-` replaced by `_`), so
    there's no untrusted input here -- this only guards against a literal backtick ever
    reaching the identifier position, not against injection from arbitrary strings.
    """
    if "`" in name:
        msg = f"Invalid SQL identifier: {name}"
        raise SynologySiteError(msg)
    return f"`{name}`"


def ensure_shared_mariadb_running(
    ssh: SSHClient,
    *,
    container_name: str = SHARED_MARIADB_CONTAINER,
) -> None:
    """Fails fast with an actionable message if the shared instance isn't up yet.

    Bootstraps of the shared network happen together with the container in
    `bootstrap-mariadb`, so confirming the container is running is enough to also
    imply the network exists -- no separate network check needed.
    """
    docker = docker_command(ssh)
    result = ssh.run(f"{docker} inspect -f '{{{{.State.Running}}}}' {shlex.quote(container_name)}")
    if not result.ok or result.stdout.strip().lower() != "true":
        msg = (
            f"Shared MariaDB container '{container_name}' is not running. "
            "Run `synology-site bootstrap-mariadb` first."
        )
        raise SynologySiteError(msg)


def provision_scoped_database(
    ssh: SSHClient,
    *,
    root_password: str,
    db_name: str,
    db_user: str,
    db_password: str,
    container_name: str = SHARED_MARIADB_CONTAINER,
) -> None:
    """Creates a database + user on the shared MariaDB instance, scoped to just that DB.

    Grants are always `ON db_name.*`, never `ON *.*` -- the whole point of sharing one
    engine across sites is that a compromised app can only reach its own schema, not
    every other site's data on the same instance. Idempotent (CREATE ... IF NOT EXISTS,
    REPLACE for the user so a re-run rotates rather than duplicates).
    """
    quoted_db = _quoted_identifier(db_name)
    quoted_user = _quoted_identifier(db_user)
    sql = (
        f"CREATE DATABASE IF NOT EXISTS {quoted_db}; "
        f"CREATE OR REPLACE USER {quoted_user}@'%' IDENTIFIED BY '{db_password}'; "
        f"GRANT ALL PRIVILEGES ON {quoted_db}.* TO {quoted_user}@'%'; "
        "FLUSH PRIVILEGES;"
    )
    docker = docker_command(ssh)
    command = (
        f"{docker} exec -i {shlex.quote(container_name)} "
        f"mariadb -uroot -p{shlex.quote(root_password)} -e {shlex.quote(sql)}"
    )
    ssh.run(command, check=True)
