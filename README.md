# Synology Site Deployer

Synology Site Deployer is a local Python CLI for deploying containerized apps to a Synology NAS over SSH. `create` scaffolds and deploys a new Flask or Laravel app from scratch (optionally with a MariaDB container); `deploy` uploads and starts an existing project's own Compose file for any framework — it doesn't generate app code, so it isn't limited to what `create` supports. `bootstrap-supabase` stands up Supabase's self-hosted stack. `cloudflare-route` wires a Cloudflare Tunnel route to a fixed port directly. All of them can configure Cloudflare Tunnel routes + DNS via the Cloudflare API when credentials are present, across multiple Cloudflare accounts/domains via workspaces (see below).

The tool is generic. Domains, NAS hosts, Docker paths, Cloudflare zones, tunnel names, and ports come from `.env`, CLI options, or validated defaults.

## Developer

Developed by Pedro Veloso.

Contact: `pedro@veloso.dev`

## What It Does

- `create`: scaffolds and deploys a new Flask or Laravel app (`--framework`) to a Synology NAS using Docker Compose, optionally with a MariaDB 11 container (private network + persistent volume), a non-secret project README, `docs/DATABASE.md`, and `/health`/`/db-health` checks. `--frontend` pairs a Vue/React/Angular/Inertia/Livewire frontend with the Laravel backend (see "Backend + Frontend Roadmap").
- `deploy`: uploads an existing project's own Compose file (+ optional `.env`) and starts it — any framework, since it doesn't generate app code. `docker compose pull` with a `--build` fallback. Works with a fixed reverse-proxy port (Traefik, etc., no port allocation/Cloudflare/health-check) or a standalone published port (same behavior as `create`).
- `bootstrap-supabase`: clones and starts Supabase's self-hosted stack, regenerating every security-critical secret properly (including correctly HS256-signed `ANON_KEY`/`SERVICE_ROLE_KEY` JWTs, not random strings), and can upload a Traefik-label override alongside it.
- `cloudflare-route`: points one hostname at a fixed port via the Cloudflare API directly, no NAS/SSH interaction — for reverse-proxy setups where many hostnames share one port.
- `workspaces`: lists configured Cloudflare accounts/NAS targets and flags copy-paste credential mistakes (e.g. a `CF_TUNNEL_ID` accidentally reused across workspaces).
- `list --all-targets`: aggregates sites across every configured NAS target instead of just the default one.
- Finds a free local NAS port when one is needed.
- Prints manual Cloudflare Tunnel setup instructions if API credentials are missing; otherwise creates/updates the tunnel ingress rule and proxied DNS record automatically.

## What It Does Not Do

- It does not expose Synology DSM, SSH, or MariaDB/Postgres to the public internet.
- It does not require the Synology DSM database package.
- It does not generate application code for frameworks other than Flask/Laravel (`create`) — but `deploy` can start any already-built project regardless of framework.
- It does not commit `.env`, tokens, generated passwords, or database credentials.

## Requirements

- Python 3.11 or newer
- SSH access to the NAS
- Synology Container Manager
- Docker and Docker Compose on the NAS
- A Docker root path such as `/volume1/docker`
- Optional: Cloudflare domain and Cloudflare Tunnel running on the NAS

On Synology, Docker may be available at `/usr/local/bin/docker` instead of the default shell `PATH`. The tool detects this path automatically. If the SSH user can only access Docker through `sudo`, the tool can use `sudo -S` with the configured SSH password.

## Install For Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
synology-site --help
```

On some Python 3.13 environments, editable installs may be affected by hidden `.pth` handling. A normal local install also works:

```bash
pip install ".[dev]"
```

## Configure

Copy `.env.example` to `.env` and edit it:

```bash
cp .env.example .env
```

Important settings:

```env
NAS_HOST=192.168.1.100
NAS_PORT=22
NAS_USER=your_synology_username
NAS_DOCKER_ROOT=/volume1/docker
LOCAL_BASE_URL_HOST=192.168.1.100
DEFAULT_START_PORT=5050
DEFAULT_END_PORT=5999
DEFAULT_SITE_DOMAIN=example.com
CF_ZONE_DOMAIN=example.com
CF_TUNNEL_NAME=my-nas-tunnel
DB_MODE=none
```

Use `NAS_SSH_KEY_PATH` when possible. If no key or password is set, the CLI prompts securely.

`DEFAULT_SITE_DOMAIN` lets you pass a bare subdomain label to `create`/`deploy` instead of a full domain: a domain argument with no dot in it (e.g. `app`) is expanded to `<name>.DEFAULT_SITE_DOMAIN` (e.g. `app.example.com`). Anything that already contains a dot (e.g. `demo.example.com`) is used as-is. Leave it empty to always require a full domain.

For Synology systems where Docker requires elevated access, the SSH user should be allowed to run Docker through DSM permissions or `sudo`. The tool does not print the configured SSH password.

## Cloudflare Setup

Cloudflare is optional for local deployment. For public access through Cloudflare Tunnel:

- The domain must be managed in Cloudflare.
- A tunnel must already exist.
- The tunnel connector should be running on the NAS.
- `CF_ZONE_DOMAIN` must match the Cloudflare zone, including domains such as `company.com.au`.
- API credentials are optional.

If these values are complete, API automation is attempted:

```env
CF_API_TOKEN=
CF_ACCOUNT_ID=
CF_ZONE_ID=
CF_ZONE_DOMAIN=example.com
CF_TUNNEL_ID=
```

If they are missing, the CLI prints manual instructions.

## Workspaces (Multiple Cloudflare Accounts, Multiple NAS Targets)

The domain, tunnel, Cloudflare *account*, or even the physical **NAS** used for a given site can
all differ per site. The root `.env`'s `CF_*`/`NAS_*` blocks are the **default workspace**. Any
additional workspace is a folder under `secrets/`, named after the workspace, holding *either or
both* of two optional files:

```text
secrets/
  acmeco/
    cloudflare.env   # different Cloudflare account/domain/tunnel
    nas.env          # different physical NAS (optional)
```

```env
# secrets/acmeco/cloudflare.env -- same keys as the root .env's CF_* block
CF_API_TOKEN=
CF_ACCOUNT_ID=
CF_ZONE_ID=
CF_ZONE_DOMAIN=acmeco.dev
CF_TUNNEL_ID=
CF_TUNNEL_NAME=acmeco-tunnel
```

```env
# secrets/acmeco/nas.env -- only needed if this workspace deploys to a *different* NAS.
# Any field left out (NAS_USER, NAS_DOCKER_ROOT, ...) inherits the root .env's value, so a
# workspace that only changes the host doesn't need to repeat everything else.
NAS_HOST=203.0.113.5
NAS_SSH_KEY_PATH=/Users/you/.ssh/acmeco_nas_ed25519
SYSTEM_TYPE=synology
```

Most workspaces only need `cloudflare.env` (same NAS, different Cloudflare account/domain — this
was the original use case). A workspace can also define only `nas.env` (same Cloudflare account,
different physical NAS) or both. `secrets/` is already gitignored in full, so workspaces are
added or removed just by adding or removing a folder — there's no separate manifest to keep in
sync, and no limit to how many can exist.

When `create`/`deploy`/`cloudflare-route`/`cloudflare-instructions` run, the domain is matched
against every known workspace's `CF_ZONE_DOMAIN` (longest match wins) to pick the Cloudflare
account, falling back to the default workspace if nothing matches. The **NAS target** is looked
up by that same resolved workspace name — there's no equivalent "domain suffix" signal for which
physical NAS to use, so a workspace without its own `nas.env` just keeps using the default NAS.
Pass `--workspace <name>` to force a specific workspace (both its Cloudflare account and its NAS
target, whichever it defines) instead of relying on domain matching:

```bash
synology-site create app.acmeco.dev --workspace acmeco
```

`SYSTEM_TYPE` (`synology` default, or `generic-linux`) is stored per NAS target for a
non-Synology Docker-over-SSH host (a VPS, a Raspberry Pi, ...). In practice the tool's only
Synology-specific behavior is two extra docker-binary fallback paths tried *after* plain
`docker`/`sudo docker` fail, which are harmless no-ops on any other Linux host — so
`generic-linux` doesn't currently change any behavior. It's there so a future genuinely
Synology-only feature (e.g. DSM Task Scheduler-based autostart) has somewhere to branch on
without a breaking config change later.

### Inspecting Workspaces

```bash
synology-site workspaces
```

Lists every known workspace and what it overrides (Cloudflare account, NAS target, or both), and
runs a "doctor" check for copy-paste credential mistakes — specifically the same `CF_TUNNEL_ID`
or `CF_API_TOKEN` accidentally reused across two workspaces that were meant to be independent
(a tunnel belongs to exactly one Cloudflare account, so a shared `CF_TUNNEL_ID` is essentially
always a mistake). Sharing the same NAS or `CF_ACCOUNT_ID` across workspaces is *not* flagged —
that's the normal, supported multi-account/same-NAS setup.

### Listing Sites Across Every NAS

```bash
synology-site list --all-targets
```

`list` normally shows sites on one NAS target (the default, or `--workspace <name>` for a
specific one). `--all-targets` fans out over every configured target and aggregates the results;
a target that's unreachable is reported inline rather than aborting the whole listing.

## Deploy Flask

```bash
synology-site create demo.example.com
```

This creates a generated Flask app, Dockerfile, Compose file, marker file, and docs under:

```text
/volume1/docker/demo-example-com
```

The public page shows only:

```text
It works
demo.example.com is running successfully.
```

## Deploy Flask With MariaDB

```bash
synology-site create demo.example.com --with-db
```

This adds:

- MariaDB image `mariadb:11`
- Private Docker network
- Persistent Docker volume
- App `.env` on the NAS with permission `600`
- `docs/DATABASE.md` on the NAS with permission `600`
- `/db-health`

MariaDB port `3306` is not published by default. Do not expose MariaDB to the public internet.

## Deploy Laravel

```bash
synology-site create demo.example.com --framework laravel
```

Unlike Flask's scaffold, this doesn't hand-template Laravel's file tree. The generated
`app/Dockerfile` runs the real `composer create-project laravel/laravel` installer at image-build
time, so the NAS needs network access to Packagist during the first `docker compose up -d
--build`. `create` only uploads the Dockerfile, Compose file, `app/.env`, docs, and marker file.
Add `--with-db` for the same MariaDB container topology as Flask, wired into Laravel's `.env`
(`DB_CONNECTION=mysql`); without it, Laravel falls back to its own default `sqlite` connection
(never actually queried, since nothing beyond `/health` runs by default). Add `--with-redis` for
a Redis container (independent of `--with-db` — either, both, or neither), which also switches
`SESSION_DRIVER`/`CACHE_STORE`/`QUEUE_CONNECTION` from `file`/`sync` to `redis` in `app/.env`.
Redis has no password and isn't published to a host port — same "internal-only, relies on
Docker network isolation" posture as MariaDB. Add `--with-queue` for a queue worker container
(`php artisan queue:work`, sharing the app's own build/image, just with a different command) —
requires `--with-redis`, since a worker only makes sense against a real queue backend, not the
default `sync` driver which already runs jobs inline with no worker needed.

```bash
synology-site create demo.example.com --framework laravel --with-redis --with-queue
```

`--php-server` picks how the app is actually served:

- `artisan` (default) — `php artisan serve`, a single process in one container. Simplest, matches
  Flask's one-container-per-site model, fine for personal/low-traffic use. **Not meant for
  production traffic** — Laravel's own docs say so. If you deploy Laravel without
  `--php-server fpm-nginx`, `create` prints a warning recommending it.
- `fpm-nginx` — **the production-recommended option.** PHP-FPM + nginx in two containers
  (`{slug}` running PHP-FPM, `{slug}-web` running nginx and publishing the port), built from the
  same Dockerfile via two build targets (`--target php-fpm` / `--target nginx`). nginx serves
  static assets directly and proxies everything else to PHP-FPM over the container network.
  `create` waits for both containers to report running before considering the deploy successful.

```bash
synology-site create demo.example.com --framework laravel --php-server fpm-nginx --with-db
```

Use this form for any NAS deployment meant to serve real production traffic.

## Deploy An Existing Project (Any Framework)

`create` scaffolds new Flask or Laravel apps (`--framework flask|laravel`). `deploy` is the counterpart for a project that already has its own Dockerfile and Compose file — a Next.js app, a Node API, or anything else with a CI pipeline that builds and pushes an image. It does not generate any application code; it uploads your Compose file (and optional `.env`), then pulls/builds and starts it on the NAS.

```bash
synology-site deploy app.example.com --compose-file ./infra/web/docker-compose.web.yml --env-file ./infra/web/.env
```

This uploads the Compose file and `.env` (permission `600`) to `/volume1/docker/app-example-com`, then runs `docker compose pull` followed by `docker compose up -d` (falling back to `--build` if the pull fails, e.g. before an image has ever been published, or if you use `--no-pull --build` to always build locally).

If the service in your Compose file is fronted by a reverse proxy already running on the NAS (Traefik, Nginx Proxy Manager) and doesn't publish a host port — as with ResiLinked's `infra/web/docker-compose.web.yml`, which joins the shared `supabase_default` network and routes by Traefik `Host()` label — omit `--port`. Cloudflare automation and the health check are both skipped, since routing is handled by the existing proxy/tunnel setup rather than a per-app port.

If the service does publish its own host port, pass `--port` to get the same behavior as `create`: port availability is checked on the NAS, and the Cloudflare tunnel route is configured automatically (or manual instructions are printed) exactly as described above.

```bash
synology-site deploy app.example.com \
  --compose-file ./docker-compose.yml \
  --port 5060 \
  --container-name my-app \
  --health-path /health
```

Options:

- `--compose-file PATH` (required) — local Compose file to upload
- `--env-file PATH` — local `.env` to upload alongside it (uploaded as `.env`, `chmod 600`)
- `--remote-compose-name NAME` — filename to use on the NAS (default `docker-compose.yml`)
- `--source-dir PATH` — upload this whole local directory instead of just `--compose-file`, and build on the NAS. See "Building From Full Source" below.
- `--port N` — enables port allocation, health checks, and Cloudflare routing (omit for reverse-proxy-fronted services)
- `--container-name NAME` — verify this container is running after startup
- `--pull/--no-pull`, `--build/--no-build` — default is `--pull` (build only as a pull-failure fallback)
- `--health-path PATH` — requires `--port`
- `--force`, `--dry-run`, `--strict-cloudflare` — same meaning as on `create`

Sites deployed this way show up in `synology-site list` and work with `start`/`stop`/`remove`/`set-autostart` like any other site.

### Building From Full Source (`--source-dir`)

`--compose-file`/`--pull`/`--build` alone assume the Compose file's own `build.context` is self-contained (or that you're pulling a prebuilt image). That's not true for a monorepo where the build context needs sibling packages — e.g. `context: ../..` in a compose file that lives under `infra/`. For that case, `--source-dir` uploads the *whole* local directory tree (not just the one Compose file) and builds directly on the NAS, with the Compose file staying at the same path relative to the uploaded root that it has locally — so a relative `context: ../..` resolves the same way it would on your machine.

```bash
synology-site deploy app.example.com \
  --compose-file ./infra/web/docker-compose.web.yml \
  --source-dir . \
  --env-file ./infra/web/.env
```

`--compose-file` must be inside `--source-dir`. The upload respects `--source-dir`'s own `.dockerignore` (bare names like `node_modules`, `.git`, `*.md` — not full gitignore-style precedence/negation, just the common case), pruning ignored directories before walking into them rather than filtering after — so a large `node_modules` never gets traversed at all. `.env` is **always** excluded from this bulk upload regardless of `.dockerignore`, even if one happens to exist in the tree being uploaded — it would otherwise land with default SFTP permissions instead of the `chmod 600` the separate `--env-file` upload gets, and could contain unrelated local secrets. Passing `--source-dir` implies `--build --no-pull` (there's nothing to pull that this upload would produce).

This exists specifically because a registry-based deploy (CI builds → GHCR → `deploy --pull`) isn't always available — e.g. the images are on a private registry the NAS has no credentials for. `--source-dir` builds the exact same Dockerfile locally on the NAS instead, no registry access needed at all.

## Automatic Cloudflare Route For A Fixed Port

`create`/`deploy --port` each allocate a fresh, unique port per app — the right model for standalone services. It's the wrong model for a reverse-proxy setup: Traefik (or Nginx Proxy Manager) binds one fixed port (typically 80) and routes many hostnames to it internally by `Host()` header, so several hostnames all need to point at that *same* port, not a freshly allocated one.

`cloudflare-route` configures the Cloudflare Tunnel ingress rule + proxied DNS record for one hostname directly, with no NAS/SSH interaction at all — just the Cloudflare API:

```bash
synology-site cloudflare-route app.example.com --port 80
synology-site cloudflare-route api.example.com --port 80
synology-site cloudflare-route studio.example.com --port 80
```

Each call routes that hostname to `http://LOCAL_BASE_URL_HOST:80` (i.e. Traefik), leaving the others untouched. Use `--service-host` to point at a different host than `LOCAL_BASE_URL_HOST`. Requires the same Cloudflare API credentials as `create`/`deploy`.

## Bootstrapping Self-Hosted Supabase

`bootstrap-supabase` automates standing up [Supabase's self-hosted stack](https://supabase.com/docs/guides/self-hosting/docker) (Postgres, Auth, Storage, Realtime, Kong, Studio) on the NAS:

```bash
synology-site bootstrap-supabase
```

This clones Supabase's own `docker/` folder (not vendored here — they maintain it) into `NAS_DOCKER_ROOT/supabase`, then regenerates the security-critical values in its `.env` rather than leaving Supabase's insecure example defaults in place:

- `POSTGRES_PASSWORD`, `DASHBOARD_PASSWORD`, `SECRET_KEY_BASE`, `VAULT_ENC_KEY` — random values
- `JWT_SECRET` — random value
- `ANON_KEY`/`SERVICE_ROLE_KEY` — **properly signed HS256 JWTs** carrying the `anon`/`service_role` claims Kong/GoTrue/PostgREST check, signed with the generated `JWT_SECRET` (not random strings — Supabase auth silently breaks otherwise)

Everything else in Supabase's `.env.example` (SMTP, analytics, pooler settings, etc.) is left as shipped. The final `.env` — with every secret above in plaintext — is written locally to `secrets/supabase.env` (never uploaded anywhere but the NAS and never printed to the terminal); keep it safe and never commit it. Then `docker compose up -d` brings the stack up on the `supabase_default` network that a reverse proxy and any apps needing Postgres/Auth/Storage are expected to join.

Two gotchas it works around, discovered deploying this for real on a Synology DS1525+:

- Git doesn't track empty directories, and Supabase's `docker/volumes/storage` and `docker/volumes/db/data` are empty in their repo (unlike sibling volume dirs, which hold real config/SQL files) — the clone silently omits them, so Docker's bind mount fails on first `up -d` unless something `mkdir -p`s them first.
- `POSTGRES_PORT` defaults to Supabase's own `5432`, which commonly collides with a NAS's own native services (e.g. a Synology package's bundled Postgres already bound to `127.0.0.1:5432`) — so it defaults to `5433` instead. **This isn't just the host-published port** — it also sets Postgres's actual internal listening port via `PGPORT` (Supabase's own `docker-compose.yml` threads the same variable through both), so anything else on the `supabase_default` network connecting to Postgres by container name must use this same port, not the Postgres-default `5432`.

Options:

- `--project-dir-name NAME` (default `supabase`) — NAS folder name under `NAS_DOCKER_ROOT`
- `--dashboard-username NAME` (default `supabase`) — Studio dashboard login
- `--postgres-port N` (default `5433`) — host-published Postgres port; override if `5433` is also taken
- `--traefik-override PATH` — a local `docker-compose.override.yml` adding Traefik labels to Supabase's `kong`/`studio` services, uploaded into the project directory before startup. **Note:** Supabase's own `.env` sets `COMPOSE_FILE=docker-compose.yml`, which disables Compose's normal override auto-discovery — when this option is given, the command passes `-f docker-compose.yml -f docker-compose.override.yml` explicitly to `up -d` rather than relying on it.
- `--force` — tear down (`docker compose down` + `sudo rm -rf`, since Postgres writes its data directory as a container UID the SSH user can't otherwise remove) and recreate an existing install
- `--dry-run`

## Manual Cloudflare Route

```bash
synology-site cloudflare-instructions demo.example.com --port 5051
```

For nested domains, the subdomain is calculated from `CF_ZONE_DOMAIN`. For example:

```text
app.client.example.com + example.com -> app.client
tools.company.com.au + company.com.au -> tools
```

## Error 1033

If Cloudflare Error 1033 appears, the tunnel DNS record exists but Cloudflare cannot resolve the tunnel connection.

Check the NAS:

```bash
sudo docker ps
sudo docker ps -a
```

If the tunnel container is stopped:

```bash
sudo docker start cloudflared
```

If the container has a random name:

```bash
sudo docker stop clever_carver
sudo docker rename clever_carver cloudflared
sudo docker start cloudflared
sudo docker update --restart unless-stopped cloudflared
```

Or run:

```bash
synology-site tunnel-fix-autostart
```

## Operations

```bash
synology-site check-nas
synology-site list
synology-site list --all-targets
synology-site workspaces
synology-site start demo.example.com
synology-site stop demo.example.com
synology-site set-autostart demo.example.com
synology-site remove demo.example.com
```

Remove keeps project files and volumes by default. Use explicit flags for destructive cleanup:

```bash
synology-site remove demo.example.com --delete-files
synology-site remove demo.example.com --delete-volumes
```

## Docker Commands On The NAS

```bash
docker ps
docker logs demo-example-com
cd /volume1/docker/demo-example-com
docker compose restart
docker compose down
docker compose up -d
```

If Docker is only available through Synology's full path or `sudo`, use:

```bash
/usr/local/bin/docker ps
sudo /usr/local/bin/docker ps
```

## Database Access And Backup

Read database credentials on the NAS:

```bash
cat /volume1/docker/demo-example-com/docs/DATABASE.md
```

Back up MariaDB:

```bash
docker exec demo-example-com-db mariadb-dump -uroot -p demo_example_com > demo_example_com_backup.sql
```

## Rebooting The NAS

Containers use `restart: unless-stopped`. Before rebooting, confirm important containers are running:

```bash
docker ps
```

After reboot, check:

```bash
docker ps
curl http://LOCAL_BASE_URL_HOST:PORT/health
```

## Backend + Frontend Roadmap

`create`'s scaffold registry (code generation from templates) now contains two backends:

```python
FRAMEWORKS = {
    "flask": FlaskScaffold(),
    "laravel": LaravelScaffold(),
}
```

`--framework laravel` doesn't hand-template Laravel's file tree the way Flask's scaffold does —
that would drift from real `laravel/laravel` releases. Instead, the generated `app/Dockerfile`
runs the real installer at image-build time (`composer create-project laravel/laravel`), and
`create` only uploads the wrapper files (Dockerfile, Compose file, `.env`, docs, marker).
`--php-server` picks the serving model: `artisan` (default, single process, fine for
personal/low-traffic use) or `fpm-nginx` (production-grade PHP-FPM + nginx, two containers —
see "Deploy Laravel" above). `create` recommends `fpm-nginx` whenever it deploys Laravel without
it.

`create` also accepts `--frontend`, for pairing a frontend framework with the Laravel backend
(Flask has no frontend integration story, and `--frontend` other than `none` is rejected for it).
`none` is the default (no-op, works with either backend). All other values are implemented:

- `livewire` — PHP-driven reactivity via `composer require livewire/livewire`, no separate JS
  framework or build step, single container. Works with either `--php-server`.
- `inertia-vue` / `inertia-react` — installed via Laravel Breeze's official installer
  (`composer require laravel/breeze --dev && php artisan breeze:install vue|react
  --no-interaction`), built into the image (`npm ci && npm run build`), single container. Works
  with either `--php-server`.
- `vue` / `react` / `angular` — a fully decoupled SPA: an independently-scaffolded frontend (Vite
  for vue/react, Angular CLI for angular) built in its own Docker stage, plus a Laravel API
  backend (Breeze's `api` stack, Sanctum-ready). Both are served through **one** nginx container
  on the site's usual published port — nginx serves the SPA's static build and proxies
  `/api`, `/health`, `/db-health` to PHP-FPM — so this needs no new Cloudflare route, DNS record,
  or second hostname. **Requires `--php-server fpm-nginx`** (artisan's dev server has no
  static/proxy split); `create` rejects the combination otherwise. This is also the only path to
  Angular, since Angular has no Inertia adapter.

```bash
synology-site create demo.example.com --framework laravel --frontend livewire
synology-site create demo.example.com --framework laravel --frontend inertia-vue
synology-site create demo.example.com --framework laravel --frontend vue --php-server fpm-nginx
```

**Caveat:** the Composer/Breeze/Vite/Angular CLI commands baked into these Dockerfiles are
authored from documented, current usage but have not been exercised against a live
`docker compose up -d --build` (this environment has no outbound access to Packagist/npm
registries reliably enough to verify a full multi-stage build). If a specific version's exact
non-interactive flags have moved on, the failure mode is a loud build error in that `RUN` step,
not a silently broken site — the fix is a one-line adjustment to the relevant `app/Dockerfile`
line. Treat the first deploy of any of `livewire`/`inertia-vue`/`inertia-react`/`vue`/`react`/
`angular` as a smoke test.

See `docs/laravel-scaffold-options.md` for the full design rationale and phased rollout plan.
This doesn't limit what can be *deployed*, though — `deploy` already starts any project with its
own Dockerfile/Compose file regardless of framework, since it uploads an existing Compose file
rather than generating one.

## Testing

```bash
pytest
ruff check .
synology-site --help
```

Tests mock SSH, Docker commands, Cloudflare API calls, and HTTP health checks. They do not require real Synology access.

## Commit And Push Workflow

For functional changes:

```bash
pytest
ruff check .
git status
git add .
git commit -m "Clear meaningful commit message"
git push
```

## License

Synology Site Deployer is released under the MIT License.

It is free to use, copy, modify, merge, publish, distribute, sublicense, and sell copies, subject to the license terms. The software is provided without warranties of any kind. See [LICENSE](LICENSE).
