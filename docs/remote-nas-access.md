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
7. Set `TAILSCALE_ENABLED=true` and `TAILSCALE_NAS_HOST` to the NAS's Tailscale address.

`TAILSCALE_ENABLED` is off by default. When enabled, only the SSH connection uses
`TAILSCALE_NAS_HOST`; `LOCAL_BASE_URL_HOST` remains the address that health checks and Cloudflare
Tunnel service URLs use to reach containers on the NAS.

For the default workspace:

```env
NAS_HOST=192.168.1.100
NAS_PORT=22
TAILSCALE_ENABLED=true
TAILSCALE_NAS_HOST=100.x.y.z
```

For a workspace-specific NAS:

```text
secrets/
  remote-nas/
    nas.env
```

```env
NAS_HOST=192.168.1.100
NAS_PORT=22
TAILSCALE_ENABLED=true
TAILSCALE_NAS_HOST=100.x.y.z
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
- The local machine must have the `cloudflared` CLI installed and authenticated.

`synology-site` can start the local `cloudflared access tcp` proxy automatically before opening
SSH. Configure a private SSH hostname in Cloudflare Access first, then opt in:

```env
SSH_ACCESS_HOSTNAME=nas-ssh.example.com
SSH_ACCESS_LOCAL_PORT=0
```

`SSH_ACCESS_LOCAL_PORT=0` asks the CLI to pick a free local port each run. Set a fixed value, such
as `9210`, only if you need predictable local firewall or audit rules.

For a workspace-specific NAS:

```env
NAS_HOST=192.168.1.100
NAS_PORT=22
SSH_ACCESS_HOSTNAME=nas-ssh.example.com
SSH_ACCESS_LOCAL_PORT=0
SYSTEM_TYPE=synology
```

When this is configured, normal SSH still uses the same DSM username/key/password settings. The
only transport change is that the SSH client connects to the local `cloudflared` proxy instead of
directly to `NAS_HOST` or `TAILSCALE_NAS_HOST`.

## Alternative: WireGuard

Synology's VPN Server package can provide WireGuard-style remote access on some setups, but it
requires a forwarded UDP port and does not work through CGNAT without another relay. Use it only
when you control the router and have a public IP or reliable DDNS.

## Fallback: Reverse SSH Through a VPS

A free or low-cost VPS can act as a relay with `autossh`: the NAS opens an outbound reverse tunnel
to the VPS, and the CLI connects to the VPS-forwarded port. This works through CGNAT and avoids a
mesh VPN provider, but it is the highest-maintenance option because the relay, keys, firewall, and
restart behavior all need to stay healthy.
