from __future__ import annotations

import shlex

import pytest

from synology_site.data_safety import (
    StoreRef,
    check_data_mount_safety,
    detect_orphaning_changes,
    parse_data_mounts,
    snapshot_databases,
)
from synology_site.errors import SynologySiteError
from synology_site.ssh_client import RemoteCommandResult

PROJECT = "/volume1/docker/systemsnotsilos-com"

BIND_COMPOSE = """
services:
  systemsnotsilos-com:
    image: wordpress:latest
    volumes:
      - ./wp-content:/var/www/html/wp-content
      - ./theme/systemsnotsilos:/var/www/html/wp-content/themes/systemsnotsilos
  systemsnotsilos-com-db:
    image: mariadb:11
    volumes:
      - ./db-data:/var/lib/mysql
"""

NAMED_COMPOSE = """
services:
  systemsnotsilos-com:
    image: wordpress:latest
    volumes:
      - systemsnotsilos-com-wp-content:/var/www/html/wp-content
      - ./theme/systemsnotsilos:/var/www/html/wp-content/themes/systemsnotsilos
  systemsnotsilos-com-db:
    image: mariadb:11
    volumes:
      - systemsnotsilos-com-db-data:/var/lib/mysql
volumes:
  systemsnotsilos-com-wp-content:
    name: systemsnotsilos-com-wp-content
  systemsnotsilos-com-db-data:
    name: systemsnotsilos-com-db-data
"""


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


def test_parse_resolves_binds_relative_to_compose_dir_and_named_volumes() -> None:
    mounts = parse_data_mounts(NAMED_COMPOSE, PROJECT)

    assert mounts[("systemsnotsilos-com-db", "/var/lib/mysql")] == StoreRef(
        "named", "systemsnotsilos-com-db-data"
    )
    assert mounts[("systemsnotsilos-com", "/var/www/html/wp-content")] == StoreRef(
        "named", "systemsnotsilos-com-wp-content"
    )
    # Relative bind resolves against the compose directory, like Compose does.
    assert mounts[
        ("systemsnotsilos-com", "/var/www/html/wp-content/themes/systemsnotsilos")
    ] == StoreRef("bind", f"{PROJECT}/theme/systemsnotsilos")


def test_parse_handles_modes_long_syntax_and_skips_anonymous() -> None:
    compose = """
    services:
      db:
        image: mariadb:11
        volumes:
          - ./data:/var/lib/mysql:ro
          - type: bind
            source: /abs/uploads
            target: /uploads
          - type: volume
            source: cache
            target: /cache
          - /var/lib/anonymous
    """
    mounts = parse_data_mounts(compose, "/proj")

    assert mounts[("db", "/var/lib/mysql")] == StoreRef("bind", "/proj/data")
    assert mounts[("db", "/uploads")] == StoreRef("bind", "/abs/uploads")
    assert mounts[("db", "/cache")] == StoreRef("named", "cache")
    # A bare container path (anonymous volume) is not a tracked store.
    assert all(target != "/var/lib/anonymous" for _service, target in mounts)


# --------------------------------------------------------------------------
# orphaning detection
# --------------------------------------------------------------------------


def _populated(*stores: StoreRef):
    populated = set(stores)
    return lambda store: store in populated


def test_detects_bind_to_fresh_named_volume_on_db_datadir() -> None:
    old = parse_data_mounts(BIND_COMPOSE, PROJECT)
    new = parse_data_mounts(NAMED_COMPOSE, PROJECT)
    # Old bind datadir holds data; the new named volumes do not exist yet.
    has_data = _populated(
        StoreRef("bind", f"{PROJECT}/db-data"),
        StoreRef("bind", f"{PROJECT}/wp-content"),
    )

    changes = detect_orphaning_changes(old, new, has_data)

    targets = {c.target for c in changes}
    assert targets == {"/var/lib/mysql", "/var/www/html/wp-content"}


def test_no_change_when_store_identical() -> None:
    mounts = parse_data_mounts(BIND_COMPOSE, PROJECT)
    has_data = _populated(StoreRef("bind", f"{PROJECT}/db-data"))

    assert detect_orphaning_changes(mounts, mounts, has_data) == []


def test_non_stateful_bind_change_is_ignored() -> None:
    old = parse_data_mounts(
        "services:\n  web:\n    volumes:\n      - ./theme-a:/var/www/html/themes/x\n",
        PROJECT,
    )
    new = parse_data_mounts(
        "services:\n  web:\n    volumes:\n      - ./theme-b:/var/www/html/themes/x\n",
        PROJECT,
    )
    has_data = _populated(StoreRef("bind", f"{PROJECT}/theme-a"))

    # A moved code bind (not a stateful target, neither side a named volume)
    # is not our concern -- only data stores are guarded.
    assert detect_orphaning_changes(old, new, has_data) == []


def test_no_change_when_old_store_is_empty() -> None:
    old = parse_data_mounts(BIND_COMPOSE, PROJECT)
    new = parse_data_mounts(NAMED_COMPOSE, PROJECT)

    # Nothing populated -> nothing to orphan.
    assert detect_orphaning_changes(old, new, lambda _store: False) == []


def test_no_change_when_new_store_already_has_data() -> None:
    old = parse_data_mounts(BIND_COMPOSE, PROJECT)
    new = parse_data_mounts(NAMED_COMPOSE, PROJECT)
    # Both old and new hold data (e.g. a prior migration already copied it).
    changes = detect_orphaning_changes(old, new, lambda _store: True)

    assert changes == []


# --------------------------------------------------------------------------
# NAS-backed guard + snapshot
# --------------------------------------------------------------------------


class FakeSSH:
    def __init__(
        self,
        *,
        files: dict[str, str] | None = None,
        dirs_with_data: set[str] | None = None,
        volumes: set[str] | None = None,
    ) -> None:
        self.files = files or {}
        self.dirs_with_data = dirs_with_data or set()
        self.volumes = volumes or set()
        self.commands: list[str] = []

    def run(self, command: str, *, check: bool = False, timeout: int | None = None):
        del timeout
        self.commands.append(command)
        exit_code, stdout = self._respond(command)
        result = RemoteCommandResult(command, exit_code, stdout, "")
        if check and not result.ok:
            raise SynologySiteError(f"command failed: {command}")
        return result

    def _respond(self, command: str) -> tuple[int, str]:
        tokens = shlex.split(command)
        if tokens[:1] == ["cat"]:
            path = tokens[1]
            return (0, self.files[path]) if path in self.files else (1, "")
        if "volume" in tokens and "inspect" in tokens:
            return (0, "") if tokens[-1] in self.volumes else (1, "")
        if tokens[:2] == ["test", "-d"]:
            return (0, "") if tokens[2] in self.dirs_with_data else (1, "")
        return (0, "")


def _deployed_files(compose_text: str) -> dict[str, str]:
    return {
        f"{PROJECT}/.synology-site.json": '{"compose_file": "docker-compose.yml"}',
        f"{PROJECT}/docker-compose.yml": compose_text,
    }


def test_guard_blocks_bind_to_named_volume_swap() -> None:
    ssh = FakeSSH(
        files=_deployed_files(BIND_COMPOSE),
        dirs_with_data={f"{PROJECT}/db-data", f"{PROJECT}/wp-content"},
        volumes=set(),  # the new named volumes do not exist yet
    )

    with pytest.raises(SynologySiteError, match="orphaning the"):
        check_data_mount_safety(
            ssh,
            docker_cmd="docker",
            project_path=PROJECT,
            new_compose_text=NAMED_COMPOSE,
            new_compose_dir=PROJECT,
            allow_data_mount_change=False,
        )


def test_guard_allows_override_flag() -> None:
    ssh = FakeSSH(
        files=_deployed_files(BIND_COMPOSE),
        dirs_with_data={f"{PROJECT}/db-data", f"{PROJECT}/wp-content"},
    )

    # Must not raise when explicitly overridden.
    check_data_mount_safety(
        ssh,
        docker_cmd="docker",
        project_path=PROJECT,
        new_compose_text=NAMED_COMPOSE,
        new_compose_dir=PROJECT,
        allow_data_mount_change=True,
    )


def test_guard_noop_on_first_deploy() -> None:
    ssh = FakeSSH(files={})  # nothing deployed yet

    check_data_mount_safety(
        ssh,
        docker_cmd="docker",
        project_path=PROJECT,
        new_compose_text=NAMED_COMPOSE,
        new_compose_dir=PROJECT,
        allow_data_mount_change=False,
    )


def test_guard_allows_unchanged_bind_redeploy() -> None:
    ssh = FakeSSH(
        files=_deployed_files(BIND_COMPOSE),
        dirs_with_data={f"{PROJECT}/db-data", f"{PROJECT}/wp-content"},
    )

    # Same bind mounts on both sides -> safe redeploy, no raise.
    check_data_mount_safety(
        ssh,
        docker_cmd="docker",
        project_path=PROJECT,
        new_compose_text=BIND_COMPOSE,
        new_compose_dir=PROJECT,
        allow_data_mount_change=False,
    )


def test_snapshot_tars_populated_db_datadir() -> None:
    ssh = FakeSSH(
        files=_deployed_files(BIND_COMPOSE),
        dirs_with_data={f"{PROJECT}/db-data"},
    )

    notes = snapshot_databases(ssh, docker_cmd="docker", project_path=PROJECT)

    assert notes == ["systemsnotsilos-com-db: bind /volume1/docker/systemsnotsilos-com/db-data"]
    assert any(f"mkdir -p {PROJECT}/backups" in c for c in ssh.commands)
    tar_cmds = [c for c in ssh.commands if "tar czf" in c]
    assert len(tar_cmds) == 1
    assert f"cd {PROJECT}" in tar_cmds[0]
    assert "db-data" in tar_cmds[0]
    # wp-content is guarded by the block, not tar'd here (only DB datadirs snapshot).
    assert all("wp-content" not in c for c in tar_cmds)


def test_snapshot_noop_when_datadir_empty() -> None:
    ssh = FakeSSH(files=_deployed_files(BIND_COMPOSE), dirs_with_data=set())

    assert snapshot_databases(ssh, docker_cmd="docker", project_path=PROJECT) == []
    assert all("tar czf" not in c for c in ssh.commands)
