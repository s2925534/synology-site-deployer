# TODO

Status tracker for the multi-workspace Cloudflare + Laravel backend work, organized by phase.

Status labels: `[Done]` · `[Partial]` (partially done / in progress) · `[Planned]` (not started)

---

## Phase 1 — Multi-Workspace Cloudflare (different domain/tunnel/account, same NAS)

- [Done] `CloudflareAccount` dataclass + `secrets/<name>/cloudflare.env` directory-scan discovery (`cloudflare/workspace.py`)
- [Done] `Settings.resolve_cloudflare(domain, workspace=...)` — longest zone-domain-suffix match, explicit override, default-workspace fallback
- [Done] `cloudflare/api.py` refactored to operate on a resolved `CloudflareAccount` instead of global `Settings`
- [Done] `--workspace` flag on `create`, `deploy`, `cloudflare-route`, `cloudflare-instructions`
- [Done] Tests: workspace discovery, resolution, explicit-override error handling, malformed workspace file handling
- [Done] README: "Multiple Cloudflare Accounts / Domains (Workspaces)" section + `.env.example` pointer

## Phase 2 — Laravel Backend Option

- [Done] `LaravelScaffold` — Dockerfile runs the real `composer create-project laravel/laravel` installer at build time instead of hand-templating Laravel's file tree
- [Done] Health (`/health`) and DB health (`/db-health`) routes injected via `routes-extra.php` append
- [Done] MariaDB container topology reused from Flask (shared `compose.yml.j2`, generalized with `internal_port`)
- [Done] Registered in `FRAMEWORKS` (`--framework laravel`) alongside Flask
- [Done] `docs/DATABASE.md` (Laravel-flavored DSN/wording), `docs/README.md`, marker JSON reused/adapted
- [Done] Tests: file list, Dockerfile content, DB-enabled vs sqlite-default `.env`, compose topology
- [Done] README: "Deploy Laravel" section

## Phase 3 — Production-Grade Laravel Serving

- [Done] `--php-server fpm-nginx` — two-container topology (`{slug}` PHP-FPM + `{slug}-web` nginx), one Dockerfile with two build targets
- [Done] nginx config: static assets served directly, `.php` requests proxied to PHP-FPM over the container network
- [Done] `container_names()` added to the scaffold interface so `create_site` confirms however many containers a mode uses (1 for `artisan`, 2 for `fpm-nginx`)
- [Done] Validation: `--php-server` rejected for non-Laravel frameworks, unknown values rejected
- [Done] Production recommendation: `create` warns when Laravel is deployed on `artisan` (single-process, not production-grade) instead of `fpm-nginx`
- [Done] Tests: two-container confirmation, both build targets, network wiring with DB enabled
- [Done] README + `docs/laravel-scaffold-options.md` reconciled with what shipped

## Phase 4 — Frontend Framework Integration

- [Done] `--frontend` accepts `none`/`livewire`/`inertia-vue`/`inertia-react`/`vue`/`react`/`angular` — all implemented, none are stub/"planned" errors anymore
- [Done] `livewire` — `composer require livewire/livewire`, single container, works with either `--php-server`
- [Done] `inertia-vue` / `inertia-react` — Laravel Breeze's official installer (`breeze:install vue|react --no-interaction`), assets built into the image, single container
- [Done] `vue` / `react` / `angular` — decoupled SPA: independently-built frontend (Vite for vue/react, Angular CLI for angular) in its own Docker stage + a Breeze `api`-stack Laravel backend, served through **one** nginx container (static files + `/api` proxy) — requires `--php-server fpm-nginx`
- [Done] Two-origin routing question resolved by construction: nginx does the `/api` vs. static split *inside* the existing one-hostname/one-port topology, so no Cloudflare-level path routing or second subdomain was needed
- [Done] Angular question resolved: cost nothing extra once the above was built, so it shipped alongside vue/react
- [Partial] **Partially build-verified, updated.** Composer/Breeze-dependent steps (`composer require laravel/breeze`, `breeze:install vue|react|api`) are still author-only — Packagist access doesn't work in this environment even with the npm cache workaround below. The pure-npm half is now confirmed for real: `npm create vite@latest . -- --template vue` (and `react`) scaffolds correctly (verified real files + `package.json`) once routed around a local `~/.npm` cache-permission issue via a scratch `npm_config_cache` dir — npm registry access itself works fine, it was never actually blocked. `npm run build` on the scaffolded Vite project then failed in this *specific* sandbox only because its local Node binary (20.12.2) predates latest Vite's minimum (20.19+) — not a flaw in the Docker recipe, which pulls `node:20-alpine`'s latest 20.x patch and would satisfy that minimum in a real build. Angular CLI (`ng new`) was not re-verified. Failure mode for any remaining unverified flag is a loud build error in that one `RUN` line, not a silently broken site. See RESUME.md.

## Phase 5 — Workspace-as-Profile / Multi-NAS / Multi-System

- [Done] "One tunnel per Cloudflare account" — structurally guaranteed: `secrets/<name>/cloudflare.env` has a single `CF_TUNNEL_ID` field per account
- [Done] `NasTarget` dataclass + `secrets/<name>/nas.env` directory-scan discovery (`nas/target.py`), **inheriting** any unset field from the default target (unlike Cloudflare accounts, which are fully self-contained)
- [Done] `Settings.resolve_target(workspace=...)` + `Settings.known_workspace_names`/`validate_workspace()` — a workspace can define `cloudflare.env`, `nas.env`, or both in the same folder; resolving one doesn't require the other to exist (fixed a real gap: a NAS-only workspace used to be wrongly rejected as an "unknown Cloudflare workspace")
- [Done] **Actually wired into the SSH connection** — `create`/`deploy` resolve the target and connect to *its* host/port/user/credentials (via a `dataclasses.replace`d `Settings`, so no existing function signature or test needed to change), not just the default NAS. Verified with tests that capture what host `ssh_factory` was actually called with.
- [Done] `system_type` (`synology`/`generic-linux`) stored + validated per target. Investigated wiring it into `docker_remote.py`'s Synology-specific fallback paths — found those paths are already harmless no-ops on non-Synology hosts (they only activate after plain `docker`/`sudo docker` fail), so no behavior actually depends on this yet. Kept as validated metadata for a real future Synology-only feature to branch on.
- [Done] `synology-site workspaces` — lists every workspace and what it overrides, plus a doctor check for a `CF_TUNNEL_ID`/`CF_API_TOKEN` duplicated across workspaces (almost always a copy-paste mistake); deliberately does *not* flag shared NAS/`CF_ACCOUNT_ID`, since that's the normal supported setup
- [Done] `synology-site list --all-targets` — aggregates sites across every configured NAS target; an unreachable target is reported inline, not fatal to the rest
- [Partial] **Not validated against a real second NAS.** All of the above is covered by unit tests with a fake SSH client capturing the resolved connection parameters — there is no second physical NAS in this environment to confirm an actual SSH session against a different host end-to-end. See RESUME.md.

**Known caveat (not a bug, a constraint to design around):** a single tunnel's connector
(`cloudflared`) can route to services on other hosts, but only if it can reach them on the
network (shared LAN/VPN mesh). If one Cloudflare account's sites end up split across NAS boxes
that are genuinely network-isolated from each other, "one tunnel per account" and "multi-NAS"
pull in different directions for that account.

## Phase 6 — Additional Backend/Runtime Options

Flask + Laravel cover Python/PHP; these are the two most-requested "deploy my app" targets not
yet covered, picked for popularity rather than novelty.

- [Done] `--framework fastapi` — unlike Laravel, FastAPI has no official project installer to run at build time (it's just a library, not a full framework with its own CLI generator), so this hand-templates `app/main.py` the same way Flask's scaffold does, rather than needing Laravel's Dockerfile-driven installer approach. Ships `/health` + `/db-health` (same SQLAlchemy/MariaDB pattern as Flask, works with `--with-db`). Runs on `gunicorn` + `uvicorn.workers.UvicornWorker` — already production-grade by default, so no `--python-server` axis needed (see the decision below). **Actually smoke-tested**, not just template-rendered: ran the generated `main.py` under real `uvicorn` (PyPI access works directly in this environment) and confirmed `/`, `/health`, and a real SQLAlchemy connection-failure path on `/db-health` all return correct responses.
- [Done] `--framework nextjs` — like Laravel, runs the real `npx create-next-app@latest` installer at build time (App Router, JS, no Tailwind/ESLint/AGENTS.md) rather than hand-templating. Ships `/health` + `/db-health` (via `mysql2`, works with `--with-db`). Runs on `npm start` on port 3000. **Fully smoke-tested against the real npm registry**: it turns out npm registry access *does* work directly in this environment (a local `~/.npm` cache-permission issue, not a network block, caused the earlier Laravel/Vite/Angular attempts to fail — worked around here with a scratch `npm_config_cache` dir; Composer/Packagist access still didn't work even after this discovery, so Laravel's recipes remain author-only, see RESUME.md). Ran the exact `create-next-app` flags, added the health/db-health App Router route handlers, `npm run build`, `npm start` (confirmed it respects `PORT`), and hit a real `mysql2` connection-failure path returning a correct 503 — all for real, not just template-rendered.
- [Done] **Decided: no `--python-server` axis for Flask.** Laravel needed the axis because its default `php artisan serve` is an explicitly-documented dev-only single process; Flask's `flask_dockerfile.j2` already runs `gunicorn` (a real pre-fork multi-worker WSGI server) as its only mode, so there's no dev-vs-production serving gap to offer a flag for.
- [Done] **Decided: no `--python-server` axis for FastAPI either**, for the same reason — it defaults straight to `gunicorn`+`uvicorn.workers.UvicornWorker`, never `uvicorn --reload`.

## Phase 7 — Laravel Production Completeness

Arguably a bigger real-world gap than the frontend work: a Laravel app in actual production
almost always needs more than a web container.

- [Done] `--with-redis` alongside `--with-db` (independent of each other — either, both, or neither) — adds a `redis:7-alpine` container, no password, not published to a host port (same posture as MariaDB); switches `SESSION_DRIVER`/`CACHE_STORE`/`QUEUE_CONNECTION` from `file`/`sync` to `redis` in `app/.env` and adds the `redis` PHP extension. Works with every `--php-server`/`--frontend` combination, including alongside `--with-db` simultaneously. Laravel-only (validated, same pattern as `--frontend`/`--php-server`).
- [Done] `--with-queue` — queue worker container (`php artisan queue:work --sleep=3 --tries=3 --max-time=3600`) reusing the app's own build/image (same Dockerfile target, different `command:`), requires `--with-redis`. Works with both `--php-server` modes and alongside `--with-db`.
- [Done] `--with-scheduler` — container looping `php artisan schedule:run --verbose --no-interaction` every 60s via a shell `while true` loop (no cron daemon installed), reusing the app's own build/image. Unlike `--with-queue`, doesn't require `--with-db`/`--with-redis` — a fresh install has no scheduled tasks, so it's a no-op until you register some.

**Phase 7 complete.** All three items (`--with-redis`, `--with-queue`, `--with-scheduler`) shipped, independently combinable with each other and with `--with-db`, across both `--php-server` modes.

## Phase 8 — Popular Self-Hosted App Bootstraps

`bootstrap-supabase` already proves out the pattern (clone the project's own compose file,
regenerate security-critical secrets properly, wire up the tunnel). The self-hosting/homelab
audience this tool serves regularly asks for the same treatment for other popular stacks.

- [Done] `bootstrap-uptime-kuma` — self-hosted status/uptime monitoring, natural pairing with `list --all-targets`. Turned out much simpler than Supabase in practice: Uptime Kuma ships as a single official image with no secrets to regenerate (own first-run setup wizard), so there's no repo to clone or `.env` to rewrite — just a small generated Compose file with a named volume, reusing the same port allocator `create` uses. Doesn't wire up Cloudflare automatically (same as `bootstrap-supabase`); prints the `cloudflare-route` follow-up command instead.
- [Done] `bootstrap-n8n` — self-hosted workflow automation, very popular alongside Supabase. Ships as a single-container official-image bootstrap with persistent `/home/node/.n8n` storage and a generated `N8N_ENCRYPTION_KEY` written to both the NAS `.env` and local `secrets/<project>.env` for recovery.
- [Done] `bootstrap-vaultwarden` — self-hosted Bitwarden-compatible password manager. Ships as a single-container official-image bootstrap with persistent `/data` storage, generated `ADMIN_TOKEN`, local secret retention, and public signups closed by default.
- [Done] `bootstrap-umami` — privacy-friendly analytics, common ask for anyone deploying sites with this tool. Ships as a two-container official-shape bootstrap (`ghcr.io/umami-software/umami:latest` + private `postgres:15-alpine`) with generated Postgres password and `APP_SECRET` retained in `secrets/<project>.env`.
- [Done] Extract shared generated-Compose bootstrap deployment logic for the official-image apps — `bootstrap-n8n`, `bootstrap-vaultwarden`, and `bootstrap-umami` now share the same port selection, remote overwrite handling, Compose/env upload, secret-file persistence, startup, and container-running checks via `commands/bootstrap_compose.py`. Supabase's clone-and-patch flow remains separate because it has materially different behavior.

## Phase 9 — Deployment Lifecycle (Partially Done)

Every deploy today is "recreate from scratch." Fine for a first deploy, increasingly annoying
once a site has been running in production for a while.

- [Done] `synology-site update <domain>` — pull latest image/rebuild and restart an existing site without re-running the full `create` scaffold/health-check-from-zero flow. Implemented as an in-place Compose update that reads `.synology-site.json`, uses stored deploy compose paths, falls back from failed pull to build, verifies a container when known/provided, and health-checks generated `create` sites.
- [Planned] Health-gated restart instead of a hard `docker compose down && up` — start the new container, confirm its health check passes, *then* stop the old one, to avoid a visible-downtime window on every redeploy
- [Done] Registry-based image builds (build once in CI, push to GHCR, `deploy --pull` on the NAS) as the documented recommended path for anything beyond a personal project — documented in README with Compose, `deploy`, `update`, GHCR login, and GitHub Actions examples.

## Phase 10 — Observability, Backups & Notifications

- [Done] Scheduled DB backups to S3-compatible storage (Backblaze B2/Cloudflare R2 are the popular cheap choices for self-hosters) — `synology-site backup-plan <domain>` generates a MariaDB dump script, env template, cron example, and Synology Task Scheduler command. Real upload verification still requires user-provided bucket credentials.
- [Done] Slack/Discord webhook notification on deploy/update success/failure — `NOTIFY_WEBHOOK_URL` and `NOTIFY_WEBHOOK_EVENTS` are optional and default off; webhook failures warn without changing the command result.
- [Done] A simple aggregated health dashboard pairing with `list --all-targets` — implemented as `synology-site health [--all-targets]`, reading site markers and checking `/health` for every site with a stored port while reporting unreachable targets inline.

## Phase 11 — Security Hardening & Alternative Ingress (Partially Done)

- [Planned] Cloudflare Access (Zero Trust) integration — password/SSO-gate a staging site or admin route via the Cloudflare API, natural extension of the tunnel/DNS automation already built
- [Done] Traefik + Let's Encrypt as a documented alternative to Cloudflare Tunnel for anyone who doesn't want a Cloudflare dependency at all — documented in `docs/traefik-letsencrypt.md`; `deploy` already supports this via the no-`--port` reverse-proxy mode.
- [Done] Secrets stored as plaintext files under `secrets/` today; evaluated `sops`/`age`, 1Password CLI, and Doppler in `docs/secrets-management.md`, with plaintext files retained as the default for personal use.
- [Done] **Confirmed: apps that implement their own OIDC client against a self-hosted IdP (e.g. `../wordpress-ai-publisher` against `../nas-sso-gateway`'s authentik) need zero changes in this tool.** `deploy --env-file` already passes arbitrary new env vars (issuer URL/client ID/secret) through with no code change, and Cloudflare Tunnel ingress keeps routing straight to the app's existing port — no reverse proxy or new component required in front of it. This is a lighter-weight alternative to the `[Planned]` Cloudflare Access line above for anyone who already runs their own OIDC provider instead of wanting Cloudflare's own Zero Trust policies.

## Phase 12 — Remote Access to the Home NAS

Running `create`/`deploy` from a network that isn't the NAS's own LAN (e.g. an office) requires
reaching the NAS's SSH port without a paid remote-access tool. The real constraint: most home
ISPs use CGNAT (no public IP at all), so the connection has to be *initiated outbound from the
NAS*, not inbound to it — the same principle Cloudflare Tunnel already uses in this project.

- [Done] **Document Tailscale (or ZeroTier) as the recommended zero-code solution** — free mesh VPN, official Synology package, works through CGNAT with no router config. Documented in `docs/remote-nas-access.md`, with Tailscale as the default path and ZeroTier/WireGuard/reverse-SSH called out as alternatives.
- [Done] **Optional Tailscale SSH host override** — added `TAILSCALE_ENABLED=false` and `TAILSCALE_NAS_HOST=` for the default NAS target and each `secrets/<workspace>/nas.env`. When enabled, SSH connects through the Tailscale address while `NAS_HOST`/`LOCAL_BASE_URL_HOST` remain available for LAN/service routing. Defaults off so users without Tailscale accounts see no behavior change.
- [Done] **Build: reach the NAS through the Cloudflare Tunnel already running for this project's sites**, instead of a separate VPN. `SSH_ACCESS_HOSTNAME` and `SSH_ACCESS_LOCAL_PORT` now let the CLI transparently start `cloudflared access tcp --hostname ... --url localhost:<port>` before opening SSH. Defaults off and requires the user to configure the Cloudflare Access app/tunnel route first.
- [Done] Document self-hosted WireGuard (DSM's built-in VPN Server package) as a no-third-party fallback — free, but needs a forwarded UDP port + DDNS, and doesn't work at all under CGNAT (called out in `docs/remote-nas-access.md`).
- [Done] Document (lower priority) a reverse-SSH-tunnel-through-a-free-VPS pattern (e.g. Oracle Cloud's free tier + `autossh`) as the option that works under CGNAT without depending on Tailscale or Cloudflare specifically — positioned as the highest-maintenance fallback in `docs/remote-nas-access.md`.
- [Done] `check-nas --remote` — probes `NAS_HOST:NAS_PORT` with a raw TCP connection and automatically routes through whatever remote transport is configured (Tailscale/Cloudflare Access) only when that probe fails, so no flag is needed when actually working remotely. `--remote` forces the remote path even when the LAN probe would succeed, so the remote path itself can be verified without leaving the LAN. Reports which network path and transport were actually used.
- [Done] `configure-tailscale` — automates the last manual step in the Tailscale setup (copying the NAS's `100.x.y.z` address out of the admin console). Given a Tailscale OAuth client (`TAILSCALE_CLIENT_ID`/`TAILSCALE_CLIENT_SECRET`), calls the Tailscale API to list the tailnet's devices and writes `TAILSCALE_ENABLED=true`/`TAILSCALE_NAS_HOST=<discovered address>` into `.env`, leaving every other line untouched. Device selection prefers an explicit `--device-name`, then the currently configured `TAILSCALE_NAS_HOST` (refreshing/confirming an existing setup on re-run), then a single-device tailnet; genuine ambiguity lists candidates and asks rather than guessing. **Run for real** against the live account: found the NAS (`DS`) and its Tailscale address, which matched the address already configured — confirms both the OAuth flow and the existing manual setup were correct.
- [Planned] `deploy`/`create` do not yet share `check-nas`'s LAN-vs-remote auto-detection — they always use whatever `default_ssh_factory` resolves to (Tailscale/Cloudflare Access if configured, even from on the LAN). Worth revisiting only if that turns out to add noticeable latency in practice; `check-nas` was the requested starting point since it's the lowest-risk command to get this right on first.

## Phase 13 — Lightsail-to-NAS Site Migration (planned)

New goal: move an existing site off a paid AWS Lightsail instance onto this NAS instead, starting
with `example.com` (WordPress + MySQL/MariaDB, no S3 — confirmed no offload plugin, media is a
plain local `wp-content/uploads`) as the first real source. Two real targets share the same
extraction step: **(1)** example.com keeps its own hosting, moved to a brand-new NAS Compose stack
(`--target-mode new-site`), and **(2)** a full clone of example.com's DB/files/plugins lands on
`newsite.example`, an already-running-but-empty NAS WordPress site (`--target-mode
existing-site-replace`), which the user will then manually diverge into a separate tech-focused
site. MVP is scoped to exactly what example.com uses; broader source types (EC2, other web
servers/databases) are follow-up flags once this path is proven. Full plan, required access, and
known hurdles are in `docs/lightsail-migration-mvp.md`.

- [Done] `migrate-from-lightsail --source-domain <x> --target-domain <y> --target-mode <mode> --dry-run` — read-only discovery over SSH + Cloudflare API; writes a migration-readiness report to `migration-reports/`, no writes anywhere else. Source credentials resolve from `secrets/<source-domain-slug>/lightsail.env` (same directory-scan convention as Cloudflare/NAS workspaces), overridable with `--source-workspace`. Discovers Bitnami-vs-stock layout, Nginx doc root, other live hostnames sharing the box, PHP version, WP-CLI presence, WordPress version, DB name/user/host from `wp-config.php` (password presence only, never the value), plugin/theme inventory, known S3-offload-plugin detection, `wp-content/uploads` size, `DISABLE_WP_CRON`/crontab, and the source domain's current Cloudflare DNS record(s) (skipped gracefully if that workspace has no API credentials). AWS API discovery (Lightsail instance metadata/snapshots) is not yet included, since it wasn't needed for the veloso.dev case (no S3 offload in use).
- [Planned] `migrate-from-lightsail --source-domain <x> --target-domain <y> --execute` — DB dump/restore, `wp-content` sync (rsync for local files, `aws s3 sync` for offloaded media), WordPress+MariaDB Compose scaffold on the NAS, Cloudflare DNS cutover, post-migration verification.
- [Done] Access setup in `secrets/example-com/` — Cloudflare covered by the default workspace; SSH now working (`secrets/example-com/lightsail.env` corrected to the real instance — the address in `~/.ssh/config` was stale); AWS S3 access confirmed unnecessary for the MVP (no offload plugin on the instance, media is a plain local `wp-content/uploads`).
- [Partial] Read-only SSH discovery done for the instance's shape (nginx vhost, doc root, PHP version, plugin inventory, no WP-CLI) — see `docs/lightsail-migration-mvp.md`. Still open: DB engine/credentials (not yet read from `wp-config.php`), NAS target workspace decision, and this is a **shared instance** (also serves other third-party sites) so all future steps must stay scoped to example.com's own paths.

## Phase 14 — Fleet Health & Safe Bulk Recovery

Direct fallout from a real incident: manually restarting every project on a live fleet (~30
containers across ~10 Compose projects, including a full self-hosted Supabase stack) pushed load
average to 75 and took the Docker daemon down hard enough to need a physical power cycle. Recovery
itself surfaced several gaps this tool had no way to detect on its own: sites that were configured
(marker + Cloudflare route) but never actually had a container created, containers silently missing
an auto-restart policy, a non-default Compose filename that made a plain `compose up -d` fail with
no useful error, and three unrelated projects colliding on Compose's default project name because
they all happened to be checked out into a directory literally called `repo`.

- [Done] `smart_ssh_factory` (LAN-probe-first, falling back to Tailscale/Cloudflare Access) rolled
  out to every command that previously defaulted to `default_ssh_factory` (which always preferred
  the configured remote transport even from on the LAN) — `start`, `stop`, `health`,
  `inspect_containers` (`ps`/`logs`), `remove`, `tunnel_fix`, and all four `bootstrap-*` commands.
  `create`/`deploy`/`update`/`registry-login`/`ensure-network`/`list` already used it.
- [Done] `docker_remote.py` additions: `list_containers_with_projects` (every container's Compose
  project/working dir/service/restart policy, batched via one `docker inspect` call for all names
  rather than one call per container), `read_system_load`/`read_memory_info` (parsed from
  `uptime`/`free -m`, tolerant of DSM's non-standard `uptime` output), and `compose_services`
  (always passes an explicit `-f <file>`, so non-default Compose filenames like
  `docker-compose.admin.yml` work the same as the default).
- [Done] `doctor [--all-targets] [--workspace]` — read-only. Reports never-started sites (a marker
  exists but no container was ever created at its expected working directory — resolved correctly
  even for nested `compose_file` paths like `repo/docker-compose.yml`), containers without
  `restart: unless-stopped`/`always`/`on-failure`, Compose project-name collisions (multiple
  distinct working directories resolving to the same default project name), and load/memory/swap
  pressure against thresholds picked directly from the incident (load ≥25 or swap ≥80% is
  critical; ≥10 / ≥50% is a warning). Exits non-zero if any critical finding exists.
- [Done] `restart-all [--all-targets] [--workspace] [--only <domain-or-slug>] [--stagger-seconds]
  [--max-load] [--dry-run]` — brings a fleet up one Compose *service* at a time (not one project,
  and never a bulk sweep of an entire multi-container stack, which is what caused the incident),
  pausing between each and checking load average before every single start; aborts the whole run
  immediately if load crosses `--max-load` and reports exactly where it stopped rather than
  ploughing on. Covers both already-existing (running or stopped) projects and never-started ones
  `doctor` flags, from the same project-discovery logic. `--only` (repeatable) restricts to named
  projects — recovering a fleet in a deliberate order (light/critical sites first, heavy stacks
  like Supabase last) is both safer and easier to reason about than one all-or-nothing command.
- [Done] `health --proxy-port <port>` — sites with no port of their own (fronted by a shared
  reverse proxy like Traefik instead of a published host port) are checked via a `Host:`-header
  request against the proxy port, the same way an external request actually reaches them, instead
  of just reporting "no port in marker" unconditionally.
- [Done] README: new "Fleet Health & Recovery" section; "Rebooting The NAS" now points at
  `doctor`/`restart-all` instead of a manual `docker ps` eyeball-check.
- [Done] Tests for every addition above, following the existing `FakeSSH` convention (no real NAS
  needed) — `test_docker_remote.py` additions, `test_doctor_command.py`,
  `test_restart_all_command.py`, `test_health_command.py` additions.

---

Design rationale and phased rollout detail for Phase 4 lives in `docs/laravel-scaffold-options.md`.
See `RESUME.md` for what's verified vs. what still needs a real build/second NAS to confirm.
Phases 9-11 still have remaining candidate work — see conversation history
for the reasoning behind each pick.