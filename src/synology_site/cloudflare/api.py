from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from synology_site.config import Settings
from synology_site.errors import SynologySiteError

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"


@dataclass(frozen=True)
class CloudflareRouteResult:
    hostname: str
    service_url: str
    dns_record_id: str | None
    tunnel_configured: bool
    dns_configured: bool


class CloudflareAPI:
    def __init__(self, settings: Settings, session: Any = requests) -> None:
        if not settings.cloudflare_api_ready:
            raise SynologySiteError("Cloudflare API credentials are incomplete")
        self.settings = settings
        self.session = session

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.cf_api_token}",
            "Content-Type": "application/json",
        }

    def configure_tunnel_route(self, hostname: str, service_url: str) -> CloudflareRouteResult:
        self._update_tunnel_ingress(hostname, service_url)
        dns_record_id = self._ensure_dns_record(hostname)
        return CloudflareRouteResult(
            hostname=hostname,
            service_url=service_url,
            dns_record_id=dns_record_id,
            tunnel_configured=True,
            dns_configured=True,
        )

    def _update_tunnel_ingress(self, hostname: str, service_url: str) -> None:
        endpoint = (
            f"{CLOUDFLARE_API_BASE}/accounts/{self.settings.cf_account_id}"
            f"/cfd_tunnel/{self.settings.cf_tunnel_id}/configurations"
        )
        current = self._request("GET", endpoint)
        config = current.get("result", {}).get("config") or {}
        ingress = list(config.get("ingress") or [])
        catch_all = [
            item for item in ingress if item.get("service", "").startswith("http_status:")
        ]
        ingress = [item for item in ingress if item.get("hostname") != hostname]
        ingress = [
            item for item in ingress if not item.get("service", "").startswith("http_status:")
        ]
        ingress.append({"hostname": hostname, "service": service_url})
        ingress.extend(catch_all or [{"service": "http_status:404"}])
        self._request("PUT", endpoint, json={"config": {"ingress": ingress}})

    def _ensure_dns_record(self, hostname: str) -> str | None:
        target = f"{self.settings.cf_tunnel_id}.cfargotunnel.com"
        list_endpoint = f"{CLOUDFLARE_API_BASE}/zones/{self.settings.cf_zone_id}/dns_records"
        current = self._request(
            "GET",
            list_endpoint,
            params={"type": "CNAME", "name": hostname},
        )
        records = current.get("result") or []
        payload = {
            "type": "CNAME",
            "name": hostname,
            "content": target,
            "proxied": True,
        }
        if records:
            record_id = records[0]["id"]
            self._request("PUT", f"{list_endpoint}/{record_id}", json=payload)
            return str(record_id)
        created = self._request("POST", list_endpoint, json=payload)
        record_id = created.get("result", {}).get("id")
        return str(record_id) if record_id else None

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        response = self.session.request(method, url, headers=self.headers, timeout=30, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            msg = "Cloudflare API returned invalid JSON"
            raise SynologySiteError(msg) from exc
        if response.status_code >= 400 or not payload.get("success", False):
            errors = payload.get("errors") or []
            detail = (
                errors[0].get("message")
                if errors and isinstance(errors[0], dict)
                else "unknown"
            )
            msg = f"Cloudflare API request failed: {detail}"
            raise SynologySiteError(msg)
        return payload


def configure_cloudflare_route(
    settings: Settings,
    *,
    hostname: str,
    service_url: str,
    session: Any = requests,
) -> CloudflareRouteResult:
    return CloudflareAPI(settings, session=session).configure_tunnel_route(hostname, service_url)
