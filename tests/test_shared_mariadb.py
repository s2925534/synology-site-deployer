from __future__ import annotations

from pathlib import Path

import pytest

from synology_site.database.shared_mariadb import (
    SHARED_MARIADB_CONTAINER,
    ensure_shared_mariadb_running,
    provision_scoped_database,
    read_shared_root_password,
)
from synology_site.errors import SynologySiteError
from synology_site.ssh_client import RemoteCommandResult


class FakeSSH:
    def __init__(self, *, container_running: bool = True) -> None:
        self.container_running = container_running
        self.commands: list[str] = []

    def run(
        self,
        command: str,
        *,
        check: bool = False,
        timeout: int | None = None,
    ) -> RemoteCommandResult:
        del timeout
        self.commands.append(command)
        exit_code = 0
        stdout = ""
        if command == "command -v docker":
            stdout = "docker\n"
        elif command == "docker ps --format '{{.Names}}'":
            stdout = "\n"
        elif command.startswith("docker inspect -f '{{.State.Running}}'"):
            stdout = "true\n" if self.container_running else "false\n"
        result = RemoteCommandResult(command, exit_code, stdout, "")
        if check and not result.ok:
            raise SynologySiteError("command failed")
        return result


def test_read_shared_root_password_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SynologySiteError, match="bootstrap-mariadb"):
        read_shared_root_password(tmp_path)


def test_read_shared_root_password_reads_value(tmp_path: Path) -> None:
    (tmp_path / "mariadb.env").write_text("MARIADB_ROOT_PASSWORD=hunter2\n", encoding="utf-8")

    assert read_shared_root_password(tmp_path) == "hunter2"


def test_ensure_shared_mariadb_running_ok() -> None:
    fake = FakeSSH(container_running=True)

    ensure_shared_mariadb_running(fake)

    assert any(SHARED_MARIADB_CONTAINER in command for command in fake.commands)


def test_ensure_shared_mariadb_running_raises_when_not_running() -> None:
    fake = FakeSSH(container_running=False)

    with pytest.raises(SynologySiteError, match="bootstrap-mariadb"):
        ensure_shared_mariadb_running(fake)


def test_provision_scoped_database_runs_scoped_grant_only() -> None:
    fake = FakeSSH()

    provision_scoped_database(
        fake,
        root_password="rootpw",
        db_name="demo_example_com",
        db_user="demo_example_com_user",
        db_password="sitepw",
    )

    exec_commands = [c for c in fake.commands if "mariadb -uroot" in c]
    assert len(exec_commands) == 1
    command = exec_commands[0]
    assert f"docker exec -i {SHARED_MARIADB_CONTAINER}" in command
    assert "GRANT ALL PRIVILEGES ON `demo_example_com`.*" in command
    assert "ON *.*" not in command
    assert "demo_example_com_user" in command
    assert "sitepw" in command


def test_provision_scoped_database_rejects_backtick_identifier() -> None:
    fake = FakeSSH()

    with pytest.raises(SynologySiteError, match="Invalid SQL identifier"):
        provision_scoped_database(
            fake,
            root_password="rootpw",
            db_name="bad`name",
            db_user="demo_example_com_user",
            db_password="sitepw",
        )
