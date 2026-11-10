# DB cloud migration — morning runbook (2026-11-09, for Pedro)

Overnight status + the exact ordered steps that still need a human (the auto-mode
guard blocks live prod deploys, DB RBAC changes, and R2 enablement — everything
below in **[YOU]** is waiting on you; everything in **[DONE]** is finished).

All scripts are committed durably at `agent-context/migration-2026-11/` (they read secrets
from `.env` at runtime — no secrets in the files). Run the cutovers with the `! bash <path>`
prefix so they execute in-session.

---

## [DONE] Data copies — both verified, NAS untouched (kept as fallback)

| Source (NAS) | → Target | tables | rows | notes |
|---|---|---|---|---|
| `zqx-db` (zqx/zqx_owner) | **Supabase** ZQX `xmklzncqgnuhxagsfeaq` | 97 = 97 | 171 = 171 | restored via IPv4 **session pooler**, Tokyo |
| `mcp-gateway-db` (mcp_gateway/mcp_gateway_owner) | **Neon** VelosoLabs `proud-boat-42777651` | 15 = 15 | 116 = 116 | Singapore, pg18 |

**Key gotcha discovered:** Supabase's *direct* host `db.<ref>.supabase.co` is **IPv6-only**
and the NAS has no IPv6 route — so the zqx apps (which run **on the NAS**) must use the
**IPv4 session pooler** `aws-0-ap-northeast-1.pooler.supabase.com:5432` (user `postgres.<ref>`).
`.env` `SUPEBASE_CLOUD_ZQX_CONNECTION_STRING` was already repointed to the pooler (old value
saved to `.env.bak-*`). Neon has no such issue (IPv4).

---

## [DONE ✅ 2026-11-10] Step 1 — Cutover mcp-gateway → Neon

Live on Neon and verified: both `mcp-gateway` + `mcp-gateway-admin` **healthy** on
`velosolabs_owner@ep-sparkling-voice-a12f48sd-pooler.ap-southeast-1.aws.neon.tech`, ~10h uptime,
zero DB errors, `/mcp/account` returns a proper **401** (route + auth + DB working). NAS
`mcp-gateway-db` left running as fallback; pre-cutover backup `mcp-gateway/.env.bak-20261110-080110`.
**Gotcha fixed:** the original health gate used `https://mcp.velosolabs.com/healthz`, which 404s
(that path isn't exposed through the tunnel). The committed script now gates on the **container's
own Docker health status** (which internally hits `/healthz:8080` → 200) + a log DB-error scan.

## [YOU] Step 2 — Cutover zqx-api → Supabase

```
! bash /Users/pedro/Documents/_Projects/synology-site-deployer/agent-context/migration-2026-11/cutover-zqx-to-supabase.sh
```
- Rewrites `DATABASE_URL` + `APP_DATABASE_URL` in `api-zqx-io/docker-compose.yml`, recreates `api`.
- Keeps `zqx-db` running. Health-checks `http://127.0.0.1:5105/health`. **Auto-rolls back** on ≠ 200.
- **Staging left OFF** on purpose: `zqx-api-staging` uses a separate `zqx_staging` DB; migrate it
  only after you add a separate `SUPEBASE_CLOUD_ZQX_STAGING_CONNECTION_STRING` and copy that DB.
- app/field/portal need **no change** — they reach the DB only via `zqx-api`.

After each: hit the public site (zqx.io flows; mcp.velosolabs.com) and confirm it behaves before
moving on. Both NAS DBs stay as instant fallback — rollback is `cp` the `.bak` + one recreate.

---

## [YOU] Step 3 — Supabase security hardening (run once, BEFORE exposing anything)

Moving to Supabase **created a new exposure that didn't exist on the NAS**: Supabase auto-publishes
the `public` schema over its PostgREST API to the `anon`/`authenticated` roles. The linter flags **17
`SECURITY DEFINER` functions callable by `anon` over the internet** (e.g. `resolve_user_tenant(email)`,
`platform_list_tenants_with_counts`, `list_active_memberships`) + 21 RLS-enabled-no-policy tables.
The zqx app connects as the **owner role** (bypasses all grants), so this revoke is safe and does
**not** affect the app. I was blocked from applying it autonomously (RBAC change on a shared DB), so
run it yourself via the Supabase SQL editor (or MCP):

```sql
REVOKE USAGE ON SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;
```
Reversible via the matching `GRANT`s. (Alternative: disable the Data API entirely in Supabase →
Settings → API, since the app uses direct Postgres, not PostgREST.)

Benign (no action needed): 279 "unused index" (no query history yet), 2 unindexed FKs,
`function_search_path_mutable` x1 — cosmetic.

---

## [YOU] Step 4 — Enable R2, then I finish the off-site backups

R2 is **not enabled** on your Cloudflare account (`c0d5c842…`): the API returns *"Please enable R2
through the Cloudflare Dashboard."* One-time: **Cloudflare dashboard → R2 → Enable** (needs a payment
method on file even for the free 10 GB tier). Once on, tell me and I'll create the `nas-db-backups`
bucket + stage the nightly backup script; you'll only need to create the R2 **S3 API token**
(dashboard-only) and add the DSM Task Scheduler job. Full ready-to-deploy doc already written
(nightly `pg_dump`/`mysqldump`/`wrangler d1 export` → gzip → R2, 30-day retention, restore-test).

Why it matters: Neon free = **6h** PITR only; Supabase free has limited backups. R2 is the real
off-site retention.

---

## [YOU, LATER] Step 5 — Decommission (ONLY after cutovers verified for a few days)

Full list in the journal/analysis. Do **not** touch the 6 HOLD items until their cutover is proven:
`zqx-db`, `mcp-gateway-db` (keep as fallback), `gumtree-dev(-db)`, `modamarieclaire(-db)` (Lightsail
migration in flight). ~24 already-exited containers are safe to remove (≈0.8 GB data + ~14–16 GB
images); biggest reclaim = the retired self-hosted **supabase** stack (~6.5 GB) + `publisher`
orphan layers (~4 GB, confirm first — it wasn't in your active/retired lists).

---

## Reference — what's in `.env` now (deployer repo, gitignored)

- `SUPEBASE_CLOUD_ZQX_*` — connection string = **IPv4 Tokyo session pooler** (reachable from NAS),
  `SUPEBASE_CLOUD_ZQX_POOLER_HOST`, `SUPEBASE_CLOUD_ZQX_DB_PWD`, project id `xmklzncqgnuhxagsfeaq`.
- `NEON_VELOSOLABS_*` — project `proud-boat-42777651`, Singapore, db `velosolabs`, role
  `velosolabs_owner`, pooled + direct connection strings.
