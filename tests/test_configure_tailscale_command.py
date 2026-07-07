from __future__ import annotations

from pathlib import Path

import pytest

from synology_site.commands.configure_tailscale import configure_tailscale
from synology_site.errors import SynologySiteError


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.status_code = 200

    def json(self) -> dict[str, object]:
        return self.payload


class FakeSession:
    def __init__(self, *, devices: list[dict[str, object]]) -> None:
        self.devices = devices

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        del url, kwargs
        return FakeResponse({"access_token": "fake-token"})

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        del url, kwargs
        return FakeResponse({"devices": self.devices})


def device(hostname: str, ip: str) -> dict[str, object]:
    return {
        "id": hostname,
        "hostname": hostname,
        "name": hostname,
        "addresses": [ip],
        "os": "linux",
    }


def write_env(tmp_path: Path, extra: str = "") -> Path:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "NAS_HOST=192.168.1.100",
                "TAILSCALE_CLIENT_ID=client-id",
                "TAILSCALE_CLIENT_SECRET=client-secret",
                "TAILSCALE_ENABLED=false",
                "TAILSCALE_NAS_HOST=",
                extra,
            ]
        ),
        encoding="utf-8",
    )
    return env_path


def test_configure_tailscale_updates_env_file(tmp_path: Path) -> None:
    env_path = write_env(tmp_path)
    session = FakeSession(
        devices=[
            {
                "id": "1",
                "hostname": "synology-nas",
                "name": "synology-nas.tailnet.ts.net",
                "addresses": ["100.64.1.2"],
                "os": "linux",
            }
        ]
    )

    result = configure_tailscale(env_path=env_path, session=session)

    assert result.tailscale_host == "100.64.1.2"
    assert result.device_hostname == "synology-nas"
    assert result.updated is True

    updated_content = env_path.read_text(encoding="utf-8")
    assert "TAILSCALE_ENABLED=true" in updated_content
    assert "TAILSCALE_NAS_HOST=100.64.1.2" in updated_content
    # Untouched lines survive.
    assert "NAS_HOST=192.168.1.100" in updated_content
    assert "TAILSCALE_CLIENT_ID=client-id" in updated_content


def test_configure_tailscale_dry_run_does_not_write(tmp_path: Path) -> None:
    env_path = write_env(tmp_path)
    session = FakeSession(devices=[device("nas", "100.64.1.2")])
    original_content = env_path.read_text(encoding="utf-8")

    result = configure_tailscale(env_path=env_path, dry_run=True, session=session)

    assert result.updated is False
    assert env_path.read_text(encoding="utf-8") == original_content


def test_configure_tailscale_requires_client_credentials(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("NAS_HOST=192.168.1.100\n", encoding="utf-8")

    with pytest.raises(SynologySiteError, match="TAILSCALE_CLIENT_ID"):
        configure_tailscale(env_path=env_path, session=FakeSession(devices=[]))


def test_configure_tailscale_missing_env_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SynologySiteError, match="No .env file found"):
        configure_tailscale(env_path=tmp_path / "missing.env", session=FakeSession(devices=[]))


def test_configure_tailscale_ambiguous_devices_requires_device_name(tmp_path: Path) -> None:
    env_path = write_env(tmp_path)
    session = FakeSession(
        devices=[device("laptop", "100.64.1.1"), device("nas", "100.64.1.2")]
    )

    with pytest.raises(SynologySiteError, match="Multiple Tailscale devices"):
        configure_tailscale(env_path=env_path, session=session)

    result = configure_tailscale(env_path=env_path, device_name="nas", session=session)
    assert result.tailscale_host == "100.64.1.2"


def test_configure_tailscale_preserves_other_workspace_lines(tmp_path: Path) -> None:
    env_path = write_env(tmp_path, extra="SOME_OTHER_KEY=value\n# a comment")
    session = FakeSession(devices=[device("nas", "100.64.1.5")])

    configure_tailscale(env_path=env_path, session=session)

    content = env_path.read_text(encoding="utf-8")
    assert "SOME_OTHER_KEY=value" in content
    assert "# a comment" in content
