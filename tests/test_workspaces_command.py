from __future__ import annotations

from pathlib import Path

from synology_site.commands.workspaces import check_workspaces
from synology_site.config import load_config


def write_env(tmp_path: Path) -> Path:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "NAS_HOST=192.0.2.10",
                "NAS_PORT=22",
                "NAS_USER=deploy",
                "NAS_DOCKER_ROOT=/volume1/docker",
                "LOCAL_BASE_URL_HOST=192.0.2.10",
                "DEFAULT_START_PORT=5050",
                "DEFAULT_END_PORT=5999",
                "CF_ZONE_DOMAIN=example.com",
                "CF_TUNNEL_NAME=my-nas-tunnel",
            ]
        ),
        encoding="utf-8",
    )
    return env_path


def write_workspace(tmp_path: Path, name: str, **fields: str) -> None:
    workspace_dir = tmp_path / "secrets" / name
    workspace_dir.mkdir(parents=True)
    lines = [f"{key}={value}" for key, value in fields.items()]
    (workspace_dir / "cloudflare.env").write_text("\n".join(lines), encoding="utf-8")


def test_check_workspaces_reports_nothing_for_independent_accounts(tmp_path: Path) -> None:
    write_workspace(
        tmp_path,
        "acmeco",
        CF_ZONE_DOMAIN="acmeco.dev",
        CF_TUNNEL_ID="acme-tunnel",
        CF_API_TOKEN="acme-token",
    )
    write_workspace(
        tmp_path,
        "clientb",
        CF_ZONE_DOMAIN="clientb.dev",
        CF_TUNNEL_ID="clientb-tunnel",
        CF_API_TOKEN="clientb-token",
    )

    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    assert check_workspaces(settings) == []


def test_check_workspaces_flags_duplicate_tunnel_id(tmp_path: Path) -> None:
    write_workspace(
        tmp_path, "acmeco", CF_ZONE_DOMAIN="acmeco.dev", CF_TUNNEL_ID="shared-tunnel"
    )
    write_workspace(
        tmp_path, "clientb", CF_ZONE_DOMAIN="clientb.dev", CF_TUNNEL_ID="shared-tunnel"
    )

    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    problems = check_workspaces(settings)
    assert len(problems) == 1
    assert "shared-tunnel" in problems[0]
    assert "acmeco" in problems[0]
    assert "clientb" in problems[0]


def test_check_workspaces_flags_duplicate_api_token(tmp_path: Path) -> None:
    write_workspace(
        tmp_path, "acmeco", CF_ZONE_DOMAIN="acmeco.dev", CF_API_TOKEN="shared-token"
    )
    write_workspace(
        tmp_path, "clientb", CF_ZONE_DOMAIN="clientb.dev", CF_API_TOKEN="shared-token"
    )

    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    problems = check_workspaces(settings)
    assert len(problems) == 1
    assert "shared-token" in problems[0].lower() or "CF_API_TOKEN" in problems[0]


def test_check_workspaces_does_not_flag_shared_nas_or_account_id(tmp_path: Path) -> None:
    """Sharing the same NAS or CF_ACCOUNT_ID across workspaces is the normal, supported
    multi-account/same-NAS setup -- it must not be treated as a doctor "problem"."""
    write_workspace(
        tmp_path,
        "acmeco",
        CF_ZONE_DOMAIN="acmeco.dev",
        CF_ACCOUNT_ID="shared-account",
        CF_TUNNEL_ID="acme-tunnel",
    )
    write_workspace(
        tmp_path,
        "clientb",
        CF_ZONE_DOMAIN="clientb.dev",
        CF_ACCOUNT_ID="shared-account",
        CF_TUNNEL_ID="clientb-tunnel",
    )

    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    assert check_workspaces(settings) == []
