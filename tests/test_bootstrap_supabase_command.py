from __future__ import annotations

from pathlib import Path

import pytest

from synology_site.commands.bootstrap_supabase import bootstrap_supabase
from synology_site.config import Settings
from synology_site.errors import SynologySiteError
from synology_site.ssh_client import RemoteCommandResult

ENV_EXAMPLE = "\n".join(
    [
        "POSTGRES_PASSWORD=example",
        "JWT_SECRET=example",
        "ANON_KEY=example",
        "SERVICE_ROLE_KEY=example",
        "DASHBOARD_USERNAME=supabase",
        "DASHBOARD_PASSWORD=example",
        "SECRET_KEY_BASE=example",
        "VAULT_ENC_KEY=example",
        "STUDIO_DEFAULT_ORGANIZATION=Default Organization",
    ]
)


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
        elif command == "test -e /volume1/docker/supabase":
            exit_code = 0 if self.project_exists else 1
        elif command.endswith(".env.example"):
            stdout = ENV_EXAMPLE
        result = RemoteCommandResult(command, exit_code, stdout, "")
        if check and not result.ok:
            raise SynologySiteError("command failed")
        return result

    def upload_text(self, remote_path: str, content: str) -> None:
        self.uploads[remote_path] = content


def test_bootstrap_supabase_clones_generates_secrets_and_starts(tmp_path: Path) -> None:
    fake = FakeSSH()
    secrets_dir = tmp_path / "secrets"

    result = bootstrap_supabase(
        settings=settings(),
        secrets_dir=secrets_dir,
        now=1_000_000,
        ssh_factory=lambda _settings, _password: fake,
    )

    assert result.project_path == "/volume1/docker/supabase"
    assert any("git clone --depth 1" in c and "supabase-src" in c for c in fake.commands)
    assert any("cp -r /volume1/docker/supabase-src/docker/." in c for c in fake.commands)
    assert "mkdir -p /volume1/docker/supabase/volumes/storage" in fake.commands
    assert "mkdir -p /volume1/docker/supabase/volumes/db/data" in fake.commands
    assert "cd /volume1/docker/supabase && docker compose up -d" in fake.commands

    uploaded_env = fake.uploads["/volume1/docker/supabase/.env"]
    assert "POSTGRES_PASSWORD=example" not in uploaded_env
    assert "POSTGRES_PORT=5433" in uploaded_env
    assert "STUDIO_DEFAULT_ORGANIZATION=Default Organization" in uploaded_env
    assert "chmod 600 /volume1/docker/supabase/.env" in fake.commands

    secrets_path = Path(result.secrets_file)
    assert secrets_path.exists()
    assert secrets_path.read_text(encoding="utf-8") == uploaded_env


def test_bootstrap_supabase_refuses_existing_project_without_force() -> None:
    fake = FakeSSH(project_exists=True)

    with pytest.raises(SynologySiteError, match="already exists"):
        bootstrap_supabase(
            settings=settings(),
            ssh_factory=lambda _settings, _password: fake,
        )


def test_bootstrap_supabase_force_tears_down_existing_project() -> None:
    fake = FakeSSH(project_exists=True)

    bootstrap_supabase(
        settings=settings(),
        force=True,
        ssh_factory=lambda _settings, _password: fake,
    )

    assert "cd /volume1/docker/supabase && docker compose down" in fake.commands
    assert "sudo -S -p '' rm -rf /volume1/docker/supabase" in fake.commands


def test_bootstrap_supabase_uploads_traefik_override_when_given(tmp_path: Path) -> None:
    fake = FakeSSH()
    override_file = tmp_path / "docker-compose.override.yml"
    override_file.write_text("services:\n  kong:\n    labels: []\n")

    bootstrap_supabase(
        settings=settings(),
        secrets_dir=tmp_path / "secrets",
        traefik_override_file=override_file,
        ssh_factory=lambda _settings, _password: fake,
    )

    assert (
        fake.uploads["/volume1/docker/supabase/docker-compose.override.yml"]
        == override_file.read_text()
    )
    assert (
        "cd /volume1/docker/supabase && docker compose -f docker-compose.yml "
        "-f docker-compose.override.yml up -d" in fake.commands
    )


def test_bootstrap_supabase_missing_traefik_override_raises(tmp_path: Path) -> None:
    fake = FakeSSH()

    with pytest.raises(SynologySiteError, match="Traefik override file not found"):
        bootstrap_supabase(
            settings=settings(),
            secrets_dir=tmp_path / "secrets",
            traefik_override_file=tmp_path / "missing.yml",
            ssh_factory=lambda _settings, _password: fake,
        )


def test_bootstrap_supabase_dry_run_skips_remote_writes() -> None:
    fake = FakeSSH()

    result = bootstrap_supabase(
        settings=settings(),
        dry_run=True,
        ssh_factory=lambda _settings, _password: fake,
    )

    assert result.secrets_file == ""
    assert fake.uploads == {}
    assert not any("git clone" in c for c in fake.commands)
