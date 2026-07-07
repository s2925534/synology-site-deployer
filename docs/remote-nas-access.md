# Remote NAS Access

`synology-site` only needs SSH access to the Docker host. When you run the CLI away from the
NAS's LAN, solve the network path first and then point `NAS_HOST` at the reachable address. Do not
forward SSH from your home router unless you have a specific reason and a hardened SSH setup.

## Recommended: Tailscale

Tailscale is the default recommendation for remote use: it works through CGNAT, does not require a
router port forward, and the Synology package handles the outbound connection from the NAS.

1. Install **Tailscale** from Synology Package Center.
2. Open the Tailscale package and sign in.
3. In the Tailscale admin console, copy the NAS's `100.x.y.z` address.
4. Enable SSH in DSM: **Control Panel -> Terminal & SNMP -> Enable SSH service**.
5. If DSM Firewall is enabled, allow TCP `22` from `100.64.0.0/10`.
6. Install and sign in to Tailscale on the machine running `synology-site`.
7. Set `NAS_HOST` to the NAS's Tailscale address.

For the default workspace:

```env
NAS_HOST=100.x.y.z
NAS_PORT=22
```

For a workspace-specific NAS:

```text
secrets/
  remote-nas/
    nas.env
```

```env
NAS_HOST=100.x.y.z
NAS_PORT=22
SYSTEM_TYPE=synology
```

Leave `LOCAL_BASE_URL_HOST` as the address that the Cloudflare Tunnel connector can reach from
where it runs. If `cloudflared` runs on the NAS, the existing LAN/NAS-local address is usually the
right service target even when CLI SSH uses Tailscale.

## Alternative: ZeroTier

ZeroTier is similar operationally: install the package on the NAS, join the same virtual network
from the NAS and the CLI machine, then set `NAS_HOST` to the NAS's ZeroTier address. It is a good
fallback if Tailscale is unavailable in your environment.

## Alternative: Cloudflare Access SSH

Cloudflare Access can expose SSH through the existing Cloudflare Tunnel without opening inbound
ports. This is attractive when you already depend on Cloudflare, but it has more moving parts than
Tailscale:

- Zero Trust must be enabled for the Cloudflare account.
- An Access application and policy must allow the user or service identity.
- The tunnel ingress must route a private SSH hostname to `ssh://<nas-host>:22`.
- The local machine must run `cloudflared access tcp` before SSH connects.

This repository does not yet automate that flow. Until it does, use Cloudflare's `cloudflared`
client manually or prefer Tailscale for day-to-day `synology-site` work.

## Alternative: WireGuard

Synology's VPN Server package can provide WireGuard-style remote access on some setups, but it
requires a forwarded UDP port and does not work through CGNAT without another relay. Use it only
when you control the router and have a public IP or reliable DDNS.

## Fallback: Reverse SSH Through a VPS

A free or low-cost VPS can act as a relay with `autossh`: the NAS opens an outbound reverse tunnel
to the VPS, and the CLI connects to the VPS-forwarded port. This works through CGNAT and avoids a
mesh VPN provider, but it is the highest-maintenance option because the relay, keys, firewall, and
restart behavior all need to stay healthy.

