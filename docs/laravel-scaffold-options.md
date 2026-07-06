# Adding a Laravel `create` Option — Design Choices

**Status: Phase 1 is implemented.** `create --framework laravel` works today (Option C below),
including a production-grade serving mode (`--php-server fpm-nginx`, added after this doc was
first written — see the note at the end of §4). Phases 2/3 (frontend framework integration) are
still design-only: the CLI recognizes and documents the values, but rejects them with a "planned"
error. The rest of this doc is kept as the design record for those phases and for how Phase 1 was
decided; treat §4's original `--stack` proposal as superseded by what's in the "What actually
shipped" note below it.

## 1. Why Laravel isn't a drop-in copy of the Flask scaffold

The current `FlaskScaffold` (`src/synology_site/scaffold/flask.py`) works because Flask apps can be
represented as ~6 small Jinja2-rendered files (`app.py`, `requirements.txt`, `Dockerfile`,
`docker-compose.yml`, docs, marker). The CLI renders those files locally and uploads them — no
build tooling is needed to produce the source tree itself.

Laravel doesn't fit that model:

- A real Laravel app is the output of `composer create-project laravel/laravel` — hundreds of
  files (routes, config, service providers, `artisan`, etc.), not something you want to hand-roll
  as Jinja2 templates that then drift from whatever `laravel/laravel` ships next.
- Frontend tooling (Vue/React/Inertia/Livewire) is installed via Composer packages *and* npm
  packages, then built with Vite. That's a real build step, not a template render.
- This means "scaffold" for Laravel is closer to what `deploy --source-dir` already does (build
  on the NAS from source) than what `create` does today for Flask.

This is the first fork in the road and affects everything else below.

### Option A — Template-rendered file tree (matches Flask's current pattern)
Ship a curated set of Jinja2 templates that reproduce a minimal Laravel skeleton (routes, a couple
controllers, `artisan` stub, `.env`, `composer.json`, Dockerfile). `create` renders and uploads
them, then the Dockerfile's `RUN composer install` fills in vendor/ during the image build.

- ✅ Consistent with the existing `ScaffoldContext` / `GeneratedFile` architecture — smallest code
  change, reuses `commands/create.py` verbatim.
- ✅ No new "run composer/npm on the NAS to bootstrap a new app" step outside Docker.
- ❌ You're maintaining a hand-copied subset of Laravel's skeleton indefinitely; new Laravel major
  versions (11 → 12 → ...) can silently drift from what `laravel/laravel` actually ships.
  Fine for a bare API, awkward the moment Breeze/Jetstream/Inertia starter kits are involved
  (those generate way more files than we'd want to template by hand).

### Option B — Build-time scaffold (Docker RUN composer create-project)
`create` uploads only a Dockerfile + docker-compose.yml + a small build-args/env file. The
Dockerfile itself runs `composer create-project laravel/laravel .` (and, if a frontend stack is
selected, `composer require laravel/breeze --dev && php artisan breeze:install vue && npm ci &&
npm run build`) as build steps, baked into a multi-stage image.

- ✅ Always produces a real, current, official Laravel app — no template drift, and Breeze/
  Jetstream/Inertia installers (which themselves scaffold many files) work unmodified.
- ✅ Naturally extends to "any starter kit," including future Laravel installer flags, without us
  writing new templates per combination.
- ❌ First-time `docker compose up -d --build` is slower (composer + npm install happen on the
  NAS) and needs the NAS to have network access to Packagist/npm registry during build — same
  constraint `deploy --source-dir` already accepts, so not a new class of problem for this repo.
- ❌ A little less "inspectable" before first build — there's no local file tree to `--dry-run`
  print like Flask's file list, only the recipe that will produce one.

### Option C — Hybrid (recommended shape)
Use Option B for the actual `laravel new` + frontend-installer step (so we're never
reimplementing Laravel's own scaffolding), but keep a thin `LaravelScaffold` in the existing
registry that renders the *wrapper* files Flask also has: `Dockerfile`, `docker-compose.yml`,
`docs/README.md`, `.synology-site.json` marker, and `docs/DATABASE.md` when `--with-db` is set.
This keeps `create`'s CLI surface, health-check polling, DB-container wiring, and Cloudflare
integration completely unchanged — only the Dockerfile's build recipe differs per framework.

This is the option worth prototyping first; the rest of this doc assumes it.

## 2. Backend-only shape (no frontend framework opinion)

Before frontend combos, decide the default "plain Laravel" flavor `--framework laravel` produces
with no other flags:

| Preset | What it is | Notes |
|---|---|---|
| **API-only** | `laravel new --api` (routes/api.php, Sanctum-ready, no Blade/views) | Matches Flask's own "just an API + health check" spirit best. |
| **Blade + Vite (default Laravel)** | Standard `laravel new`, default Vite/Tailwind starter, no JS framework | Closest to "Laravel out of the box." |
| **Livewire** | `laravel new` + `composer require livewire/livewire` | PHP-driven reactivity, no separate JS framework/build to manage, no second container. Closest in *spirit* to Flask's single-container simplicity. |

Recommendation: default to **API-only** for parity with Flask (`/health`, `/db-health` equivalents
are trivial to add as a controller), and treat Blade/Livewire/frontend-framework choices as
opt-in via a `--stack` flag (see §4).

## 3. Frontend-framework integration patterns

This is the actual "Vue/React/Angular/etc." question. Laravel has three officially-supported
integration shapes, plus one DIY shape for anything Laravel doesn't ship an installer for:

### 3a. Inertia.js (Laravel's official "SPA without an API" glue)
Laravel controllers return Inertia responses instead of JSON or Blade views; the frontend
framework renders pages but routing/data-loading stays server-side. No REST/GraphQL API layer to
maintain separately.

- **Officially installable via Breeze**: `php artisan breeze:install vue`, `... react`, or
  `... svelte`. **No official Angular Inertia adapter** (community ones exist but aren't
  Laravel-blessed) — Angular is not a good fit for this path.
- Single container: PHP serves everything, npm build only produces static assets bundled into the
  same image. Cleanest Docker topology of all options — one service, same shape as Flask+DB today.

### 3b. Fully decoupled SPA (Laravel API + standalone frontend app)
Laravel is a pure JSON API (Sanctum for auth), and the frontend is a completely separate
Vue CLI/Vite, Create React App/Vite, or Angular CLI project with its own build and its own web
server (nginx serving the built static bundle).

- ✅ The only realistic path for **Angular** (Angular has no Laravel-specific installer, but it
  doesn't need one — it just talks to any HTTP API).
  Also the natural choice if the user wants Vue/React fully independent of Laravel's build
  pipeline (e.g. deploying to a CDN later, or a team that owns frontend/backend separately).
  ✅ Frontend and backend can scale/restart independently.
- ❌ Two containers per site instead of one (`{slug}-api` + `{slug}-web`), so this is the first
  place port allocation, health checks, and the Cloudflare route logic all need to handle "two
  origins for one domain" — likely via a path-based split (`/api/*` → Laravel, `/*` → frontend) or
  two subdomains. This is real, new plumbing beyond what `ScaffoldContext`/`create_site` do today.

### 3c. Livewire + Alpine.js (no separate JS framework)
Mentioned in §2 — included here for contrast. No Vue/React/Angular at all; reactivity is done in
PHP with small Alpine.js sprinkles. Simplest possible topology (one container, no npm framework
build), but doesn't answer "integrate with Vue/React/Angular" since there isn't one.

### 3d. Vanilla Vite (Blade + plain Vue/React components, no Inertia)
`laravel new` ships Vite by default; you can `npm install vue`/`react` and mount components
directly into Blade views without Inertia or Breeze. More manual than 3a, less isolated than 3b.
Rarely what people mean by "Laravel + Vue," but worth naming since some users specifically want
"just enough Vue for one interactive page" without adopting Inertia's routing model.

## 4. Proposed CLI surface

```
synology-site create app.example.com --framework laravel --stack api
synology-site create app.example.com --framework laravel --stack inertia-vue
synology-site create app.example.com --framework laravel --stack inertia-react
synology-site create app.example.com --framework laravel --stack livewire
synology-site create app.example.com --framework laravel --stack spa-vue      # decoupled, 2 containers
synology-site create app.example.com --framework laravel --stack spa-react   # decoupled, 2 containers
synology-site create app.example.com --framework laravel --stack spa-angular # decoupled, 2 containers
```

`--stack` presets map to a `(installer_commands, container_topology, dockerfile_template)` tuple
in `LaravelScaffold`. Presets prefixed `inertia-*` and `livewire`/`api` reuse the existing
single-container `ScaffoldContext`/`CreateResult` flow untouched. `spa-*` presets are the ones
that need the two-container topology work described in §3b — worth shipping in a second phase.

Existing flags (`--with-db`, `--db-mode`, `--port`, `--force`, `--dry-run`, `--strict-cloudflare`)
keep working unmodified for every preset above — `db_mode`/Cloudflare wiring is orthogonal to
which frontend framework is chosen.

### What actually shipped instead of `--stack`

The single `--stack` flag proposed above was split into two independent flags once it became
clear they're orthogonal concerns:

- **`--frontend`** (`none` | `vue` | `react` | `angular` | `inertia-vue` | `inertia-react` |
  `livewire`) covers the frontend-framework question from §3. Only `none` (no-op) is implemented;
  every other value is accepted by the CLI and rejected with a "planned, see this doc" error —
  this *is* the Phase 2/3 work below, still undone.
- **`--php-server`** (`artisan` | `fpm-nginx`) is a different axis this doc didn't originally
  anticipate: not "which frontend," but "how does the container actually serve PHP." `artisan`
  (default) is `php artisan serve`, a single process — fine for personal use, not production
  concurrency. `fpm-nginx` is a real two-container PHP-FPM + nginx topology (`{slug}` + `{slug}-web`,
  one Dockerfile with two build targets) — **this is implemented**, not just documented, and
  `create` recommends it whenever Laravel is deployed without it. See `README.md` → "Deploy
  Laravel" for usage. Note this means the two-container topology §3b worried about as "real, new
  plumbing beyond what `create_site` does today" already exists for the `fpm-nginx` serving mode —
  a future `spa-*` frontend preset reusing that same plumbing is less new work than §3b implied.

## 5. Suggested phased rollout

1. **Phase 1 — done.** `--framework laravel` (Option C hybrid scaffold, single container by
   default) reuses 100% of `create_site`'s DB/Cloudflare/health-check machinery. Shipped with a
   bonus not originally scoped here: `--php-server fpm-nginx`, a production two-container
   PHP-FPM + nginx topology (see the note in §4). `container_names()` was added to the scaffold
   interface so `create_site` can confirm however many containers a given scaffold/mode uses,
   which is also what a future `spa-*` preset would reuse.
2. **Phase 2 — not started.** Add `inertia-vue`, `inertia-react`, `livewire` as real `--frontend`
   values instead of the current "planned" rejection — still single container, just a different
   Dockerfile build recipe/npm build step per preset. No changes needed to `commands/create.py`
   itself, only new templates + registry entries.
3. **Phase 3 — not started.** Add `spa-vue`, `spa-react`, `spa-angular` — this is the only phase that touches
   `create_site`'s core assumptions (one container/one port/one health URL per site), since it's
   two containers behind one domain. Reuses whatever pattern gets built here for any future
   "frontend + API" combo, not just Laravel's.

## 6. Open questions for you

- Do you actually need Angular, or was it named as "the third framework people ask about"? If
  nobody needs Angular specifically, Phase 3 (the only phase Angular requires) could be dropped
  entirely and everything ships as single-container Inertia/Livewire presets.
- For decoupled SPA mode (3b), do you want path-based routing on one domain (`/api` vs `/`) or two
  subdomains (`api.app.example.com` + `app.example.com`)? This decides the Cloudflare/Traefik
  routing shape and is the main new architectural piece.
- ~~Should `--stack` have a default...~~ Resolved: `--frontend none` and `--php-server artisan`
  are both the defaults today, matching the original recommendation's spirit (minimal-by-default,
  parity with Flask) — `--php-server fpm-nginx` is opt-in and recommended, not default, so a
  plain `create --framework laravel` stays a single, simple container.
