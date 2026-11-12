# zqx frontends → Vercel — prep/plan (ready to execute)

**2026-11-12, deployer session.** Groundwork for moving the zqx Next.js frontends off the NAS to Vercel.
Access confirmed: `VERCEL_ZQXIO_TOKEN` in `.env`, account **admin@zqx.io**, team **zqx2 / "ZQX"**
(`team_uKL1ePEdgmE6CUVFQaBOqpXb`), no projects yet.

## What moves
4 self-contained **Next.js 16** apps in the `zqxio/zqx` monorepo (npm, root `package-lock.json`, **no shared
`packages/`** → each builds independently). Each is currently a NAS container (`node server.js`, port 3000),
**no DB dependency** — they call `zqx-api` over HTTP. The backend `apps/api` stays (NestJS); `apps/field-native`
is mobile (skip).

| Vercel project | Root Directory | Current NAS container | Domain |
|---|---|---|---|
| zqx-site   | `apps/site`   | zqx-site   | zqx.io (apex + www) |
| zqx-app    | `apps/app`    | zqx-app    | app.zqx.io |
| zqx-portal | `apps/portal` | zqx-portal | portal.zqx.io |
| zqx-field  | `apps/field`  | zqx-field  | field.zqx.io |

## Per-project Vercel settings
- **Framework preset:** Next.js (auto). **Root Directory:** `apps/<name>`. Install/Build: defaults — Vercel
  detects the root npm workspace + lockfile and builds the app. No `vercel.json` needed to start.
- **Env vars** (copy from each NAS container's env: `docker inspect <container> --format '{{range .Config.Env}}…'`).
  Known for `apps/app` (template; others similar):
  - `ZQX_API_URL` → **change `http://zqx-api:3000` → `https://api.zqx.io`** (internal → public; required on Vercel)
  - `NEXTAUTH_URL` = the app's public URL (e.g. `https://app.zqx.io`)
  - `NEXTAUTH_SECRET` = (secret, copy from container)
  - **Auth: do NOT carry `AUTH_AUTHENTIK_*`** — that SSO is dead (sso.systemsnotsilos.com → 502). Replace with
    the **velosolabs hub OIDC** provider (issuer/client id/secret) once the repoint lands (PR #310 / the hub
    OIDC-client registration). This is the main gating prerequisite.
- **Supabase↔Vercel integration** you already connected will auto-inject Supabase vars — harmless; these apps
  use `ZQX_API_URL`, not Supabase directly, so they're not required.

## Prerequisites (both must be true before prod cutover)
1. **Auth repoint → velosolabs hub OIDC** (fixes the current `app.zqx.io` login outage too). In flight as the
   cloud session's PR #310 (blocked only by 2 flaky rate-limit tests — see
   `zqx-flaky-ratelimit-diagnosis.md`).
2. **Git method** — choose one:
   - **a)** Install the **Vercel GitHub app** on the `zqxio` org (dashboard, one-time) → I create Git-connected
     projects (auto-deploy on push). *Recommended.*
   - **b)** I deploy via **Vercel CLI** from a local clone of `zqxio/zqx` (`vercel --token …`, root dir per app).
     No auto-deploy, but no GitHub-app install needed.

## Suggested execution order (low risk first)
1. **Staging first** — the `*-staging` apps → Vercel (you already wired Vercel + the zqx **staging** Supabase),
   validate build + env + a preview domain. Non-prod, removes 4 staging containers.
2. **Prod frontends** → Vercel; then repoint Cloudflare DNS (CNAME `zqx.io`/`app`/`portal`/`field` → Vercel).
   **DNS stays on Cloudflare** — Vercel only hosts the Next apps.
3. Retire the 8 NAS frontend containers once green.

## Not doing until told
Nothing executed yet (no Vercel projects created, no DNS changed). Needs your Git-method call + the auth fix.
