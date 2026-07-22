from __future__ import annotations

import base64
import gzip
import io
import shlex
import tarfile
import zipfile
from pathlib import Path

import pytest

from synology_site.commands.migrate_from_lightsail import run_execute
from synology_site.config import Settings
from synology_site.errors import SynologySiteError
from synology_site.lightsail.source import LightsailSource
from synology_site.ssh_client import RemoteCommandResult


def settings(*, cloudflare_ready: bool = False) -> Settings:
    return Settings(
        nas_host="192.0.2.10",
        nas_port=22,
        nas_user="deploy",
        nas_docker_root="/volume1/docker",
        nas_ssh_key_path=None,
        nas_ssh_password="secret",
        local_base_url_host="192.0.2.10",
        default_start_port=5050,
        default_end_port=5999,
        default_framework="flask",
        restart_policy="unless-stopped",
        cf_api_token="token" if cloudflare_ready else None,
        cf_account_id="account" if cloudflare_ready else None,
        cf_zone_id="zone" if cloudflare_ready else None,
        cf_zone_domain="demo.example.com",
        cf_tunnel_id="tunnel-id" if cloudflare_ready else None,
        cf_tunnel_name="my-nas-tunnel",
        db_mode="none",
        db_type="mariadb",
        db_image="mariadb:11",
        db_password_length=32,
        db_publish_port=False,
        db_host_port=None,
        allow_overwrite=False,
        dry_run=False,
    )


def source() -> LightsailSource:
    return LightsailSource(
        name="veloso-dev",
        host="198.51.100.10",
        port=22,
        user="ubuntu",
        ssh_key_path="/keys/veloso-dev.pem",
        ssh_password=None,
    )


DOC_ROOT = "/var/www/html/veloso.dev/public"
DB_NAME = "veloso_wp"
DB_USER = "veloso_user"
DB_PASSWORD = "sourcepw123"
DB_HOST = "localhost"
TABLE_PREFIX = "wp_"

WP_CONFIG = f"""<?php
define('DB_NAME', '{DB_NAME}');
define('DB_USER', '{DB_USER}');
define('DB_PASSWORD', '{DB_PASSWORD}');
define('DB_HOST', '{DB_HOST}');
$table_prefix = '{TABLE_PREFIX}';
"""

SOURCE_DUMP_SQL = b"-- source dump --\nINSERT INTO wp_options VALUES (1);\n"


def _gzip_b64(payload: bytes) -> str:
    return base64.b64encode(gzip.compress(payload)).decode()


def _tar_b64(files: dict[str, bytes]) -> str:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for relpath, content in files.items():
            info = tarfile.TarInfo(name=f"wp-content/{relpath}")
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return base64.b64encode(buf.getvalue()).decode()


def _volume_tar_b64(files: dict[str, bytes]) -> str:
    """Like _tar_b64, but without the wp-content/ prefix -- dump_wp_content_volume tars from
    /data (the volume root, which *is* wp-content's contents), unlike fetch_wp_content's
    `tar -C {doc_root} wp-content` which includes wp-content/ as its own top-level entry."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for relpath, content in files.items():
            info = tarfile.TarInfo(name=relpath)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return base64.b64encode(buf.getvalue()).decode()


def discovery_responses(
    doc_root: str = DOC_ROOT, *, s3_offload: bool = False
) -> dict[str, tuple[int, str]]:
    plugins = "amazon-s3-and-cloudfront\nakismet\n" if s3_offload else "akismet\n"
    server_name_grep = "grep -h server_name /etc/nginx/sites-enabled/* 2>/dev/null"
    uploads_du = f"du -sh {doc_root}/wp-content/uploads 2>/dev/null"
    return {
        "test -d /opt/bitnami/wordpress": (1, ""),
        "grep -Rl veloso.dev /etc/nginx/sites-enabled /etc/nginx/sites-available 2>/dev/null": (
            0,
            "/etc/nginx/sites-enabled/veloso.dev\n",
        ),
        "cat /etc/nginx/sites-enabled/veloso.dev": (
            0,
            f"server {{ server_name veloso.dev; root {doc_root}; }}",
        ),
        server_name_grep: (0, "server_name veloso.dev;\n"),
        "php -v": (0, "PHP 8.3.14 (cli)\n"),
        "command -v wp": (1, ""),
        f"cat {doc_root}/wp-includes/version.php 2>/dev/null": (0, "$wp_version = '6.5.2';\n"),
        f"cat {doc_root}/wp-config.php 2>/dev/null": (0, WP_CONFIG),
        f"ls -1 {doc_root}/wp-content/plugins 2>/dev/null": (0, plugins),
        f"ls -1 {doc_root}/wp-content/themes 2>/dev/null": (0, "twentytwentyfour\n"),
        uploads_du: (0, f"10M\t{doc_root}/wp-content/uploads\n"),
        "crontab -l 2>/dev/null": (0, ""),
    }


SOURCE_CREDENTIALS_COMMAND = f"cat {shlex.quote(DOC_ROOT)}/wp-config.php"
SOURCE_DUMP_COMMAND = (
    f"MYSQL_PWD={shlex.quote(DB_PASSWORD)} mariadb-dump --no-tablespaces "
    f"-h {shlex.quote(DB_HOST)} -u{shlex.quote(DB_USER)} {shlex.quote(DB_NAME)} "
    "| gzip -c | base64"
)
SOURCE_FETCH_COMMAND = f"tar czf - -C {shlex.quote(DOC_ROOT)} wp-content | base64"

BUNDLE_TOP_DIR = Path(DOC_ROOT).name
BUNDLE_ARCHIVE_PATH = f"/tmp/{BUNDLE_TOP_DIR}-site-bundle.zip"
SOURCE_ZIP_COMMAND = (
    f"cd {shlex.quote(str(Path(DOC_ROOT).parent))} && "
    f"zip -qr {shlex.quote(BUNDLE_ARCHIVE_PATH)} {shlex.quote(BUNDLE_TOP_DIR)} "
    f"&& base64 {shlex.quote(BUNDLE_ARCHIVE_PATH)}"
)


def _site_archive_b64(files: dict[str, bytes]) -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for relpath, content in files.items():
            zf.writestr(f"{BUNDLE_TOP_DIR}/{relpath}", content)
    return base64.b64encode(buf.getvalue()).decode()

DOCKER_BOOTSTRAP_RESPONSES: dict[str, tuple[int, str]] = {
    "command -v docker": (0, "docker\n"),
    "docker ps --format '{{.Names}}'": (0, ""),
    "docker compose version": (0, ""),
    "test -d /volume1/docker": (0, ""),
    "docker ps --format '{{.Ports}}'": (0, ""),
}


class FakeSSH:
    def __init__(self, responses: dict[str, tuple[int, str]] | None = None) -> None:
        self.responses = dict(responses or {})
        self.commands: list[str] = []
        self.uploads: dict[str, str] = {}
        self.byte_uploads: dict[str, bytes] = {}
        self.uploaded_directories: list[tuple[str, str]] = []

    def __enter__(self) -> FakeSSH:
        return self

    def __exit__(self, *_exc: object) -> None:
        pass

    def run(
        self,
        command: str,
        *,
        check: bool = False,
        timeout: int | None = None,
        stdin: str | None = None,
    ) -> RemoteCommandResult:
        del timeout, stdin
        self.commands.append(command)
        if command in self.responses:
            exit_code, stdout = self.responses[command]
        elif command.startswith("cat ") and self._cat_path(command) in self.uploads:
            exit_code, stdout = 0, self.uploads[self._cat_path(command)]
        else:
            exit_code, stdout = 0, ""
        result = RemoteCommandResult(command, exit_code, stdout, "")
        if check and not result.ok:
            raise SynologySiteError(f"command failed: {command}")
        return result

    @staticmethod
    def _cat_path(command: str) -> str:
        parts = shlex.split(command[len("cat ") :])
        return parts[0] if parts else ""

    def upload_text(self, remote_path: str, content: str) -> None:
        self.uploads[remote_path] = content

    def upload_bytes(self, remote_path: str, content: bytes) -> None:
        self.byte_uploads[remote_path] = content

    def upload_directory(
        self, local_root: Path, remote_root: str, *, ignore: object = None
    ) -> list[str]:
        del ignore
        self.uploaded_directories.append((str(local_root), remote_root))
        return [
            str(path.relative_to(local_root))
            for path in sorted(Path(local_root).rglob("*"))
            if path.is_file()
        ]


class FakeCloudflareResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, object]:
        return self.payload


class FakeCloudflareSession:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method: str, url: str, **kwargs: object) -> FakeCloudflareResponse:
        self.requests.append((method, url, kwargs))
        if method == "GET" and url.endswith("/configurations"):
            return FakeCloudflareResponse({"success": True, "result": {"config": {"ingress": []}}})
        if method == "PUT" and url.endswith("/configurations"):
            return FakeCloudflareResponse({"success": True, "result": {}})
        if method == "GET" and url.endswith("/dns_records"):
            return FakeCloudflareResponse({"success": True, "result": []})
        if method == "POST" and url.endswith("/dns_records"):
            return FakeCloudflareResponse({"success": True, "result": {"id": "record-id"}})
        return FakeCloudflareResponse({"success": True, "result": {}})


def source_ssh(*, s3_offload: bool = False, full_archive: bool = False) -> FakeSSH:
    responses = discovery_responses(s3_offload=s3_offload)
    responses[SOURCE_CREDENTIALS_COMMAND] = (0, WP_CONFIG)
    if not s3_offload:
        responses[SOURCE_DUMP_COMMAND] = (0, _gzip_b64(SOURCE_DUMP_SQL))
        if full_archive:
            responses["command -v zip"] = (0, "zip\n")
            responses[SOURCE_ZIP_COMMAND] = (
                0,
                _site_archive_b64(
                    {
                        "wp-content/index.php": b"<?php // wp-content\n",
                        "_migration_bundle/database.sql": SOURCE_DUMP_SQL,
                        "_migration_bundle/nginx.conf": b"server { server_name veloso.dev; }",
                    }
                ),
            )
        else:
            responses[SOURCE_FETCH_COMMAND] = (
                0,
                _tar_b64({"index.php": b"<?php // wp-content\n"}),
            )
    return FakeSSH(responses)


class FakeHealthResponse:
    status_code = 200


def test_run_execute_aborts_on_s3_offload_before_any_dump(tmp_path: Path) -> None:
    fake_source = source_ssh(s3_offload=True)

    def boom_target(_settings: object, _password: object) -> object:
        raise AssertionError("target SSH should never be reached when S3 offload is detected")

    with pytest.raises(SynologySiteError, match="S3-offloaded media"):
        run_execute(
            source=source(),
            source_domain="veloso.dev",
            target_domain="demo.example.com",
            target_mode="new-site",
            settings=settings(),
            confirmed=True,
            source_ssh_factory=lambda _source, _password: fake_source,
            target_ssh_factory=boom_target,
            backup_dir=tmp_path / "migration-backups",
        )
    assert not any("mariadb-dump" in c for c in fake_source.commands)


def test_run_execute_existing_site_replace_requires_confirmation(tmp_path: Path) -> None:
    def boom_target(_settings: object, _password: object) -> object:
        raise AssertionError("target SSH should never be reached without confirmation")

    with pytest.raises(SynologySiteError, match="Pass --yes"):
        run_execute(
            source=source(),
            source_domain="veloso.dev",
            target_domain="demo.example.com",
            target_mode="existing-site-replace",
            settings=settings(),
            confirmed=False,
            source_ssh_factory=lambda _source, _password: source_ssh(),
            target_ssh_factory=boom_target,
            backup_dir=tmp_path / "migration-backups",
        )


def test_run_execute_new_site_provisions_and_migrates(tmp_path: Path) -> None:
    target_fake = FakeSSH(dict(DOCKER_BOOTSTRAP_RESPONSES))
    target_fake.responses["test -e /volume1/docker/demo-example-com"] = (1, "")
    target_fake.responses["docker inspect -f '{{.State.Running}}' demo-example-com"] = (0, "true\n")
    target_fake.responses["docker inspect -f '{{.State.Running}}' shared-mariadb"] = (0, "true\n")
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "mariadb.env").write_text("MARIADB_ROOT_PASSWORD=rootpw\n", encoding="utf-8")

    result = run_execute(
        source=source(),
        source_domain="veloso.dev",
        target_domain="demo.example.com",
        target_mode="new-site",
        settings=settings(cloudflare_ready=True),
        confirmed=True,
        source_ssh_factory=lambda _source, _password: source_ssh(),
        target_ssh_factory=lambda _settings, _password: target_fake,
        health_get=lambda _url, timeout: FakeHealthResponse(),
        cloudflare_session=FakeCloudflareSession(),
        backup_dir=tmp_path / "migration-backups",
        secrets_dir=secrets_dir,
        wp_cli_download=lambda: b"phar-bytes",
    )

    assert result.target_mode == "new-site"
    env = target_fake.uploads["/volume1/docker/demo-example-com/app/.env"]
    assert "WORDPRESS_DB_HOST=shared-mariadb" in env
    assert any(
        "MYSQL_PWD=" in c and " -p" not in c.split("MYSQL_PWD=")[0]
        for c in target_fake.commands
        if "mariadb -u" in c
    )
    assert target_fake.uploaded_directories
    assert result.cloudflare_configured is True


def test_run_execute_existing_site_replace_backs_up_and_search_replaces(tmp_path: Path) -> None:
    project_path = "/volume1/docker/demo-example-com"
    target_fake = FakeSSH(dict(DOCKER_BOOTSTRAP_RESPONSES))
    target_fake.uploads[f"{project_path}/app/.env"] = (
        "WORDPRESS_DB_HOST=demo-example-com-db\n"
        "WORDPRESS_DB_NAME=demo_example_com\n"
        "WORDPRESS_DB_USER=demo_example_com_user\n"
        "WORDPRESS_DB_PASSWORD=targetpw\n"
        "WORDPRESS_TABLE_PREFIX=wp_\n"
    )
    target_fake.uploads[f"{project_path}/.synology-site.json"] = (
        '{"tool": "synology-site-deployer", "port": 5051, "domain": "demo.example.com"}'
    )

    backup_dump_command = (
        "docker exec -i demo-example-com-db sh -c "
        "'MYSQL_PWD=targetpw mariadb-dump --no-tablespaces "
        "-udemo_example_com_user demo_example_com' | gzip -c | base64"
    )
    list_inner = (
        "MYSQL_PWD=targetpw mariadb -N -udemo_example_com_user "
        f"-e {shlex.quote('SHOW TABLES')} demo_example_com"
    )
    show_tables_command = f"docker exec -i demo-example-com-db sh -c {shlex.quote(list_inner)}"
    target_fake.responses[backup_dump_command] = (0, _gzip_b64(b"-- old target dump --\n"))
    target_fake.responses[show_tables_command] = (0, "wp_options\nwp_posts\n")
    target_fake.responses[f"tar czf - -C {project_path} wp-content | base64"] = (
        0,
        _tar_b64({"index.php": b"<?php // old target content\n"}),
    )

    backup_dir = tmp_path / "migration-backups"
    result = run_execute(
        source=source(),
        source_domain="veloso.dev",
        target_domain="demo.example.com",
        target_mode="existing-site-replace",
        settings=settings(),
        confirmed=True,
        source_ssh_factory=lambda _source, _password: source_ssh(),
        target_ssh_factory=lambda _settings, _password: target_fake,
        backup_dir=backup_dir,
        wp_cli_download=lambda: b"phar-bytes",
    )

    assert (backup_dir / "demo-example-com" / "pre-overwrite-dump.sql.gz").exists()
    assert (backup_dir / "demo-example-com" / "wp-content" / "index.php").exists()
    assert any(
        "DROP TABLE IF EXISTS" in c for c in target_fake.commands
    )
    assert any("search-replace veloso.dev demo.example.com" in c for c in target_fake.commands)
    assert result.cloudflare_configured is False


def test_run_execute_full_archive_transfer_mode_builds_and_cleans_up_source(
    tmp_path: Path,
) -> None:
    target_fake = FakeSSH(dict(DOCKER_BOOTSTRAP_RESPONSES))
    target_fake.responses["test -e /volume1/docker/demo-example-com"] = (1, "")
    target_fake.responses["docker inspect -f '{{.State.Running}}' demo-example-com"] = (0, "true\n")
    target_fake.responses["docker inspect -f '{{.State.Running}}' shared-mariadb"] = (0, "true\n")
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "mariadb.env").write_text("MARIADB_ROOT_PASSWORD=rootpw\n", encoding="utf-8")

    fake_source = source_ssh(full_archive=True)
    backup_dir = tmp_path / "migration-backups"

    result = run_execute(
        source=source(),
        source_domain="veloso.dev",
        target_domain="demo.example.com",
        target_mode="new-site",
        settings=settings(),
        confirmed=True,
        transfer_mode="full-archive",
        source_ssh_factory=lambda _source, _password: fake_source,
        target_ssh_factory=lambda _settings, _password: target_fake,
        health_get=lambda _url, timeout: FakeHealthResponse(),
        backup_dir=backup_dir,
        secrets_dir=secrets_dir,
        wp_cli_download=lambda: b"phar-bytes",
    )

    assert result.target_mode == "new-site"
    assert target_fake.uploaded_directories
    # source ends the call in exactly the state it started: the staging bundle and the zip
    # are always removed again, regardless of success.
    bundle_dir = f"{DOC_ROOT}/_migration_bundle"
    assert f"rm -rf {bundle_dir}" in fake_source.commands
    assert f"rm -f {BUNDLE_ARCHIVE_PATH}" in fake_source.commands
    # the nginx.conf/database.sql reference copies land under the backup dir for the user,
    # not applied to the running stack.
    bundle_backup = backup_dir / "demo-example-com" / "source-bundle"
    assert (bundle_backup / "nginx.conf").exists()
    assert (bundle_backup / "database.sql").exists()


BESPOKE_COMPOSE_CONFIG = """
services:
  systemsnotsilos-com:
    image: wordpress:latest
    container_name: systemsnotsilos-com
    environment:
      WORDPRESS_DB_HOST: systemsnotsilos-com-db
      WORDPRESS_DB_NAME: systemsnotsilos_com
      WORDPRESS_DB_USER: systemsnotsilos_com_user
      WORDPRESS_DB_PASSWORD: targetpw
      GITHUB_SYNC_REPO: s2925534/systemsnotsilos
    volumes:
      - type: volume
        source: systemsnotsilos-com-wp-content
        target: /var/www/html/wp-content
      - type: bind
        source: /volume1/docker/systemsnotsilos-com/mu-plugins
        target: /var/www/html/wp-content/mu-plugins
volumes:
  systemsnotsilos-com-wp-content:
    name: systemsnotsilos-com-wp-content
"""


def test_run_execute_existing_site_replace_handles_bespoke_non_scaffold_target(
    tmp_path: Path,
) -> None:
    """Real-world shape: a target deployed by hand or via `deploy`, not this tool's own
    `wordpress` scaffold -- no app/.env, wp-content is a named Docker volume, DB host/name/user
    are hardcoded in the compose file (only the password came from .env), and it has a
    GitHub-sync-style mu-plugin. Must be handled without ever touching that plugin's separate
    bind mount, and must warn (not fail) about the sync repo.
    """
    project_path = "/volume1/docker/systemsnotsilos-com"
    target_fake = FakeSSH(dict(DOCKER_BOOTSTRAP_RESPONSES))
    target_fake.uploads[f"{project_path}/.synology-site.json"] = (
        '{"tool": "synology-site-deployer", "domain": "systemsnotsilos.com", '
        '"framework": "existing", "port": null, "compose_file": "docker-compose.yml"}'
    )
    target_fake.responses[f"test -f {project_path}/app/.env"] = (1, "")
    target_fake.responses[
        f"cd {project_path} && docker compose -f docker-compose.yml config"
    ] = (0, BESPOKE_COMPOSE_CONFIG)

    backup_dump_command = (
        "docker exec -i systemsnotsilos-com-db sh -c "
        "'MYSQL_PWD=targetpw mariadb-dump --no-tablespaces "
        "-usystemsnotsilos_com_user systemsnotsilos_com' | gzip -c | base64"
    )
    bespoke_list_inner = (
        "MYSQL_PWD=targetpw mariadb -N -usystemsnotsilos_com_user "
        f"-e {shlex.quote('SHOW TABLES')} systemsnotsilos_com"
    )
    show_tables_command = (
        f"docker exec -i systemsnotsilos-com-db sh -c {shlex.quote(bespoke_list_inner)}"
    )
    volume_dump_command = (
        "docker exec -u www-data systemsnotsilos-com "
        "tar czf - -C /var/www/html/wp-content . | base64"
    )
    target_fake.responses[backup_dump_command] = (0, _gzip_b64(b"-- old target dump --\n"))
    target_fake.responses[show_tables_command] = (0, "wp_options\nwp_posts\n")
    target_fake.responses[volume_dump_command] = (
        0,
        _volume_tar_b64({"index.php": b"<?php // old target content\n"}),
    )

    backup_dir = tmp_path / "migration-backups"
    result = run_execute(
        source=source(),
        source_domain="veloso.dev",
        target_domain="systemsnotsilos.com",
        target_mode="existing-site-replace",
        settings=settings(),
        confirmed=True,
        source_ssh_factory=lambda _source, _password: source_ssh(),
        target_ssh_factory=lambda _settings, _password: target_fake,
        backup_dir=backup_dir,
        wp_cli_download=lambda: b"phar-bytes",
    )

    assert result.local_url == "https://systemsnotsilos.com"  # null port -> no host:port shown
    assert (backup_dir / "systemsnotsilos-com" / "pre-overwrite-dump.sql.gz").exists()
    assert (backup_dir / "systemsnotsilos-com" / "wp-content" / "index.php").exists()

    volume_push_command = next(
        c for c in target_fake.commands if c.startswith("docker exec -i -u www-data")
    )
    assert "systemsnotsilos-com" in volume_push_command
    assert "find /var/www/html/wp-content -mindepth 1 -delete" in volume_push_command
    # the mu-plugins bind mount is a completely separate mount -- never referenced anywhere
    assert not any("mu-plugins" in c for c in target_fake.commands)

    assert any(
        c == "docker cp /tmp/wp-cli-systemsnotsilos-com.phar systemsnotsilos-com:/tmp/wp-cli.phar"
        for c in target_fake.commands
    )
    assert any(
        "search-replace veloso.dev systemsnotsilos.com" in c for c in target_fake.commands
    )
    assert any(
        c == "docker exec systemsnotsilos-com rm -f /tmp/wp-cli.phar"
        for c in target_fake.commands
    )
    assert result.cloudflare_configured is False


def test_run_execute_rejects_unknown_transfer_mode() -> None:
    def boom(_source: object, _password: object) -> object:
        raise AssertionError("SSH should not be attempted for a rejected --transfer-mode value")

    with pytest.raises(SynologySiteError, match="--transfer-mode"):
        run_execute(
            source=source(),
            source_domain="veloso.dev",
            target_domain="demo.example.com",
            target_mode="new-site",
            settings=settings(),
            confirmed=True,
            transfer_mode="bogus-mode",
            source_ssh_factory=boom,
        )
