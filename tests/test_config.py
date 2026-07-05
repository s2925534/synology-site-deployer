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
    settings = load_config(write_env(tmp_path))

    assert settings.nas_host == "192.0.2.10"
    assert settings.nas_port == 22
    assert settings.cf_api_token is None
    assert settings.cf_tunnel_id is None
    assert settings.cloudflare_api_ready is False
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

    assert settings.cloudflare_api_ready is True


def test_load_config_requires_core_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("NAS_HOST=192.0.2.10\n", encoding="utf-8")

    with pytest.raises(SynologySiteError, match="NAS_USER"):
        load_config(env_path)


def test_load_config_default_site_domain_defaults_to_none(tmp_path: Path) -> None:
    settings = load_config(write_env(tmp_path))

    assert settings.default_site_domain is None


def test_load_config_reads_default_site_domain(tmp_path: Path) -> None:
    settings = load_config(write_env(tmp_path, "DEFAULT_SITE_DOMAIN=veloso.dev"))

    assert settings.default_site_domain == "veloso.dev"
