# Traefik + Let's Encrypt Ingress

This is the Cloudflare Tunnel alternative for users who want a conventional reverse proxy on the
NAS with public DNS pointing at their home IP.

Use this only when you have:

- A public IP or working DDNS hostname
- Router port forwards for TCP `80` and `443` to the NAS
- A firewall policy that allows those ports
- A domain where you can create DNS records

If your ISP uses CGNAT, inbound Traefik will not work without another relay. Use Tailscale,
Cloudflare Tunnel, or the reverse-SSH fallback in `docs/remote-nas-access.md` instead.

## Compose

Create a Traefik project on the NAS, for example under `/volume1/docker/traefik`:

```yaml
services:
  traefik:
    image: traefik:v3.1
    container_name: traefik
    restart: unless-stopped
    command:
      - --api.dashboard=false
      - --providers.docker=true
      - --providers.docker.exposedbydefault=false
      - --entrypoints.web.address=:80
      - --entrypoints.websecure.address=:443
      - --certificatesresolvers.letsencrypt.acme.email=you@example.com
      - --certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json
      - --certificatesresolvers.letsencrypt.acme.httpchallenge=true
      - --certificatesresolvers.letsencrypt.acme.httpchallenge.entrypoint=web
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - traefik-letsencrypt:/letsencrypt
    networks:
      - proxy

networks:
  proxy:
    name: proxy

volumes:
  traefik-letsencrypt:
```

Start it:

```bash
docker compose up -d
```

## Deploying Apps Behind Traefik

Your app Compose file should join the same external `proxy` network and use Traefik labels:

```yaml
services:
  web:
    image: ghcr.io/your-org/your-app:main
    container_name: your-app
    restart: unless-stopped
    networks:
      - proxy
    labels:
      - traefik.enable=true
      - traefik.http.routers.your-app.rule=Host(`app.example.com`)
      - traefik.http.routers.your-app.entrypoints=websecure
      - traefik.http.routers.your-app.tls.certresolver=letsencrypt
      - traefik.http.services.your-app.loadbalancer.server.port=3000

networks:
  proxy:
    external: true
```

Deploy without `--port`, because Traefik owns ports `80` and `443`:

```bash
synology-site deploy app.example.com \
  --compose-file ./docker-compose.traefik.yml \
  --container-name your-app
```

When `--port` is omitted, `synology-site` skips Cloudflare route automation and per-app port
allocation. Traefik handles hostname routing by Docker labels.

## DNS

Point `app.example.com` at your home public IP or DDNS hostname. If your IP changes often, run a
DDNS client on the router or NAS.

## Operational Notes

- Keep Traefik and app containers on the shared `proxy` network.
- Do not expose app containers directly with host ports unless you have a specific reason.
- Back up the `traefik-letsencrypt` volume; it contains ACME account and certificate state.
- Use Cloudflare Tunnel instead when you cannot open inbound ports.
