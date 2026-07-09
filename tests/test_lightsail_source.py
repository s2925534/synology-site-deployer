from __future__ import annotations

from pathlib import Path

import pytest

from synology_site.errors import SynologySiteError
from synology_site.lightsail.source import discover_lightsail_sources, resolve_lightsail_source


def test_discover_lightsail_sources_scans_secrets_dir(tmp_path: Path) -> None:
    workspace = tmp_path / "veloso-dev"
    workspace.mkdir()
    (workspace / "lightsail.env").write_text(
        "LIGHTSAIL_HOST=198.51.100.10\n"
        "LIGHTSAIL_PORT=2222\n"
        "LIGHTSAIL_USER=bitnami\n"
        "LIGHTSAIL_SSH_KEY_PATH=/keys/veloso-dev.pem\n",
        encoding="utf-8",
    )

    sources = discover_lightsail_sources(tmp_path)

    assert len(sources) == 1
    source = sources[0]
    assert source.name == "veloso-dev"
    assert source.host == "198.51.100.10"
    assert source.port == 2222
    assert source.user == "bitnami"
    assert source.ssh_key_path == "/keys/veloso-dev.pem"


def test_discover_lightsail_sources_defaults_port_22(tmp_path: Path) -> None:
    workspace = tmp_path / "veloso-dev"
    workspace.mkdir()
    (workspace / "lightsail.env").write_text(
        "LIGHTSAIL_HOST=198.51.100.10\nLIGHTSAIL_USER=ubuntu\n",
        encoding="utf-8",
    )

    sources = discover_lightsail_sources(tmp_path)

    assert sources[0].port == 22


def test_discover_lightsail_sources_requires_host_and_user(tmp_path: Path) -> None:
    workspace = tmp_path / "broken"
    workspace.mkdir()
    (workspace / "lightsail.env").write_text("LIGHTSAIL_HOST=198.51.100.10\n", encoding="utf-8")

    with pytest.raises(SynologySiteError, match="LIGHTSAIL_HOST and LIGHTSAIL_USER"):
        discover_lightsail_sources(tmp_path)


def test_discover_lightsail_sources_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    assert discover_lightsail_sources(tmp_path / "does-not-exist") == ()


def test_resolve_lightsail_source_matches_domain_slug(tmp_path: Path) -> None:
    workspace = tmp_path / "veloso-dev"
    workspace.mkdir()
    (workspace / "lightsail.env").write_text(
        "LIGHTSAIL_HOST=198.51.100.10\nLIGHTSAIL_USER=ubuntu\n", encoding="utf-8"
    )
    sources = discover_lightsail_sources(tmp_path)

    resolved = resolve_lightsail_source("veloso.dev", sources)

    assert resolved.name == "veloso-dev"


def test_resolve_lightsail_source_honors_explicit_workspace_override(tmp_path: Path) -> None:
    workspace = tmp_path / "custom-name"
    workspace.mkdir()
    (workspace / "lightsail.env").write_text(
        "LIGHTSAIL_HOST=198.51.100.10\nLIGHTSAIL_USER=ubuntu\n", encoding="utf-8"
    )
    sources = discover_lightsail_sources(tmp_path)

    resolved = resolve_lightsail_source("veloso.dev", sources, workspace="custom-name")

    assert resolved.name == "custom-name"


def test_resolve_lightsail_source_raises_when_missing(tmp_path: Path) -> None:
    with pytest.raises(SynologySiteError, match="No Lightsail source configured"):
        resolve_lightsail_source("veloso.dev", ())
