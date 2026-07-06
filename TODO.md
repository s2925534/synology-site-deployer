# TODO

Status tracker for the multi-workspace Cloudflare + Laravel backend work, organized by phase.

**Legend:** 🟢 Done &nbsp;•&nbsp; 🟡 Partially done / in progress &nbsp;•&nbsp; 🔴 Not started (planned)

---

## Phase 1 — Multi-Workspace Cloudflare (different domain/tunnel/account, same NAS)

| Status | Item |
|---|---|
| 🟢 | `CloudflareAccount` dataclass + `secrets/<name>/cloudflare.env` directory-scan discovery (`cloudflare/workspace.py`) |
| 🟢 | `Settings.resolve_cloudflare(domain, workspace=...)` — longest zone-domain-suffix match, explicit override, default-workspace fallback |
| 🟢 | `cloudflare/api.py` refactored to operate on a resolved `CloudflareAccount` instead of global `Settings` |
| 🟢 | `--workspace` flag on `create`, `deploy`, `cloudflare-route`, `cloudflare-instructions` |
| 🟢 | Tests: workspace discovery, resolution, explicit-override error handling, malformed workspace file handling |
| 🟢 | README: "Multiple Cloudflare Accounts / Domains (Workspaces)" section + `.env.example` pointer |

## Phase 2 — Laravel Backend Option

| Status | Item |
|---|---|
| 🟢 | `LaravelScaffold` — Dockerfile runs the real `composer create-project laravel/laravel` installer at build time instead of hand-templating Laravel's file tree |
| 🟢 | Health (`/health`) and DB health (`/db-health`) routes injected via `routes-extra.php` append |
| 🟢 | MariaDB container topology reused from Flask (shared `compose.yml.j2`, generalized with `internal_port`) |
| 🟢 | Registered in `FRAMEWORKS` (`--framework laravel`) alongside Flask |
| 🟢 | `docs/DATABASE.md` (Laravel-flavored DSN/wording), `docs/README.md`, marker JSON reused/adapted |
| 🟢 | Tests: file list, Dockerfile content, DB-enabled vs sqlite-default `.env`, compose topology |
| 🟢 | README: "Deploy Laravel" section |

## Phase 3 — Production-Grade Laravel Serving

| Status | Item |
|---|---|
| 🟢 | `--php-server fpm-nginx` — two-container topology (`{slug}` PHP-FPM + `{slug}-web` nginx), one Dockerfile with two build targets |
| 🟢 | nginx config: static assets served directly, `.php` requests proxied to PHP-FPM over the container network |
| 🟢 | `container_names()` added to the scaffold interface so `create_site` confirms however many containers a mode uses (1 for `artisan`, 2 for `fpm-nginx`) |
| 🟢 | Validation: `--php-server` rejected for non-Laravel frameworks, unknown values rejected |
| 🟢 | Production recommendation: `create` warns when Laravel is deployed on `artisan` (single-process, not production-grade) instead of `fpm-nginx` |
| 🟢 | Tests: two-container confirmation, both build targets, network wiring with DB enabled |
| 🟢 | README + `docs/laravel-scaffold-options.md` reconciled with what shipped |

## Phase 4 — Frontend Framework Integration

| Status | Item |
|---|---|
| 🟢 | `--frontend` accepts `none`/`livewire`/`inertia-vue`/`inertia-react`/`vue`/`react`/`angular` — all implemented, none are stub/"planned" errors anymore |
| 🟢 | `livewire` — `composer require livewire/livewire`, single container, works with either `--php-server` |
| 🟢 | `inertia-vue` / `inertia-react` — Laravel Breeze's official installer (`breeze:install vue\|react --no-interaction`), assets built into the image, single container |
| 🟢 | `vue` / `react` / `angular` — decoupled SPA: independently-built frontend (Vite for vue/react, Angular CLI for angular) in its own Docker stage + a Breeze `api`-stack Laravel backend, served through **one** nginx container (static files + `/api` proxy) — requires `--php-server fpm-nginx` |
| 🟢 | Two-origin routing question resolved by construction: nginx does the `/api` vs. static split *inside* the existing one-hostname/one-port topology, so no Cloudflare-level path routing or second subdomain was needed |
| 🟢 | Angular question resolved: cost nothing extra once the above was built, so it shipped alongside vue/react |
| 🟡 | **Not build-verified.** The exact Composer/Breeze/Vite/Angular CLI invocations are authored from documented usage, not exercised against a real `docker compose up -d --build` (no reliable Packagist/npm registry access in the authoring sandbox). Failure mode if a flag has moved on is a loud build error in that one `RUN` line, not a silently broken site. See RESUME.md. |

## Phase 5 — Workspace-as-Profile / Multi-NAS / Multi-System

| Status | Item |
|---|---|
| 🟢 | "One tunnel per Cloudflare account" — structurally guaranteed: `secrets/<name>/cloudflare.env` has a single `CF_TUNNEL_ID` field per account |
| 🟢 | `NasTarget` dataclass + `secrets/<name>/nas.env` directory-scan discovery (`nas/target.py`), **inheriting** any unset field from the default target (unlike Cloudflare accounts, which are fully self-contained) |
| 🟢 | `Settings.resolve_target(workspace=...)` + `Settings.known_workspace_names`/`validate_workspace()` — a workspace can define `cloudflare.env`, `nas.env`, or both in the same folder; resolving one doesn't require the other to exist (fixed a real gap: a NAS-only workspace used to be wrongly rejected as an "unknown Cloudflare workspace") |
| 🟢 | **Actually wired into the SSH connection** — `create`/`deploy` resolve the target and connect to *its* host/port/user/credentials (via a `dataclasses.replace`d `Settings`, so no existing function signature or test needed to change), not just the default NAS. Verified with tests that capture what host `ssh_factory` was actually called with. |
| 🟢 | `system_type` (`synology`/`generic-linux`) stored + validated per target. Investigated wiring it into `docker_remote.py`'s Synology-specific fallback paths — found those paths are already harmless no-ops on non-Synology hosts (they only activate after plain `docker`/`sudo docker` fail), so no behavior actually depends on this yet. Kept as validated metadata for a real future Synology-only feature to branch on. |
| 🟢 | `synology-site workspaces` — lists every workspace and what it overrides, plus a doctor check for a `CF_TUNNEL_ID`/`CF_API_TOKEN` duplicated across workspaces (almost always a copy-paste mistake); deliberately does *not* flag shared NAS/`CF_ACCOUNT_ID`, since that's the normal supported setup |
| 🟢 | `synology-site list --all-targets` — aggregates sites across every configured NAS target; an unreachable target is reported inline, not fatal to the rest |
| 🟡 | **Not validated against a real second NAS.** All of the above is covered by unit tests with a fake SSH client capturing the resolved connection parameters — there is no second physical NAS in this environment to confirm an actual SSH session against a different host end-to-end. See RESUME.md. |

**Known caveat (not a bug, a constraint to design around):** a single tunnel's connector
(`cloudflared`) can route to services on other hosts, but only if it can reach them on the
network (shared LAN/VPN mesh). If one Cloudflare account's sites end up split across NAS boxes
that are genuinely network-isolated from each other, "one tunnel per account" and "multi-NAS"
pull in different directions for that account.

## Phase 6 — Additional Backend/Runtime Options (Not Started)

Flask + Laravel cover Python/PHP; these are the two most-requested "deploy my app" targets not
yet covered, picked for popularity rather than novelty.

| Status | Item |
|---|---|
| 🔴 | `--framework nextjs` — Next.js (React full-stack), scaffolded via `npx create-next-app` at build time, same Option-C hybrid pattern as Laravel (don't hand-template it) |
| 🔴 | `--framework fastapi` — FastAPI has largely replaced Flask as the default choice for new Python APIs; `uv`/`pip`-based build, ASGI server (uvicorn/gunicorn) instead of Flask's WSGI dev server |
| 🔴 | Evaluate whether Flask's own scaffold should gain a `--python-server` axis mirroring Laravel's `--php-server` (gunicorn is already production-grade, so likely no — worth a deliberate "no" rather than leaving it unasked) |

## Phase 7 — Laravel Production Completeness (Not Started)

Arguably a bigger real-world gap than the frontend work: a Laravel app in actual production
almost always needs more than a web container.

| Status | Item |
|---|---|
| 🔴 | Queue worker container (`php artisan queue:work`) as an opt-in sibling service, sharing the same app image/build |
| 🔴 | Scheduler container running `php artisan schedule:run` on a cron loop (Laravel has no built-in daemon for this — needs an explicit cron or sleep-loop container) |
| 🔴 | `--with-redis` alongside `--with-db` — cache/session/queue backends in real Laravel production almost always want Redis, not the database driver `laravel_env.j2` currently defaults to |
| 🔴 | Decide default `QUEUE_CONNECTION`/`CACHE_STORE`/`SESSION_DRIVER` once Redis exists as an option — today's `file`/`sync` defaults were deliberately chosen to avoid needing any of this; revisit once it does |

## Phase 8 — Popular Self-Hosted App Bootstraps (Not Started)

`bootstrap-supabase` already proves out the pattern (clone the project's own compose file,
regenerate security-critical secrets properly, wire up the tunnel). The self-hosting/homelab
audience this tool serves regularly asks for the same treatment for other popular stacks.

| Status | Item |
|---|---|
| 🔴 | `bootstrap-n8n` — self-hosted workflow automation, very popular alongside Supabase |
| 🔴 | `bootstrap-uptime-kuma` — self-hosted status/uptime monitoring, natural pairing with `list --all-targets` |
| 🔴 | `bootstrap-vaultwarden` — self-hosted Bitwarden-compatible password manager |
| 🔴 | `bootstrap-plausible` or `bootstrap-umami` — privacy-friendly analytics, common ask for anyone deploying sites with this tool |
| 🔴 | Extract the shared "clone + regenerate secrets + wire tunnel" logic out of `bootstrap_supabase.py` into a reusable helper once a second bootstrap command exists, instead of copy-pasting it |

## Phase 9 — Deployment Lifecycle (Not Started)

Every deploy today is "recreate from scratch." Fine for a first deploy, increasingly annoying
once a site has been running in production for a while.

| Status | Item |
|---|---|
| 🔴 | `synology-site update <domain>` — pull latest image/rebuild and restart an existing site without re-running the full `create` scaffold/health-check-from-zero flow |
| 🔴 | Health-gated restart instead of a hard `docker compose down && up` — start the new container, confirm its health check passes, *then* stop the old one, to avoid a visible-downtime window on every redeploy |
| 🔴 | Registry-based image builds (build once in CI, push to GHCR, `deploy --pull` on the NAS) as the documented recommended path for anything beyond a personal project — building on the NAS itself (today's default for `create`) is fine for low-traffic personal use but doesn't scale to frequent deploys |

## Phase 10 — Observability, Backups & Notifications (Not Started)

| Status | Item |
|---|---|
| 🔴 | Scheduled DB backups to S3-compatible storage (Backblaze B2/Cloudflare R2 are the popular cheap choices for self-hosters) instead of the current manual `mariadb-dump` documented in `docs/DATABASE.md` |
| 🔴 | Slack/Discord webhook notification on deploy success/failure — very common once a tool is used for anything beyond solo experimentation |
| 🔴 | A simple aggregated health dashboard pairing with `list --all-targets` — one view of every site's `/health` status across every NAS target, instead of curling each one by hand |

## Phase 11 — Security Hardening & Alternative Ingress (Not Started)

| Status | Item |
|---|---|
| 🔴 | Cloudflare Access (Zero Trust) integration — password/SSO-gate a staging site or admin route via the Cloudflare API, natural extension of the tunnel/DNS automation already built |
| 🔴 | Traefik + Let's Encrypt as a documented alternative to Cloudflare Tunnel for anyone who doesn't want a Cloudflare dependency at all — `deploy` already supports the "existing reverse proxy" no-port-allocation mode, but there's no scaffold-side guidance for setting one up from scratch |
| 🔴 | Secrets stored as plaintext files under `secrets/` today; evaluate age/sops-encrypted secrets or a proper secrets manager (1Password CLI, Doppler) for anyone deploying this from a shared/less-trusted machine |

---

Design rationale and phased rollout detail for Phase 4 lives in `docs/laravel-scaffold-options.md`.
See `RESUME.md` for what's verified vs. what still needs a real build/second NAS to confirm.
Phases 6-11 are brainstormed candidates, not yet scoped or agreed on — see conversation history
for the reasoning behind each pick.
