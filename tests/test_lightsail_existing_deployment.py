from __future__ import annotations

import base64
import io
import tarfile
from pathlib import Path

import pytest

from synology_site.errors import SynologySiteError
from synology_site.lightsail.migration import (
    dump_wp_content_volume,
    inspect_existing_wordpress_deployment,
    push_wp_content_to_volume,
)
from synology_site.ssh_client import RemoteCommandResult

PROJECT_PATH = "/volume1/docker/systemsnotsilos-com"

DOCKER_RESOLUTION_RESPONSES: dict[str, tuple[int, str]] = {
    "command -v docker": (0, "docker\n"),
    "docker ps --format '{{.Names}}'": (0, ""),
}

# Real shape of `docker compose config`'s output for the actual systemsnotsilos.com deployment
# (values redacted/simplified) -- named-volume wp-content, DB host/name/user hardcoded in the
# compose file itself (only the password came from .env, already resolved here), plus the
# GitHub-sync mu-plugin's env vars.
VOLUME_BASED_CONFIG = """
services:
  systemsnotsilos-com:
    image: wordpress:latest
    container_name: systemsnotsilos-com
    environment:
      WORDPRESS_DB_HOST: systemsnotsilos-com-db
      WORDPRESS_DB_NAME: systemsnotsilos_com
      WORDPRESS_DB_USER: systemsnotsilos_com_user
      WORDPRESS_DB_PASSWORD: resolved-secret-pw
      GITHUB_SYNC_REPO: s2925534/systemsnotsilos
      GITHUB_SYNC_BRANCH: main
    volumes:
      - type: volume
        source: systemsnotsilos-com-wp-content
        target: /var/www/html/wp-content
      - type: bind
        source: /volume1/docker/systemsnotsilos-com/mu-plugins
        target: /var/www/html/wp-content/mu-plugins
  systemsnotsilos-com-db:
    image: mariadb:11
    container_name: systemsnotsilos-com-db
volumes:
  systemsnotsilos-com-wp-content:
    name: systemsnotsilos-com-wp-content
"""

# Short-string volume syntax + list-form environment, for a bind-mounted target (this tool's
# own `wordpress` scaffold shape, expressed in the alternate syntax `docker compose config`
# can also emit depending on Compose version).
BIND_MOUNT_CONFIG_LIST_ENV = """
services:
  demo-example-com:
    image: wordpress:apache
    container_name: demo-example-com
    environment:
      - WORDPRESS_DB_HOST=shared-mariadb
      - WORDPRESS_DB_NAME=demo_example_com
      - WORDPRESS_DB_USER=demo_example_com_user
      - WORDPRESS_DB_PASSWORD=resolved-secret-pw
      - WORDPRESS_TABLE_PREFIX=wp_
    volumes:
      - ./wp-content:/var/www/html/wp-content
"""

NO_WORDPRESS_SERVICE_CONFIG = """
services:
  redis:
    image: redis:7-alpine
"""

MISSING_DB_ENV_CONFIG = """
services:
  demo-example-com:
    image: wordpress:apache
    container_name: demo-example-com
    environment:
      WORDPRESS_DB_HOST: shared-mariadb
    volumes:
      - ./wp-content:/var/www/html/wp-content
"""


class FakeSSH:
    def __init__(self, responses: dict[str, tuple[int, str]] | None = None) -> None:
        self.responses = dict(responses or {})
        self.commands: list[str] = []
        self.byte_uploads: dict[str, bytes] = {}
        self.stdin_payloads: dict[str, str] = {}

    def run(
        self,
        command: str,
        *,
        check: bool = False,
        timeout: int | None = None,
        stdin: str | None = None,
    ) -> RemoteCommandResult:
        del timeout
        self.commands.append(command)
        if stdin is not None:
            self.stdin_payloads[command] = stdin
        exit_code, stdout = self.responses.get(command, (0, ""))
        result = RemoteCommandResult(command, exit_code, stdout, "")
        if check and not result.ok:
            raise SynologySiteError(f"command failed: {command}")
        return result

    def upload_bytes(self, remote_path: str, content: bytes) -> None:
        self.byte_uploads[remote_path] = content


def compose_config_responses(config_yaml: str) -> dict[str, tuple[int, str]]:
    return {
        "command -v docker": (0, "docker\n"),
        "docker ps --format '{{.Names}}'": (0, ""),
        "docker compose version": (0, ""),
        f"cd {PROJECT_PATH} && docker compose -f docker-compose.yml config": (0, config_yaml),
    }


def test_inspect_existing_wordpress_deployment_detects_named_volume() -> None:
    fake = FakeSSH(compose_config_responses(VOLUME_BASED_CONFIG))

    deployment = inspect_existing_wordpress_deployment(fake, project_path=PROJECT_PATH)

    assert deployment.container_name == "systemsnotsilos-com"
    assert deployment.db_host == "systemsnotsilos-com-db"
    assert deployment.db_name == "systemsnotsilos_com"
    assert deployment.db_user == "systemsnotsilos_com_user"
    assert deployment.db_password == "resolved-secret-pw"
    assert deployment.table_prefix == "wp_"  # not set in this compose file -- defaults
    assert deployment.wp_content_is_volume is True
    assert deployment.wp_content_source == "systemsnotsilos-com-wp-content"
    assert deployment.github_sync_repo == "s2925534/systemsnotsilos"


def test_inspect_existing_wordpress_deployment_detects_bind_mount_with_list_env() -> None:
    fake = FakeSSH(compose_config_responses(BIND_MOUNT_CONFIG_LIST_ENV))

    deployment = inspect_existing_wordpress_deployment(fake, project_path=PROJECT_PATH)

    assert deployment.wp_content_is_volume is False
    assert deployment.wp_content_source == "./wp-content"
    assert deployment.db_host == "shared-mariadb"
    assert deployment.table_prefix == "wp_"
    assert deployment.github_sync_repo is None


def test_inspect_existing_wordpress_deployment_raises_without_wordpress_service() -> None:
    fake = FakeSSH(compose_config_responses(NO_WORDPRESS_SERVICE_CONFIG))

    with pytest.raises(SynologySiteError, match="Could not find a WordPress service"):
        inspect_existing_wordpress_deployment(fake, project_path=PROJECT_PATH)


def test_inspect_existing_wordpress_deployment_raises_on_missing_db_env() -> None:
    fake = FakeSSH(compose_config_responses(MISSING_DB_ENV_CONFIG))

    with pytest.raises(SynologySiteError, match="Could not determine WORDPRESS_DB"):
        inspect_existing_wordpress_deployment(fake, project_path=PROJECT_PATH)


def _tar_b64(files: dict[str, bytes]) -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for relpath, content in files.items():
            info = tarfile.TarInfo(name=relpath)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return base64.b64encode(buf.getvalue()).decode()


def test_dump_wp_content_volume_extracts_via_app_container(tmp_path: Path) -> None:
    dump_command = (
        "docker exec -u www-data systemsnotsilos-com "
        "tar czf - -C /var/www/html/wp-content . | base64"
    )
    responses = dict(DOCKER_RESOLUTION_RESPONSES)
    responses[dump_command] = (0, _tar_b64({"index.php": b"<?php // old\n"}))
    fake = FakeSSH(responses)

    extract_dir = dump_wp_content_volume(
        fake, container_name="systemsnotsilos-com", local_tmp_dir=tmp_path
    )

    assert (extract_dir / "index.php").read_bytes() == b"<?php // old\n"
    assert dump_command in fake.commands


def test_push_wp_content_to_volume_uploads_and_extracts(tmp_path: Path) -> None:
    local_dir = tmp_path / "new-content"
    local_dir.mkdir()
    (local_dir / "index.php").write_bytes(b"<?php // new\n")
    fake = FakeSSH(dict(DOCKER_RESOLUTION_RESPONSES))

    push_wp_content_to_volume(
        fake,
        local_dir,
        container_name="systemsnotsilos-com",
    )

    exec_command = next(
        c for c in fake.commands if c.startswith("docker exec -i -u www-data")
    )
    assert "systemsnotsilos-com" in exec_command
    assert "find /var/www/html/wp-content -mindepth 1 -delete" in exec_command
    assert "base64 -d | tar xzf - -C /var/www/html/wp-content" in exec_command
    # payload delivered via stdin, not an uploaded file -- no temp tarball on the host at all
    payload = fake.stdin_payloads[exec_command]
    with tarfile.open(fileobj=io.BytesIO(base64.b64decode(payload))) as tar:
        assert "index.php" in tar.getnames()


def test_push_wp_content_to_volume_raises_on_failure(tmp_path: Path) -> None:
    local_dir = tmp_path / "new-content"
    local_dir.mkdir()
    (local_dir / "index.php").write_bytes(b"<?php\n")

    class FailingSSH(FakeSSH):
        def run(self, command, *, check=False, timeout=None, stdin=None):
            if command.startswith("docker exec -i -u www-data"):
                return RemoteCommandResult(command, 1, "", "boom")
            return super().run(command, check=check, timeout=timeout, stdin=stdin)

    with pytest.raises(SynologySiteError, match="Failed to populate wp-content"):
        push_wp_content_to_volume(
            FailingSSH(dict(DOCKER_RESOLUTION_RESPONSES)),
            local_dir,
            container_name="systemsnotsilos-com",
        )
