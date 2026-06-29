from __future__ import annotations

from synology_site.cloudflare.domain_split import split_domain_for_zone


def build_manual_instructions(
    domain: str,
    zone_domain: str,
    local_host: str,
    port: int,
    tunnel_name: str,
) -> str:
    split = split_domain_for_zone(domain, zone_domain, strict=False)
    warning = f"\n[WARN] {split.warning}\n" if split.warning else ""
    return (
        "Cloudflare manual setup required\n\n"
        f"{warning}"
        "1. Open Cloudflare.\n"
        "2. Go to Cloudflare One / Zero Trust.\n"
        "3. Go to Networks.\n"
        "4. Go to Connectors.\n"
        f"5. Open your tunnel, for example {tunnel_name}.\n"
        "6. Go to Published application routes.\n"
        "7. Click Add a published application route.\n"
        "8. Enter:\n\n"
        f"   Subdomain: {split.subdomain}\n"
        f"   Domain: {split.zone_domain}\n"
        "   Path: leave empty\n\n"
        "   Service type: HTTP\n"
        f"   Service URL: {local_host}:{port}\n\n"
        "9. Save.\n"
        "10. Go back to Cloudflare DNS records and confirm a tunnel record exists:\n\n"
        f"   {split.domain}    Tunnel    {tunnel_name}    Proxied\n\n"
        "11. Open:\n\n"
        f"   https://{split.domain}\n\n"
        "If you see Cloudflare Error 1033:\n\n"
        "The tunnel DNS record exists, but Cloudflare cannot currently resolve the tunnel "
        "connection.\n\n"
        "Check the tunnel container on the NAS:\n\n"
        "sudo docker ps\n"
        "sudo docker ps -a\n\n"
        "If cloudflared is stopped, start it:\n\n"
        "sudo docker start cloudflared\n\n"
        "If the container has a random name such as clever_carver:\n\n"
        "sudo docker start clever_carver\n\n"
        "Then rename it:\n\n"
        "sudo docker stop clever_carver\n"
        "sudo docker rename clever_carver cloudflared\n"
        "sudo docker start cloudflared\n"
        "sudo docker update --restart unless-stopped cloudflared\n\n"
        "If direct IP works but the domain does not:\n\n"
        "1. Check the Cloudflare Tunnel status.\n"
        "2. Check Published application routes.\n"
        "3. Check DNS records.\n"
        "4. Confirm the route service URL points to:\n"
        f"   http://{local_host}:{port}\n"
        "5. Confirm the Flask container is running.\n"
    )
