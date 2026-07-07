from __future__ import annotations

import pytest

from synology_site.errors import SynologySiteError
from synology_site.tailscale import (
    TailscaleDevice,
    fetch_access_token,
    list_devices,
    select_nas_device,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, object]:
        return self.payload


class FakeSession:
    def __init__(self, *, token_payload=None, devices_payload=None) -> None:
        self.token_payload = (
            token_payload if token_payload is not None else {"access_token": "fake-token"}
        )
        self.devices_payload = devices_payload if devices_payload is not None else {"devices": []}
        self.requests: list[tuple[str, str, dict[str, object]]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.requests.append(("POST", url, kwargs))
        return FakeResponse(self.token_payload)

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.requests.append(("GET", url, kwargs))
        return FakeResponse(self.devices_payload)


def test_fetch_access_token_returns_token() -> None:
    session = FakeSession(token_payload={"access_token": "abc123"})

    token = fetch_access_token("client-id", "client-secret", session=session)

    assert token == "abc123"
    method, url, kwargs = session.requests[0]
    assert method == "POST"
    assert url.endswith("/oauth/token")
    assert kwargs["data"] == {"client_id": "client-id", "client_secret": "client-secret"}


def test_fetch_access_token_raises_on_missing_token() -> None:
    session = FakeSession(token_payload={})

    with pytest.raises(SynologySiteError, match="access_token"):
        fetch_access_token("client-id", "client-secret", session=session)


def test_fetch_access_token_raises_on_error_status() -> None:
    class ErrorSession(FakeSession):
        def post(self, url: str, **kwargs: object) -> FakeResponse:
            return FakeResponse({"message": "invalid client credentials"}, status_code=401)

    with pytest.raises(SynologySiteError, match="invalid client credentials"):
        fetch_access_token("bad-id", "bad-secret", session=ErrorSession())


def test_list_devices_parses_response() -> None:
    session = FakeSession(
        devices_payload={
            "devices": [
                {
                    "id": "1",
                    "hostname": "nas",
                    "name": "nas.tailnet.ts.net",
                    "addresses": ["100.64.1.2", "fd7a:115c:a1e0::1"],
                    "os": "linux",
                },
            ]
        }
    )

    devices = list_devices("token", session=session)

    assert len(devices) == 1
    assert devices[0].hostname == "nas"
    assert devices[0].tailscale_ipv4 == "100.64.1.2"
    method, url, kwargs = session.requests[0]
    assert kwargs["headers"] == {"Authorization": "Bearer token"}
    assert url.endswith("/tailnet/-/devices")


def _device(hostname: str, ip: str, *, name: str | None = None) -> TailscaleDevice:
    return TailscaleDevice(
        id=hostname, hostname=hostname, name=name or f"{hostname}.tailnet.ts.net",
        addresses=(ip,), os="linux",
    )


def test_select_nas_device_single_device_is_unambiguous() -> None:
    device = _device("nas", "100.64.1.2")

    assert select_nas_device((device,)) is device


def test_select_nas_device_matches_by_name() -> None:
    laptop = _device("work-laptop", "100.64.1.1")
    nas = _device("synology-nas", "100.64.1.2")

    assert select_nas_device((laptop, nas), device_name="synology") is nas


def test_select_nas_device_prefers_current_tailscale_host() -> None:
    laptop = _device("work-laptop", "100.64.1.1")
    nas = _device("synology-nas", "100.64.1.2")

    selected = select_nas_device((laptop, nas), current_tailscale_host="100.64.1.2")

    assert selected is nas


def test_select_nas_device_raises_on_ambiguity() -> None:
    laptop = _device("work-laptop", "100.64.1.1")
    nas = _device("synology-nas", "100.64.1.2")

    with pytest.raises(SynologySiteError, match="Multiple Tailscale devices"):
        select_nas_device((laptop, nas))


def test_select_nas_device_raises_when_device_name_matches_nothing() -> None:
    nas = _device("synology-nas", "100.64.1.2")

    with pytest.raises(SynologySiteError, match="No Tailscale device matched"):
        select_nas_device((nas,), device_name="raspberry-pi")


def test_select_nas_device_raises_on_empty_tailnet() -> None:
    with pytest.raises(SynologySiteError, match="No devices found"):
        select_nas_device(())
