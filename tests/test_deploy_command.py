from __future__ import annotations

import json
from pathlib import Path

import pytest

from synology_site.commands.deploy import deploy_existing_project
from synology_site.config import Settings
from synology_site.errors import SynologySiteError
from synology_site.nas.target import NasTarget
from synology_site.ssh_client import RemoteCommandResult


def settings() -> Settings:
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
        cf_api_token=None,
        cf_account_id=None,
        cf_zone_id=None,
        cf_zone_domain="example.com",
        cf_tunnel_id=None,
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


class FakeResponse:
    status_code = 200


class FakeSSH:
    def __init__(self, *, project_exists: bool = False, pull_ok: bool = True) -> None:
        self.project_exists = project_exists
        self.pull_ok = pull_ok
        self.commands: list[str] = []
        self.uploads: dict[str, str] = {}

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
    ) -> RemoteCommandResult:
        del timeout
        self.commands.append(command)
        exit_code = 0
        stdout = ""
        if command == "command -v docker":
            stdout = "docker\n"
        elif command == "test -e /volume1/docker/app-example-com":
            exit_code = 0 if self.project_exists else 1
        elif command.endswith("pull"):
            exit_code = 0 if self.pull_ok else 1
        elif command == "docker inspect -f '{{.State.Running}}' resilinked-web":
            stdout = "true\n"
        elif command == "docker ps --format '{{.Ports}}'":
            stdout = ""
        result = RemoteCommandResult(command, exit_code, stdout, "")
        if check and not result.ok:
            raise SynologySiteError("command failed")
        return result

    def upload_text(self, remote_path: str, content: str) -> None:
        self.uploads[remote_path] = content

    def upload_directory(self, local_root: Path, remote_root: str, *, ignore=None) -> list[str]:
        uploaded = []
        for path in sorted(local_root.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(local_root)
            if ignore and ignore(rel):
                continue
            remote_path = f"{remote_root}/{rel.as_posix()}"
            self.uploads[remote_path] = path.read_text(encoding="utf-8")
            uploaded.append(rel.as_posix())
        return uploaded


def _compose_file(tmp_path: Path) -> Path:
    compose = tmp_path / "docker-compose.web.yml"
    compose.write_text("services:\n  web:\n    image: ghcr.io/example/web:latest\n")
    return compose


def test_deploy_existing_project_without_port_skips_health_and_cloudflare(
    tmp_path: Path,
) -> None:
    fake = FakeSSH()

    result = deploy_existing_project(
        "app.example.com",
        compose_file=_compose_file(tmp_path),
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
    )

    assert result.port is None
    assert result.local_url is None
    assert "/volume1/docker/app-example-com/docker-compose.yml" in fake.uploads
    assert "/volume1/docker/app-example-com/.synology-site.json" in fake.uploads
    marker = json.loads(fake.uploads["/volume1/docker/app-example-com/.synology-site.json"])
    assert marker["mode"] == "deploy"
    assert marker["port"] is None
    assert (
        "cd /volume1/docker/app-example-com && docker compose -f docker-compose.yml pull"
        in fake.commands
    )
    assert (
        "cd /volume1/docker/app-example-com && docker compose -f docker-compose.yml up -d"
        in fake.commands
    )


def test_deploy_existing_project_with_port_runs_health_check(tmp_path: Path) -> None:
    fake = FakeSSH()
    health_urls: list[str] = []

    def health_get(url: str, timeout: int) -> FakeResponse:
        del timeout
        health_urls.append(url)
        return FakeResponse()

    result = deploy_existing_project(
        "app.example.com",
        compose_file=_compose_file(tmp_path),
        settings=settings(),
        port=5050,
        container_name="resilinked-web",
        health_path="/health",
        ssh_factory=lambda _settings, _password: fake,
        health_get=health_get,
    )

    assert result.port == 5050
    assert result.local_url == "http://192.0.2.10:5050"
    assert result.health_url == "http://192.0.2.10:5050/health"
    assert health_urls == ["http://192.0.2.10:5050/health"]


def test_deploy_falls_back_to_build_when_pull_fails(tmp_path: Path) -> None:
    fake = FakeSSH(pull_ok=False)

    deploy_existing_project(
        "app.example.com",
        compose_file=_compose_file(tmp_path),
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
    )

    assert (
        "cd /volume1/docker/app-example-com && docker compose -f docker-compose.yml "
        "up -d --build" in fake.commands
    )


def test_deploy_uploads_env_file_with_chmod(tmp_path: Path) -> None:
    fake = FakeSSH()
    env_file = tmp_path / ".env"
    env_file.write_text("NEXT_PUBLIC_API_URL=https://api.example.com\n")

    deploy_existing_project(
        "app.example.com",
        compose_file=_compose_file(tmp_path),
        settings=settings(),
        env_file=env_file,
        ssh_factory=lambda _settings, _password: fake,
    )

    assert "/volume1/docker/app-example-com/.env" in fake.uploads
    assert "chmod 600 /volume1/docker/app-example-com/.env" in fake.commands


def test_deploy_refuses_existing_project_without_force(tmp_path: Path) -> None:
    fake = FakeSSH(project_exists=True)

    with pytest.raises(SynologySiteError, match="already exists"):
        deploy_existing_project(
            "app.example.com",
            compose_file=_compose_file(tmp_path),
            settings=settings(),
            ssh_factory=lambda _settings, _password: fake,
        )


def test_deploy_dry_run_skips_remote_writes(tmp_path: Path) -> None:
    fake = FakeSSH()

    result = deploy_existing_project(
        "app.example.com",
        compose_file=_compose_file(tmp_path),
        settings=settings(),
        dry_run=True,
        ssh_factory=lambda _settings, _password: fake,
    )

    assert result.uploaded_files
    assert fake.uploads == {}
    assert not any("up -d" in command for command in fake.commands)


def test_deploy_health_path_requires_port(tmp_path: Path) -> None:
    fake = FakeSSH()

    with pytest.raises(SynologySiteError, match="--port"):
        deploy_existing_project(
            "app.example.com",
            compose_file=_compose_file(tmp_path),
            settings=settings(),
            health_path="/health",
            ssh_factory=lambda _settings, _password: fake,
        )


def test_deploy_missing_compose_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SynologySiteError, match="Compose file not found"):
        deploy_existing_project(
            "app.example.com",
            compose_file=tmp_path / "missing.yml",
            settings=settings(),
            ssh_factory=lambda _settings, _password: (_ for _ in ()).throw(
                AssertionError("ssh should not be used")
            ),
        )


def _monorepo(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "infra" / "web").mkdir(parents=True)
    compose = tmp_path / "infra" / "web" / "docker-compose.web.yml"
    compose.write_text("services:\n  web:\n    build:\n      context: ../..\n")
    (tmp_path / "apps" / "web" / "node_modules").mkdir(parents=True)
    (tmp_path / "apps" / "web" / "node_modules" / "dep.js").write_text("skip me\n")
    (tmp_path / "apps" / "web" / "index.ts").write_text("entry\n")
    (tmp_path / ".dockerignore").write_text("node_modules\n**/node_modules\n")
    return tmp_path, compose


def test_deploy_with_source_dir_uploads_tree_and_builds(tmp_path: Path) -> None:
    fake = FakeSSH()
    source_dir, compose = _monorepo(tmp_path)

    result = deploy_existing_project(
        "app.example.com",
        compose_file=compose,
        source_dir=source_dir,
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
    )

    assert result.compose_file == "repo/infra/web/docker-compose.web.yml"
    assert "/volume1/docker/app-example-com/repo/apps/web/index.ts" in fake.uploads
    assert not any("node_modules" in p for p in fake.uploads)
    assert (
        "cd /volume1/docker/app-example-com && docker compose "
        "-f repo/infra/web/docker-compose.web.yml up -d --build" in fake.commands
    )
    assert not any(c.endswith("pull") for c in fake.commands)


def test_deploy_with_source_dir_uploads_env_file_alongside_compose(tmp_path: Path) -> None:
    fake = FakeSSH()
    source_dir, compose = _monorepo(tmp_path)
    env_file = tmp_path / "web.env"
    env_file.write_text("NEXT_PUBLIC_API_URL=https://api.example.com\n")

    deploy_existing_project(
        "app.example.com",
        compose_file=compose,
        source_dir=source_dir,
        env_file=env_file,
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
    )

    remote_env = "/volume1/docker/app-example-com/repo/infra/web/.env"
    assert fake.uploads[remote_env] == "NEXT_PUBLIC_API_URL=https://api.example.com\n"
    assert f"chmod 600 {remote_env}" in fake.commands


def test_deploy_with_source_dir_excludes_env_from_bulk_upload(tmp_path: Path) -> None:
    fake = FakeSSH()
    source_dir, compose = _monorepo(tmp_path)
    (source_dir / "infra" / "web" / ".env").write_text("SHOULD_NOT_UPLOAD=1\n")

    deploy_existing_project(
        "app.example.com",
        compose_file=compose,
        source_dir=source_dir,
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
    )

    assert "/volume1/docker/app-example-com/repo/infra/web/.env" not in fake.uploads


def test_deploy_source_dir_requires_compose_file_inside_it(tmp_path: Path) -> None:
    fake = FakeSSH()
    source_dir, _compose = _monorepo(tmp_path)
    outside_compose = tmp_path.parent / "outside.yml"
    outside_compose.write_text("services: {}\n")

    with pytest.raises(SynologySiteError, match="inside --source-dir"):
        deploy_existing_project(
            "app.example.com",
            compose_file=outside_compose,
            source_dir=source_dir,
            settings=settings(),
            ssh_factory=lambda _settings, _password: fake,
        )
    outside_compose.unlink()


def test_deploy_source_dir_missing_directory_raises(tmp_path: Path) -> None:
    fake = FakeSSH()
    _source_dir, compose = _monorepo(tmp_path)

    with pytest.raises(SynologySiteError, match="Source directory not found"):
        deploy_existing_project(
            "app.example.com",
            compose_file=compose,
            source_dir=tmp_path / "missing-dir",
            settings=settings(),
            ssh_factory=lambda _settings, _password: fake,
        )


def test_deploy_uses_resolved_nas_target_for_ssh_connection(tmp_path: Path) -> None:
    from dataclasses import replace

    fake = FakeSSH()
    captured_settings: list[Settings] = []

    def capturing_ssh_factory(passed_settings: Settings, _password: object) -> FakeSSH:
        captured_settings.append(passed_settings)
        return fake

    clienta_target = NasTarget(
        name="clienta",
        host="203.0.113.5",
        port=2222,
        user="clienta-deploy",
        ssh_key_path=None,
        ssh_password="clienta-secret",
        docker_root="/volume1/docker",
        local_base_url_host="192.0.2.10",
        default_start_port=5050,
        default_end_port=5999,
    )
    multi_nas_settings = replace(settings(), nas_targets=(clienta_target,))

    deploy_existing_project(
        "app.example.com",
        compose_file=_compose_file(tmp_path),
        settings=multi_nas_settings,
        workspace="clienta",
        ssh_factory=capturing_ssh_factory,
    )

    assert captured_settings[0].nas_host == "203.0.113.5"
    assert captured_settings[0].nas_port == 2222
    assert captured_settings[0].nas_user == "clienta-deploy"
