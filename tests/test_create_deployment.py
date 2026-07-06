from __future__ import annotations

import pytest

from synology_site.commands.create import create_site
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
    def __init__(self, *, project_exists: bool = False) -> None:
        self.project_exists = project_exists
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
        elif command == "test -e /volume1/docker/demo-example-com":
            exit_code = 0 if self.project_exists else 1
        elif command in {
            "docker inspect -f '{{.State.Running}}' demo-example-com",
            "docker inspect -f '{{.State.Running}}' demo-example-com-db",
            "docker inspect -f '{{.State.Running}}' demo-example-com-web",
            "docker inspect -f '{{.State.Running}}' demo-example-com-redis",
            "docker inspect -f '{{.State.Running}}' demo-example-com-queue",
            "docker inspect -f '{{.State.Running}}' demo-example-com-scheduler",
        }:
            stdout = "true\n"
        elif command == "docker ps --format '{{.Ports}}'":
            stdout = "0.0.0.0:5050->5000/tcp\n"
        result = RemoteCommandResult(command, exit_code, stdout, "")
        if check and not result.ok:
            raise SynologySiteError("command failed")
        return result

    def upload_text(self, remote_path: str, content: str) -> None:
        self.uploads[remote_path] = content


def test_create_site_deploys_flask_without_db() -> None:
    fake = FakeSSH()

    result = create_site(
        "demo.example.com",
        settings=settings(),
        ssh_factory=lambda _settings, _password: fake,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert result.port == 5051
    assert result.local_url == "http://192.0.2.10:5051"
    assert "/volume1/docker/demo-example-com/app/app.py" in fake.uploads
    assert "/volume1/docker/demo-example-com/docker-compose.yml" in fake.uploads
    assert "/volume1/docker/demo-example-com/docs/README.md" in fake.uploads
    assert "cd /volume1/docker/demo-example-com && docker compose up -d --build" in fake.commands


def test_create_site_dry_run_skips_remote_writes_and_start() -> None:
    fake = FakeSSH()

    result = create_site(
        "demo.example.com",
        settings=settings(),
        dry_run=True,
        ssh_factory=lambda _settings, _password: fake,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert result.uploaded_files
    assert fake.uploads == {}
    assert not any("up -d --build" in command for command in fake.commands)


def test_create_site_rejects_frontend_for_non_laravel_framework_before_touching_ssh() -> None:
    def boom(_settings: object, _password: object) -> object:
        raise AssertionError("SSH should not be attempted for a rejected --frontend value")

    with pytest.raises(SynologySiteError, match="only applicable to --framework laravel"):
        create_site(
            "demo.example.com",
            settings=settings(),
            framework="flask",
            frontend="vue",
            ssh_factory=boom,
        )


def test_create_site_rejects_decoupled_spa_frontend_without_fpm_nginx() -> None:
    def boom(_settings: object, _password: object) -> object:
        raise AssertionError("SSH should not be attempted for a rejected frontend/php-server combo")

    with pytest.raises(SynologySiteError, match="requires --php-server fpm-nginx"):
        create_site(
            "demo.example.com",
            settings=settings(),
            framework="laravel",
            frontend="vue",
            php_server="artisan",
            ssh_factory=boom,
        )


def test_create_site_rejects_unknown_frontend() -> None:
    with pytest.raises(SynologySiteError, match="Unsupported frontend"):
        create_site(
            "demo.example.com",
            settings=settings(),
            frontend="svelte-but-not-inertia",
            ssh_factory=lambda _settings, _password: FakeSSH(),
        )


def test_create_site_deploys_laravel_without_db() -> None:
    fake = FakeSSH()

    result = create_site(
        "demo.example.com",
        settings=settings(),
        framework="laravel",
        ssh_factory=lambda _settings, _password: fake,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert result.port == 5051
    assert "/volume1/docker/demo-example-com/app/Dockerfile" in fake.uploads
    assert "/volume1/docker/demo-example-com/docker-compose.yml" in fake.uploads
    assert "composer create-project" in fake.uploads[
        "/volume1/docker/demo-example-com/app/Dockerfile"
    ]


def test_create_site_deploys_fastapi_without_db() -> None:
    fake = FakeSSH()

    result = create_site(
        "demo.example.com",
        settings=settings(),
        framework="fastapi",
        ssh_factory=lambda _settings, _password: fake,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert result.port == 5051
    assert "/volume1/docker/demo-example-com/app/main.py" in fake.uploads
    assert "/volume1/docker/demo-example-com/app/requirements.txt" in fake.uploads
    dockerfile = fake.uploads["/volume1/docker/demo-example-com/app/Dockerfile"]
    assert "gunicorn" in dockerfile
    assert "uvicorn.workers.UvicornWorker" in dockerfile


def test_create_site_deploys_nextjs_without_db() -> None:
    fake = FakeSSH()

    result = create_site(
        "demo.example.com",
        settings=settings(),
        framework="nextjs",
        ssh_factory=lambda _settings, _password: fake,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert result.port == 5051
    assert "/volume1/docker/demo-example-com/app/health-route.js" in fake.uploads
    dockerfile = fake.uploads["/volume1/docker/demo-example-com/app/Dockerfile"]
    assert "create-next-app" in dockerfile


def test_create_site_deploys_laravel_with_redis() -> None:
    fake = FakeSSH()

    create_site(
        "demo.example.com",
        settings=settings(),
        framework="laravel",
        redis_enabled=True,
        ssh_factory=lambda _settings, _password: fake,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert "docker inspect -f '{{.State.Running}}' demo-example-com-redis" in fake.commands
    env = fake.uploads["/volume1/docker/demo-example-com/app/.env"]
    assert "CACHE_STORE=redis" in env


def test_create_site_deploys_laravel_with_queue_worker() -> None:
    fake = FakeSSH()

    create_site(
        "demo.example.com",
        settings=settings(),
        framework="laravel",
        redis_enabled=True,
        queue_enabled=True,
        ssh_factory=lambda _settings, _password: fake,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert "docker inspect -f '{{.State.Running}}' demo-example-com-queue" in fake.commands


def test_create_site_deploys_laravel_with_scheduler() -> None:
    fake = FakeSSH()

    create_site(
        "demo.example.com",
        settings=settings(),
        framework="laravel",
        scheduler_enabled=True,
        ssh_factory=lambda _settings, _password: fake,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert "docker inspect -f '{{.State.Running}}' demo-example-com-scheduler" in fake.commands


def test_create_site_rejects_scheduler_for_non_laravel_framework_before_touching_ssh() -> None:
    def boom(_settings: object, _password: object) -> object:
        raise AssertionError("SSH should not be attempted for a rejected --with-scheduler combo")

    with pytest.raises(SynologySiteError, match="only applicable to --framework laravel"):
        create_site(
            "demo.example.com",
            settings=settings(),
            framework="flask",
            scheduler_enabled=True,
            ssh_factory=boom,
        )


def test_create_site_rejects_queue_without_redis() -> None:
    def boom(_settings: object, _password: object) -> object:
        raise AssertionError("SSH should not be attempted for a rejected --with-queue combo")

    with pytest.raises(SynologySiteError, match="requires --with-redis"):
        create_site(
            "demo.example.com",
            settings=settings(),
            framework="laravel",
            queue_enabled=True,
            ssh_factory=boom,
        )


def test_create_site_rejects_redis_for_non_laravel_framework_before_touching_ssh() -> None:
    def boom(_settings: object, _password: object) -> object:
        raise AssertionError("SSH should not be attempted for a rejected --with-redis combo")

    with pytest.raises(SynologySiteError, match="only applicable to --framework laravel"):
        create_site(
            "demo.example.com",
            settings=settings(),
            framework="flask",
            redis_enabled=True,
            ssh_factory=boom,
        )


def test_create_site_deploys_laravel_with_livewire_single_container() -> None:
    fake = FakeSSH()

    result = create_site(
        "demo.example.com",
        settings=settings(),
        framework="laravel",
        frontend="livewire",
        ssh_factory=lambda _settings, _password: fake,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert result.port == 5051
    dockerfile = fake.uploads["/volume1/docker/demo-example-com/app/Dockerfile"]
    assert "livewire/livewire" in dockerfile
    assert "/volume1/docker/demo-example-com/app/nginx.conf" not in fake.uploads


def test_create_site_deploys_laravel_inertia_vue_single_container() -> None:
    fake = FakeSSH()

    result = create_site(
        "demo.example.com",
        settings=settings(),
        framework="laravel",
        frontend="inertia-vue",
        ssh_factory=lambda _settings, _password: fake,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert result.port == 5051
    dockerfile = fake.uploads["/volume1/docker/demo-example-com/app/Dockerfile"]
    assert "laravel/breeze" in dockerfile
    assert "breeze:install vue" in dockerfile
    assert "npm run build" in dockerfile


def test_create_site_deploys_laravel_decoupled_spa_vue_requires_fpm_nginx() -> None:
    fake = FakeSSH()

    result = create_site(
        "demo.example.com",
        settings=settings(),
        framework="laravel",
        frontend="vue",
        php_server="fpm-nginx",
        ssh_factory=lambda _settings, _password: fake,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert result.port == 5051
    dockerfile = fake.uploads["/volume1/docker/demo-example-com/app/Dockerfile"]
    assert "breeze:install api" in dockerfile
    assert "FROM node:20-alpine AS frontend-build" in dockerfile
    nginx_conf = fake.uploads["/volume1/docker/demo-example-com/app/nginx.conf"]
    assert "location ~ ^/(api|health|db-health)" in nginx_conf
    assert (
        "docker inspect -f '{{.State.Running}}' demo-example-com-web" in fake.commands
    )


def test_create_site_deploys_laravel_fpm_nginx_confirms_both_containers() -> None:
    fake = FakeSSH()

    result = create_site(
        "demo.example.com",
        settings=settings(),
        framework="laravel",
        php_server="fpm-nginx",
        ssh_factory=lambda _settings, _password: fake,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert result.port == 5051
    assert "/volume1/docker/demo-example-com/app/nginx.conf" in fake.uploads
    assert (
        "docker inspect -f '{{.State.Running}}' demo-example-com-web" in fake.commands
    )
    assert "docker inspect -f '{{.State.Running}}' demo-example-com" in fake.commands
    dockerfile = fake.uploads["/volume1/docker/demo-example-com/app/Dockerfile"]
    assert "FROM php:8.3-fpm AS php-fpm" in dockerfile
    assert "FROM nginx:alpine AS nginx" in dockerfile


def test_create_site_rejects_php_server_for_non_laravel_framework() -> None:
    with pytest.raises(SynologySiteError, match="only applicable to --framework laravel"):
        create_site(
            "demo.example.com",
            settings=settings(),
            framework="flask",
            php_server="fpm-nginx",
            ssh_factory=lambda _settings, _password: FakeSSH(),
        )


def test_create_site_rejects_unknown_php_server() -> None:
    with pytest.raises(SynologySiteError, match="Unsupported --php-server"):
        create_site(
            "demo.example.com",
            settings=settings(),
            framework="laravel",
            php_server="bogus",
            ssh_factory=lambda _settings, _password: FakeSSH(),
        )


def test_create_site_uses_resolved_nas_target_for_ssh_connection() -> None:
    """A workspace's own nas.env target must actually drive the SSH connection --
    not just be resolvable in config while create_site quietly keeps using the default NAS."""
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

    create_site(
        "demo.example.com",
        settings=multi_nas_settings,
        workspace="clienta",
        ssh_factory=capturing_ssh_factory,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert captured_settings[0].nas_host == "203.0.113.5"
    assert captured_settings[0].nas_port == 2222
    assert captured_settings[0].nas_user == "clienta-deploy"
    assert captured_settings[0].nas_ssh_password == "clienta-secret"


def test_create_site_without_workspace_keeps_using_default_nas_target() -> None:
    fake = FakeSSH()
    captured_settings: list[Settings] = []

    def capturing_ssh_factory(passed_settings: Settings, _password: object) -> FakeSSH:
        captured_settings.append(passed_settings)
        return fake

    create_site(
        "demo.example.com",
        settings=settings(),
        ssh_factory=capturing_ssh_factory,
        health_get=lambda _url, timeout: FakeResponse(),
    )

    assert captured_settings[0].nas_host == "192.0.2.10"


def test_create_site_refuses_existing_project_without_force() -> None:
    fake = FakeSSH(project_exists=True)

    with pytest.raises(SynologySiteError, match="already exists"):
        create_site(
            "demo.example.com",
            settings=settings(),
            ssh_factory=lambda _settings, _password: fake,
            health_get=lambda _url, timeout: FakeResponse(),
        )


def test_create_site_deploys_flask_with_db() -> None:
    fake = FakeSSH()
    health_urls: list[str] = []

    def health_get(url: str, timeout: int) -> FakeResponse:
        del timeout
        health_urls.append(url)
        return FakeResponse()

    result = create_site(
        "demo.example.com",
        settings=settings(),
        db_mode="container",
        ssh_factory=lambda _settings, _password: fake,
        health_get=health_get,
    )

    assert result.db_enabled is True
    assert result.db_health_url == "http://192.0.2.10:5051/db-health"
    assert "/volume1/docker/demo-example-com/app/.env" in fake.uploads
    assert "/volume1/docker/demo-example-com/docs/DATABASE.md" in fake.uploads
    assert "chmod 600 /volume1/docker/demo-example-com/app/.env" in fake.commands
    assert "chmod 600 /volume1/docker/demo-example-com/docs/DATABASE.md" in fake.commands
    assert "http://192.0.2.10:5051/health" in health_urls
    assert "http://192.0.2.10:5051/db-health" in health_urls
