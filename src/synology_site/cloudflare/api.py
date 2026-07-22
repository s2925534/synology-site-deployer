from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from synology_site.cloudflare.workspace import CloudflareAccount
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
    def __init__(self, account: CloudflareAccount, session: Any = requests) -> None:
        if not account.ready:
            raise SynologySiteError("Cloudflare API credentials are incomplete")
        self.account = account
        self.session = session

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.account.api_token}",
            "Content-Type": "application/json",
        }

    def get_dns_records(self, hostname: str) -> list[dict[str, Any]]:
        """Read-only lookup of existing DNS records for a hostname. Never writes anything."""
        list_endpoint = f"{CLOUDFLARE_API_BASE}/zones/{self.account.zone_id}/dns_records"
        current = self._request("GET", list_endpoint, params={"name": hostname})
        return list(current.get("result") or [])

    def get_zone_nameservers(self) -> list[str]:
        """Read-only lookup of the nameservers Cloudflare has assigned to this zone. Never
        writes anything -- used to compare against a registrar's (e.g. GoDaddy's) current
        nameservers without the operator having to paste them in manually."""
        result = self._request("GET", f"{CLOUDFLARE_API_BASE}/zones/{self.account.zone_id}")
        return list(result.get("result", {}).get("name_servers") or [])

    def get_tunnel_ingress(self) -> list[dict[str, Any]]:
        """Read-only lookup of the tunnel's full ingress rule list. Never writes anything.

        Useful for diagnosing `cloudflare-route` issues -- this tunnel is commonly shared
        across multiple workspaces/zones (one Cloudflare account, several domains, one NAS),
        so its ingress list holds entries for every hostname across all of them, not just one
        workspace's own.
        """
        current = self._request("GET", self._tunnel_config_endpoint)
        config = current.get("result", {}).get("config") or {}
        return list(config.get("ingress") or [])

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

    @property
    def _tunnel_config_endpoint(self) -> str:
        return (
            f"{CLOUDFLARE_API_BASE}/accounts/{self.account.account_id}"
            f"/cfd_tunnel/{self.account.tunnel_id}/configurations"
        )

    def _update_tunnel_ingress(self, hostname: str, service_url: str) -> None:
        endpoint = self._tunnel_config_endpoint
        ingress = self.get_tunnel_ingress()
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
        target = f"{self.account.tunnel_id}.cfargotunnel.com"
        list_endpoint = f"{CLOUDFLARE_API_BASE}/zones/{self.account.zone_id}/dns_records"
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
    account: CloudflareAccount,
    *,
    hostname: str,
    service_url: str,
    session: Any = requests,
) -> CloudflareRouteResult:
    return CloudflareAPI(account, session=session).configure_tunnel_route(hostname, service_url)
