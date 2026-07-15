# API-Only / Non-Indexed Routes

Recipe for a hostname that serves an API (JSON, no human-facing pages) and should never show up
in search results. Rather than every project's app code implementing its own robots handling,
add two Traefik labels alongside the usual routing labels in that project's own Compose file:

```yaml
labels:
  - traefik.enable=true
  - traefik.http.routers.<router>.rule=Host(`api.example.com`)
  - traefik.http.services.<router>.loadbalancer.server.port=<port>
  - traefik.http.routers.<router>.middlewares=<router>-noindex
  - traefik.http.middlewares.<router>-noindex.headers.customresponseheaders.X-Robots-Tag=noindex, nofollow
```

This sets `X-Robots-Tag: noindex, nofollow` on every response through Traefik, which is the
header-based equivalent of a page's `<meta name="robots" content="noindex">` and works for
non-HTML responses (JSON, etc.) where a meta tag isn't possible. `robots.txt` is a separate,
weaker signal (advisory, crawlers can ignore it) — this header is what actually keeps compliant
crawlers from indexing the route.

First used by `au-address-lookup`'s `addressr-gateway` (`addr.systemsnotsilos.com`) — see that
repo's `docker-compose.yml`.
