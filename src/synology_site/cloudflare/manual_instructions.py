from __future__ import annotations


def build_manual_instructions(
    domain: str,
    zone_domain: str,
    local_host: str,
    port: int,
    tunnel_name: str,
) -> str:
    return (
        "Cloudflare manual setup required\n\n"
        f"Domain: {domain}\n"
        f"Zone domain: {zone_domain}\n"
        f"Service URL: {local_host}:{port}\n"
        f"Tunnel: {tunnel_name}\n"
    )
