# RESUME — Frontend Integration + Workspace-Driven Multi-NAS

Summary of what got built in this pass (Phase 4 + Phase 5 from `TODO.md`), what's genuinely
verified vs. authored-but-unverified, and exactly what to do to close each gap. Nothing here was
committed or pushed — it's sitting in the working tree for you to review first.

## TL;DR

- **Phase 4 (frontend frameworks)** and **Phase 5 (multi-NAS workspaces)** are both fully
  implemented, not just designed. 166 tests pass, `ruff check` is clean, and I ran the new code
  against your real `.env` (read-only — `workspaces`, `list`) to confirm zero behavior change for
  your current single-NAS/single-account setup.
- **Two things are implemented but not verified against real infrastructure**, because doing so
  would have required exactly what you told me not to need: a second real NAS, and reliable
  package-registry access this sandbox doesn't reliably have. Both are called out below with the
  exact steps to verify them yourself, and both fail *loudly* if something's off rather than
  silently breaking a site.
- Nothing about your existing single-NAS, single-Cloudflare-account, Flask/Laravel-artisan setup
  changed behavior. Every new code path is additive and opt-in (a new `--frontend`/`--php-server`
  value, a new `secrets/<name>/nas.env` file, a new `--all-targets` flag).

## What's done and verified

### Phase 4 — Frontend frameworks (`--frontend`)
All six values are implemented (previously only `none` worked, everything else was a stub error):

| Value | What it does | Container topology |
|---|---|---|
| `livewire` | `composer require livewire/livewire` | 1 (works with either `--php-server`) |
| `inertia-vue` / `inertia-react` | Laravel Breeze's official installer, assets built in-image | 1 |
| `vue` / `react` / `angular` | Independently-built SPA (Vite/Angular CLI) + Laravel API backend (Breeze `api` stack), served through one nginx container | 2 (requires `--php-server fpm-nginx`) |

Verified: scaffold-generation tests for every combination (23 tests in
`test_laravel_scaffold.py`), validation tests (rejects decoupled-SPA frontends without
`--php-server fpm-nginx`, rejects `--frontend` for non-Laravel frameworks), and manual template
rendering for all 11 frontend×server combinations to confirm no Jinja syntax errors and that
generated YAML/nginx config is well-formed.

### Phase 5 — Workspace-driven multi-NAS
- A workspace (`secrets/<name>/`) can now define `nas.env` alongside — or instead of —
  `cloudflare.env`. Unset fields in `nas.env` inherit the default target's values, so a workspace
  that only needs a different `NAS_HOST` doesn't have to repeat everything else.
- **This is actually wired into the SSH connection**, not just resolvable in config: `create`
  and `deploy` now connect to *the resolved target's* host/port/user/credentials. Verified with
  tests that capture what host the SSH factory was actually invoked with when a workspace defines
  its own `nas.env` (`test_create_site_uses_resolved_nas_target_for_ssh_connection`,
  `test_deploy_uses_resolved_nas_target_for_ssh_connection`) — this is the part that would have
  been easy to leave as dead config and I want to be explicit that it isn't.
- Fixed a real correctness gap along the way: a NAS-only workspace (defines `nas.env`, no
  `cloudflare.env`) used to be wrongly rejected as an "unknown Cloudflare workspace" if you passed
  `--workspace` with its name. Validation now checks the union of known accounts *and* targets.
- `synology-site workspaces`: lists every workspace and a doctor check for a `CF_TUNNEL_ID` or
  `CF_API_TOKEN` accidentally duplicated across workspaces. Ran it against your real `.env` —
  output was `default: Cloudflare account (veloso.dev, ready=True), NAS target (192.168.1.109)`
  and "No duplicate-credential issues detected," confirming it reads your real config correctly
  without printing anything sensitive (no tokens/passwords in the output).
- `synology-site list --all-targets`: aggregates sites across every configured target; one
  unreachable target is reported inline, not fatal to the others.
- `system_type` (`synology`/`generic-linux`) is stored and validated per target, for a future
  non-Synology host. I looked for where this would actually need to change behavior today and
  found the only Synology-specific code is two fallback docker-binary paths in
  `docker_remote.py` that are already harmless no-ops on any other Linux host (they only run
  *after* plain `docker`/`sudo docker` fail) — so there's nothing to wire it into yet. It's there
  so a real Synology-only feature later (e.g. DSM Task Scheduler-based autostart) has something
  to branch on without a breaking config change.

## What's implemented but NOT verified against real infrastructure

### 1. The exact Composer/Breeze/Vite/Angular CLI commands in the new Dockerfiles

I could not run a real `docker compose up -d --build` for any of the six frontend modes — this
sandbox has PHP/Composer/Node/npm locally, but outbound access to `repo.packagist.org` and
`registry.npmjs.org` timed out on every attempt at an actual package install (a plain `curl -I`
to both succeeded, but Composer's/npm's own downloaders did not — some sandbox-level restriction
beyond simple connectivity). So the commands in `laravel_dockerfile.j2` and
`laravel_fpm_dockerfile.j2` are authored from documented, current Laravel/Breeze/Vite/Angular CLI
usage, not exercised end-to-end.

**Specifically un-verified:**
- `php artisan breeze:install vue|react --no-interaction` and `php artisan breeze:install api --no-interaction` — confident these are correct (well-documented, stable Breeze command), but not run.
- `npm create vite@latest . -- --template vue|react` — the exact non-interactive flag surface for `npm create` can vary by npm version; there's a chance a real run needs an extra `-y`/`--yes` to skip an "install create-vite, ok to proceed?" prompt. Docker builds run with no attached stdin, which usually resolves such prompts to their default rather than hanging, so the likely failure mode is a clear build error, not a silent hang.
- `ng new . --directory=. --routing=false --style=css --skip-git --defaults --skip-install=false` — Angular CLI's flags and default project output structure (`dist/<project>/` vs `dist/<project>/browser/`) have changed across major versions. I defended against the output-path uncertainty by having the build stage `find`-locate wherever `index.html` actually landed rather than hardcoding a path, so this specific risk is mitigated — but the `ng new` invocation itself is the least battle-tested piece of everything in this pass.

**How to verify:** pick one frontend mode and do a real deploy —
```bash
synology-site create test.yourdomain.dev --framework laravel --frontend livewire --dry-run
synology-site create test.yourdomain.dev --framework laravel --frontend livewire
```
then repeat for `inertia-vue`, and separately for `vue --php-server fpm-nginx` (the most
speculative one) on a throwaway subdomain. If a `RUN` step in `app/Dockerfile` fails, the fix is
almost always a one-line flag adjustment to that step — Docker build failures are loud and
specific about which command failed, not a silently broken site.

### 2. Multi-NAS wiring, against a real second NAS

Everything is covered by unit tests with a fake SSH client that captures the resolved connection
parameters (host/port/user/credentials) and confirms they match the target's `nas.env`, not the
default. What I could not do is actually open an SSH session to a *second real machine*, because
I don't have one and you said no new infrastructure should be required.

**How to verify:** if/when you have a second host available —
```bash
mkdir -p secrets/testnas
cat > secrets/testnas/nas.env <<'EOF'
NAS_HOST=<second host IP>
NAS_SSH_KEY_PATH=<path to a key that can reach it>
EOF
synology-site workspaces          # confirm it shows up as "testnas: NAS target (...)"
synology-site create test.yourdomain.dev --workspace testnas --dry-run
```
The dry run exercises the full resolution path (SSH connect, docker check, port allocation) against
the real second host without deploying anything, since `--dry-run` returns before uploading files
or starting containers.

## What was deliberately not built (and why)

- **Fully decoupled two-hostname SPA routing** (`{slug}-api` + `{slug}-web` on separate
  subdomains, from the original design doc's §3b) was not built. The nginx-internal-path-routing
  approach that *was* built achieves the same practical outcome — an independently-built
  frontend talking to a Laravel API — without needing new Cloudflare DNS records, a second
  tunnel route, or new port-allocation logic. The tradeoff is that frontend and backend
  always scale/restart together (one container pair, not two independently-managed origins).
  Revisit only if you specifically need independent scaling.
- **Target/account fully decoupled as separate top-level `targets/`/`accounts/` directories**
  (the many-to-many pairing option from the design discussion) was not built. Instead, a single
  `secrets/<name>/` folder can hold either or both of `cloudflare.env`/`nas.env`. This covers
  every case you described (same NAS/different account, different NAS/same account, both
  different) with less new surface area — the many-to-many version only earns its keep if you
  end up with, say, 3 NAS boxes × 4 Cloudflare accounts in varied combinations, which isn't
  today's shape.
- **Rewiring `system_type` into `docker_remote.py` and 9 other command files** was scoped down
  to just storing/validating the field. See the Phase 5 note above — there's currently nothing
  for it to actually change, and rewriting the core SSH/docker-detection path across every
  command for a hypothetical need was exactly the kind of high-blast-radius, hard-to-verify
  change I was told to be careful about.

## Validation performed

- `pytest`: 166/166 passing (started at 128 before this session; +38 new tests).
- `ruff check src/ tests/`: clean.
- Loaded your real `.env` through `load_config()` directly — resolves to exactly one workspace
  (`default`), confirming no behavior change for your current setup.
- Ran `synology-site workspaces` and `--help` for every touched command against your real config
  — read-only, no secrets printed, no SSH/API calls made.
- Manually rendered every new Laravel scaffold combination (6 frontends × 2 server modes where
  applicable) and inspected the generated Dockerfile/compose/nginx.conf content directly.

Nothing was committed or pushed. Run `git status`/`git diff` to review before deciding what to
commit.
