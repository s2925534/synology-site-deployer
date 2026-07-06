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
    with pytest.raises(SynologySiteError, match="Unknown workspace"):
        settings.resolve_cloudflare("app.example.com", workspace="does-not-exist")


def test_discover_cloudflare_accounts_requires_zone_domain(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "secrets" / "broken"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "cloudflare.env").write_text("CF_API_TOKEN=token", encoding="utf-8")

    with pytest.raises(SynologySiteError, match="CF_ZONE_DOMAIN"):
        load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")


def write_nas_target(tmp_path: Path, name: str, **overrides: str) -> None:
    workspace_dir = tmp_path / "secrets" / name
    workspace_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in overrides.items()]
    (workspace_dir / "nas.env").write_text("\n".join(lines), encoding="utf-8")


def test_load_config_default_nas_target_matches_root_env(tmp_path: Path) -> None:
    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    target = settings.default_nas_target
    assert target.name == "default"
    assert target.host == "192.0.2.10"
    assert target.docker_root == "/volume1/docker"
    assert target.system_type == "synology"


def test_load_config_discovers_extra_nas_target_and_inherits_unset_fields(tmp_path: Path) -> None:
    write_nas_target(tmp_path, "clienta", NAS_HOST="203.0.113.5", NAS_USER="clienta-deploy")

    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    assert [target.name for target in settings.nas_targets] == ["clienta"]
    target = settings.nas_targets[0]
    assert target.host == "203.0.113.5"
    assert target.user == "clienta-deploy"
    # Not overridden -- inherited from the root .env's default target.
    assert target.docker_root == "/volume1/docker"
    assert target.local_base_url_host == "192.0.2.10"


def test_resolve_target_falls_back_to_default_when_workspace_has_no_nas_override(
    tmp_path: Path,
) -> None:
    write_workspace(tmp_path, "acmeco", zone_domain="acmeco.dev")

    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    # "acmeco" is a known (Cloudflare-only) workspace but has no nas.env of its own.
    target = settings.resolve_target(workspace="acmeco")
    assert target.name == "default"
    assert target.host == "192.0.2.10"


def test_resolve_target_explicit_workspace_override(tmp_path: Path) -> None:
    write_nas_target(tmp_path, "clienta", NAS_HOST="203.0.113.5")

    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    assert settings.resolve_target(workspace="clienta").host == "203.0.113.5"
    assert settings.resolve_target().host == "192.0.2.10"


def test_nas_only_workspace_is_valid_for_cloudflare_resolution_too(tmp_path: Path) -> None:
    """A workspace that only overrides the NAS target (no cloudflare.env) must not be rejected
    as an "unknown Cloudflare workspace" -- it should just fall back to the default account."""
    write_nas_target(tmp_path, "clienta", NAS_HOST="203.0.113.5")

    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    account = settings.resolve_cloudflare("app.example.com", workspace="clienta")
    assert account.name == "default"


def test_cloudflare_only_workspace_is_valid_for_target_resolution_too(tmp_path: Path) -> None:
    """The reverse of the above: a Cloudflare-only workspace must not be rejected when resolving
    the NAS target, even though it has no nas.env of its own."""
    write_workspace(tmp_path, "acmeco", zone_domain="acmeco.dev")

    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    target = settings.resolve_target(workspace="acmeco")
    assert target.name == "default"


def test_validate_workspace_rejects_name_unknown_to_both_accounts_and_targets(
    tmp_path: Path,
) -> None:
    settings = load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")

    with pytest.raises(SynologySiteError, match="Unknown workspace"):
        settings.validate_workspace("does-not-exist")


def test_discover_nas_targets_rejects_invalid_system_type(tmp_path: Path) -> None:
    write_nas_target(tmp_path, "broken", SYSTEM_TYPE="windows")

    with pytest.raises(SynologySiteError, match="SYSTEM_TYPE"):
        load_config(write_env(tmp_path), secrets_dir=tmp_path / "secrets")
