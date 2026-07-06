from pathlib import Path

import pytest

from synology_site.config import load_config
from synology_site.errors import SynologySiteError


def write_env(tmp_path: Path, extra: str = "") -> Path:
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
                extra,
            ]
        ),
        encoding="utf-8",
    )
    return env_path


def test_load_config_defaults_and_missing_optional_cloudflare(tmp_path: Path) -> None:
    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    assert settings.nas_host == "192.0.2.10"
    assert settings.nas_port == 22
    assert settings.cf_api_token is None
    assert settings.cf_tunnel_id is None
    assert settings.default_cloudflare_account.ready is False
    assert settings.db_mode == "none"
    assert settings.db_publish_port is False


def test_load_config_detects_complete_cloudflare_api_config(tmp_path: Path) -> None:
    settings = load_config(
        write_env(
            tmp_path,
            "\n".join(
                [
                    "CF_API_TOKEN=token",
                    "CF_ACCOUNT_ID=account",
                    "CF_ZONE_ID=zone",
                    "CF_TUNNEL_ID=tunnel",
                ]
            ),
        )
    )

    assert settings.default_cloudflare_account.ready is True


def test_load_config_requires_core_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("NAS_HOST=192.0.2.10\n", encoding="utf-8")

    with pytest.raises(SynologySiteError, match="NAS_USER"):
        load_config(env_path)


def test_load_config_default_site_domain_defaults_to_none(tmp_path: Path) -> None:
    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    assert settings.default_site_domain is None


def test_load_config_reads_default_site_domain(tmp_path: Path) -> None:
    settings = load_config(write_env(tmp_path, "DEFAULT_SITE_DOMAIN=veloso.dev"))

    assert settings.default_site_domain == "veloso.dev"


def write_workspace(tmp_path: Path, name: str, *, zone_domain: str, **extra: str) -> None:
    workspace_dir = tmp_path / "secrets" / name
    workspace_dir.mkdir(parents=True)
    lines = [f"CF_ZONE_DOMAIN={zone_domain}"] + [f"{key}={value}" for key, value in extra.items()]
    (workspace_dir / "cloudflare.env").write_text("\n".join(lines), encoding="utf-8")


def test_load_config_discovers_extra_cloudflare_workspaces(tmp_path: Path) -> None:
    write_workspace(
        tmp_path,
        "acmeco",
        zone_domain="acmeco.dev",
        CF_API_TOKEN="acme-token",
        CF_ACCOUNT_ID="acme-account",
        CF_ZONE_ID="acme-zone",
        CF_TUNNEL_ID="acme-tunnel",
    )

    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    assert [account.name for account in settings.cloudflare_accounts] == ["acmeco"]
    account = settings.cloudflare_accounts[0]
    assert account.zone_domain == "acmeco.dev"
    assert account.ready is True


def test_resolve_cloudflare_matches_domain_to_workspace(tmp_path: Path) -> None:
    write_workspace(tmp_path, "acmeco", zone_domain="acmeco.dev")

    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    assert settings.resolve_cloudflare("app.acmeco.dev").name == "acmeco"
    assert settings.resolve_cloudflare("app.example.com").name == "default"


def test_resolve_cloudflare_explicit_workspace_override(tmp_path: Path) -> None:
    write_workspace(tmp_path, "acmeco", zone_domain="acmeco.dev")

    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    assert settings.resolve_cloudflare("app.example.com", workspace="acmeco").name == "acmeco"
    with pytest.raises(SynologySiteError, match="Unknown Cloudflare workspace"):
        settings.resolve_cloudflare("app.example.com", workspace="does-not-exist")


def test_discover_cloudflare_accounts_requires_zone_domain(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "secrets" / "broken"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "cloudflare.env").write_text("CF_API_TOKEN=token", encoding="utf-8")

    with pytest.raises(SynologySiteError, match="CF_ZONE_DOMAIN"):
        load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")
