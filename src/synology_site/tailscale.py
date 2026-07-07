from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from synology_site.errors import SynologySiteError

TAILSCALE_API_BASE = "https://api.tailscale.com/api/v2"


@dataclass(frozen=True)
class TailscaleDevice:
    id: str
    hostname: str
    name: str
    addresses: tuple[str, ...]
    os: str

    @property
    def tailscale_ipv4(self) -> str | None:
        for address in self.addresses:
            if address.startswith("100."):
                return address
        return None


def _payload_or_error(response: Any, *, context: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        msg = f"Tailscale API returned invalid JSON ({context})"
        raise SynologySiteError(msg) from exc
    if response.status_code >= 400:
        detail = payload.get("message") or payload.get("error") or "unknown error"
        msg = f"Tailscale API request failed ({context}): {detail}"
        raise SynologySiteError(msg)
    return payload


def fetch_access_token(client_id: str, client_secret: str, *, session: Any = requests) -> str:
    response = session.post(
        f"{TAILSCALE_API_BASE}/oauth/token",
        data={"client_id": client_id, "client_secret": client_secret},
        timeout=15,
    )
    payload = _payload_or_error(response, context="oauth/token")
    token = payload.get("access_token")
    if not token:
        msg = "Tailscale OAuth response did not include an access_token"
        raise SynologySiteError(msg)
    return str(token)


def list_devices(access_token: str, *, session: Any = requests) -> tuple[TailscaleDevice, ...]:
    response = session.get(
        f"{TAILSCALE_API_BASE}/tailnet/-/devices",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    payload = _payload_or_error(response, context="tailnet/-/devices")
    devices = []
    for item in payload.get("devices", []):
        devices.append(
            TailscaleDevice(
                id=str(item.get("id", "")),
                hostname=str(item.get("hostname", "")),
                name=str(item.get("name", "")),
                addresses=tuple(item.get("addresses") or []),
                os=str(item.get("os", "")),
            )
        )
    return tuple(devices)


def select_nas_device(
    devices: tuple[TailscaleDevice, ...],
    *,
    device_name: str | None = None,
    current_tailscale_host: str | None = None,
) -> TailscaleDevice:
    """Pick which tailnet device is the NAS.

    Explicit --device-name always wins when given. Otherwise, if a TAILSCALE_NAS_HOST is
    already configured, prefer the device that currently owns that address (refreshing/
    confirming an existing setup). A single-device tailnet is unambiguous. Anything else is a
    real ambiguity -- list the candidates and ask, rather than guessing which one is the NAS.
    """
    if not devices:
        msg = "No devices found in this Tailscale tailnet"
        raise SynologySiteError(msg)

    if device_name:
        needle = device_name.strip().lower()
        matches = [
            device
            for device in devices
            if needle in device.hostname.lower() or needle in device.name.lower()
        ]
        if len(matches) == 1:
            return matches[0]
        available = ", ".join(sorted({device.hostname for device in devices}))
        if not matches:
            msg = (
                f"No Tailscale device matched --device-name {device_name!r}. "
                f"Available: {available}"
            )
            raise SynologySiteError(msg)
        matched = ", ".join(sorted({device.hostname for device in matches}))
        msg = f"--device-name {device_name!r} matched multiple devices: {matched}"
        raise SynologySiteError(msg)

    if current_tailscale_host:
        for device in devices:
            if device.tailscale_ipv4 == current_tailscale_host:
                return device

    if len(devices) == 1:
        return devices[0]

    available = ", ".join(
        sorted(f"{device.hostname} ({device.tailscale_ipv4})" for device in devices)
    )
    msg = (
        "Multiple Tailscale devices found and none could be identified as the NAS "
        f"automatically. Pass --device-name to pick one. Available: {available}"
    )
    raise SynologySiteError(msg)
