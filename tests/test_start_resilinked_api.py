from __future__ import annotations

from synology_site.commands.start_resilinked_api import run_start_resilinked_api
from synology_site.config import Settings
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


class FakeSSH:
    def __init__(self) -> None:
        self.commands: list[str] = []

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
        del check, timeout
        self.commands.append(command)
        if command == "command -v docker":
            return RemoteCommandResult(command, 0, "docker\n", "")
        if command == "docker ps --format '{{.Names}}'":
            return RemoteCommandResult(command, 0, "", "")
        if command == "docker compose version":
            return RemoteCommandResult(command, 0, "Docker Compose version v2\n", "")
        return RemoteCommandResult(command, 0, "", "")


def test_start_resilinked_api_brings_up_supabase_db_then_starts_the_container() -> None:
    fake = FakeSSH()

    run_start_resilinked_api(settings(), ssh_factory=lambda _settings, _password: fake)

    assert "cd /volume1/docker/supabase && docker compose up -d db" in fake.commands
    assert "docker start resilinked-api" in fake.commands
    db_index = fake.commands.index("cd /volume1/docker/supabase && docker compose up -d db")
    start_index = fake.commands.index("docker start resilinked-api")
    assert db_index < start_index
