# zqx frontends → Vercel staging — setup & blockers (2026-11-16)

Prepared while Pedro was asleep. **Nothing was created on Vercel** — the one
hard blocker (below) must be cleared first; creating orphan shell projects now
would just be clutter to delete later.

## What's already verified / ready
- **Vercel account:** `admin@zqx.io`, team **zqx2** (`team_uKL1ePEdgmE6CUVFQaBOqpXb`).
- **GitHub app IS installed** on the `zqxio` org (namespace id `180731968`); the
  private repo **`zqxio/zqx`** (repo id `1300021182`, default branch `main`) is
  visible/connectable. *(The anticipated "GitHub app not installed" blocker does
  NOT apply.)*
- **Monorepo build config is known:** each app is self-contained — its own
  `package-lock.json` + `Dockerfile`, Next.js **16.3.8**. So each Vercel project
  just needs `rootDirectory = apps/<name>`, framework **nextjs**, default install
  — no workspace wiring, no "include files outside root".
- The 4 frontends: `apps/site`, `apps/app`, `apps/portal`, `apps/field`.
  (`apps/field-native` = React Native, NOT a Vercel target. `apps/api` = the Docker
  backend, NOT a Vercel target — it runs as a container.)

## 🚧 HARD BLOCKER — needs Pedro (a paid decision)
**Vercel refuses to link `zqxio/zqx`:**
> `repo_owned_by_org` — "The repository is private and owned by an organization,
> which is not supported on the Hobby plan. Upgrade to Pro to continue."

Team **zqx2** (and the personal scope) are both on **Hobby**. A **private,
org-owned** repo requires **Vercel Pro** (~US$20/seat/mo).

**To unblock, one of:**
1. **Upgrade team zqx2 → Pro** (recommended; keeps the repo private). Vercel →
   team zqx2 → Settings → Billing → Upgrade to Pro. Then tell this session and
   the 4 projects get created + configured in one pass (script below is ready).
2. (Not recommended) make `zqxio/zqx` public — defeats the point; rejected.

## 🚧 SECOND dependency — not a Vercel blocker, but staging is non-functional without it
These are **frontends with no Supabase of their own** — they call the backend
`apps/api` server-side via **`ZQX_API_URL`** (my original directive's assumption
that they need `NEXT_PUBLIC_SUPABASE_*` is **wrong** — Supabase lives in
`apps/api`, not the frontends). So each staging frontend needs a **deployed
staging `apps/api`** URL. There isn't one yet. Options: run a staging `apps/api`
container (its Dockerfile exists) on the AWS box or NAS and point `ZQX_API_URL`
at it. **Decide the staging apps/api home → give me its URL.**

## Per-app env vars (what I'll set once Pro is active)
| var | site | app | portal | field | source / note |
|---|---|---|---|---|---|
| `ZQX_API_URL` | ✓ | ✓ | ✓ | ✓ | **needs staging apps/api URL (blocked)** |
| `NEXTAUTH_SECRET` (+ `AUTH_SECRET`, `AUTH_TRUST_HOST=true`) | — | ✓ | ✓ | — | I generate a fresh random per app |
| `NEXTAUTH_URL` | — | ✓ | ✓ | — | set to each project's stable `*.vercel.app` after create |
| `AUTH_VELOSOLABS_ISSUER/ID/SECRET` | — | ⚠ | — | — | **needs Pedro**: register a velosolabs.com OIDC confidential client for the app's staging redirect `…/api/auth/callback/velosolabs`. Left UNSET ⇒ "Sign in with VelosoLabs" button hidden, native login still works. |
| Sentry DSNs | optional | optional | optional | optional | hardcoded fallback exists; leave unset |

No custom production domains will be assigned — staging stays on `*.vercel.app` only.

## Ready-to-run creation (once Pro is active) — uses VERCEL_ZQXIO_TOKEN from .env
```
TOK=$(grep -E '^VERCEL_ZQXIO_TOKEN=' .env | cut -d= -f2-)
TEAM=team_uKL1ePEdgmE6CUVFQaBOqpXb
for pair in "zqx-site-staging:apps/site" "zqx-app-staging:apps/app" \
            "zqx-portal-staging:apps/portal" "zqx-field-staging:apps/field"; do
  name=${pair%%:*}; root=${pair##*:}
  curl -s -X POST "https://api.vercel.com/v11/projects?teamId=$TEAM" \
    -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
    -d "{\"name\":\"$name\",\"framework\":\"nextjs\",\"rootDirectory\":\"$root\",\"gitRepository\":{\"type\":\"github\",\"repo\":\"zqxio/zqx\"}}"
done
```
Linking does NOT auto-deploy; the first staging build happens on the next push to
`main` (or a manual Deploy). That's the desired "push → auto-deploy to staging".
