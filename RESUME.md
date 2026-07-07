# RESUME — Status Across All Phases

Updated after completing as much of `TODO.md` as possible without new infrastructure/accounts.
Every item below was validated with tests or real smoke-testing where the tooling allowed it.

## TL;DR

- **Phases 1–8, Phase 10, and Phase 12 are done**. Phase 9 and Phase 11 are partially done in
  `TODO.md`; the next substantive unfinished work is health-gated restart and deeper
  Cloudflare Access/security-hardening.
- 259 tests pass, `ruff check` is clean, and the real `.env` on this machine still resolves to
  exactly one workspace (`default`) — confirming zero behavior change for the existing
  single-NAS, single-Cloudflare-account setup throughout all of this.
- **Corrected an earlier finding**: I'd previously reported "no reliable Packagist/npm registry
  access" in this sandbox. That was half wrong — **npm registry access works fine directly**; a
  local `~/.npm` cache-permission issue (root-owned files) was silently breaking Node package
  installs, not a network restriction. Working around it with a scratch `npm_config_cache`
  directory let me *actually* smoke-test FastAPI (`uvicorn`), Next.js (`create-next-app`, real
  build, real serve), and the Vite scaffolding commands Laravel's decoupled-SPA frontends use —
  all confirmed correct for real, not just plausible-looking. **Composer/Packagist access still
  doesn't work** even with the same kind of workaround, so Laravel's Breeze-dependent steps
  remain author-only (unverified against a real build).

## What's done and verified this pass

### Phase 6 — More backends
- **FastAPI** (`--framework fastapi`): hand-templated (no official installer exists for FastAPI,
  unlike Laravel), `/health` + `/db-health` (SQLAlchemy/MariaDB, same pattern as Flask), served by
  `gunicorn` + `uvicorn.workers.UvicornWorker`. **Actually ran the generated app under real
  `uvicorn`** in this environment and hit `/`, `/health`, and a real SQLAlchemy
  connection-failure path on `/db-health` (correct 503) — genuine runtime validation, not just
  template rendering.
- **Next.js** (`--framework nextjs`): like Laravel, runs the real `npx create-next-app@latest`
  installer at build time. **Fully smoke-tested against the real npm registry**: ran the exact
  flags (`--js --no-tailwind --no-eslint --no-src-dir --app --import-alias "@/*" --use-npm
  --no-git --no-agents-md`), added the `/health` and `/db-health` (via `mysql2`) App Router route
  handlers, ran a real `npm run build`, started it with `npm start` (confirmed it respects
  `PORT`), and hit both endpoints for real — including a genuine `mysql2` connection-failure
  path returning a correct 503.
- Decided (twice, formally) that neither Flask nor FastAPI need a `--python-server` axis the way
  Laravel needed `--php-server`: both already default straight to a real multi-worker production
  server (`gunicorn`), so there's no dev-server trap to offer a flag against.

### Phase 7 — Laravel production completeness
- `--with-redis`: independent Redis container (works alongside or instead of `--with-db`),
  switches `SESSION_DRIVER`/`CACHE_STORE`/`QUEUE_CONNECTION` to `redis`, adds the PHP `redis`
  extension. No password, not published to a host port (same posture as MariaDB).
- `--with-queue`: queue worker container (`php artisan queue:work`) reusing the app's own
  build/image with a different `command:`. Requires `--with-redis` (a worker needs a real queue
  backend). Works across both `--php-server` modes and alongside `--with-db`.
- `--with-scheduler`: container looping `php artisan schedule:run` every 60s (Laravel has no
  built-in scheduler daemon). Unlike `--with-queue`, doesn't require `--with-db`/`--with-redis` —
  a fresh install has no scheduled tasks, so it's harmless until the app registers some.
- All three are independently combinable with each other, with `--with-db`, and across both
  `--php-server` modes — verified with dedicated compose-topology tests for every combination.

### Phase 8 — Popular self-hosted app bootstraps
- `bootstrap-uptime-kuma`: turned out much simpler than `bootstrap-supabase` in practice — Uptime
  Kuma ships as a single official image with no secrets to regenerate (its own first-run setup
  wizard creates the admin account), so there's no repo to clone or `.env` to rewrite. Reuses the
  same port allocator `create` uses; doesn't wire up Cloudflare automatically (same as
  `bootstrap-supabase` — prints the `cloudflare-route` follow-up command instead).
- `bootstrap-n8n`, `bootstrap-vaultwarden`, and `bootstrap-umami` are built. Their generated
  Compose/env deployment path is shared through `commands/bootstrap_compose.py`: port selection,
  overwrite handling, upload, local secret persistence, startup, and container-running checks.
  Supabase's clone-and-patch flow remains separate because it has materially different behavior.

### Phase 12 — Remote access to the home NAS
- Tailscale remains the recommended path and is now an explicit opt-in SSH override:
  `TAILSCALE_ENABLED=false` by default, with `TAILSCALE_NAS_HOST` used only for the SSH
  connection when enabled. `NAS_HOST` and `LOCAL_BASE_URL_HOST` remain available for LAN/service
  routing.
- Cloudflare Access SSH is implemented as an optional transport: `SSH_ACCESS_HOSTNAME` makes the
  CLI start `cloudflared access tcp --hostname ... --url localhost:<port>` before opening SSH.
  `SSH_ACCESS_LOCAL_PORT=0` picks a free local port per run. The Cloudflare Access app/tunnel
  route still has to be configured in Cloudflare first.
- WireGuard and reverse-SSH-through-a-VPS are documented as fallbacks in
  `docs/remote-nas-access.md`, with their CGNAT/maintenance constraints called out.

### Phase 10 — Observability, backups, and notifications
- `synology-site backup-plan <domain>` generates a MariaDB dump script, `backup.env.example`,
  cron example, and Synology Task Scheduler command for `--with-db` sites. S3-compatible upload
  is supported by the generated script but real verification still needs user-provided bucket
  credentials.
- `NOTIFY_WEBHOOK_URL` and `NOTIFY_WEBHOOK_EVENTS` add optional Slack/Discord-compatible
  deploy/update success/failure notifications. They default off, and webhook delivery failures
  warn without changing the command result.
- `synology-site health [--all-targets]` remains the simple aggregated health dashboard.

## What's still unverified against real infrastructure (unchanged from before)

### 1. Laravel's Composer/Breeze-dependent Dockerfile steps
`composer require laravel/breeze --dev`, `php artisan breeze:install vue|react|api
--no-interaction` are still author-only — Packagist access doesn't work in this sandbox even
with the same cache-workaround trick that fixed npm. The **pure-npm half of the decoupled-SPA
frontends is now confirmed real** (see above): `npm create vite@latest . -- --template vue|react`
scaffolds correctly, and `npm run build` on it only failed in this specific sandbox because its
local Node binary (20.12.2) predates latest Vite's minimum (20.19+) — not a flaw in the Docker
recipe, which pulls `node:20-alpine`'s latest 20.x patch and would satisfy that minimum for real.
Angular CLI (`ng new`) was not re-verified. Failure mode for anything still wrong is a loud build
error in that one `RUN` line, not a silently broken site.

**How to verify:** deploy one Laravel frontend mode for real on a throwaway subdomain —
```bash
synology-site create test.yourdomain.dev --framework laravel --frontend livewire
synology-site create test.yourdomain.dev --framework laravel --frontend inertia-vue
synology-site create test.yourdomain.dev --framework laravel --frontend vue --php-server fpm-nginx
```

### 2. Multi-NAS wiring, against a real second NAS
Unit-tested with a fake SSH client capturing resolved connection parameters, but never opened
against an actual second machine (none available, and none should be required to build this).

**How to verify** once you have a second host:
```bash
mkdir -p secrets/testnas
cat > secrets/testnas/nas.env <<'EOF'
NAS_HOST=<second host IP>
NAS_SSH_KEY_PATH=<path to a key that can reach it>
EOF
synology-site workspaces
synology-site create test.yourdomain.dev --workspace testnas --dry-run
```

## What was deliberately not built (and why) — carried forward

- **Fully decoupled two-hostname SPA routing** (separate subdomains for API vs. frontend) wasn't
  built — the nginx-internal-path-routing approach achieves the same practical outcome without
  new Cloudflare DNS/tunnel routes, at the cost of frontend/backend always scaling together.
- **Target/account as separate top-level `targets/`/`accounts/` directories** (many-to-many
  pairing) wasn't built — a single `secrets/<name>/` folder holding either or both of
  `cloudflare.env`/`nas.env` covers every case described with less new surface area.
- **Rewiring `system_type` into `docker_remote.py`**: the only Synology-specific code is two
  fallback docker-binary paths that are already harmless no-ops on generic Linux, so there's
  nothing for `system_type` to change yet — kept as validated metadata for a real future
  Synology-only feature to branch on.

## Remaining phases (not started)

- **Phase 9 remainder**: health-gated zero-downtime restarts.
- **Phase 11 remainder**: Cloudflare Access/Zero Trust API integration for staging/admin routes.

See `TODO.md` for the full per-item breakdown and status of everything above.

## Validation performed this pass

- `pytest`: 259/259 passing.
- `ruff check .`: clean.
- Real runtime smoke tests (not just template rendering): FastAPI app under `uvicorn` (index,
  health, and a genuine DB-connection-failure path); Next.js app built and served with `npm run
  build`/`npm start`, hit for real including its `mysql2` failure path; `npm create vite@latest`
  scaffolding for both `vue` and `react` templates.
- Loaded the real local `.env` through `load_config()` — still resolves to exactly the `default`
  workspace, confirming no behavior change to the existing setup throughout this entire pass.
- Current working tree changes are intentionally uncommitted.
