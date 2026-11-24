# Database consolidation → Neon + AWS only (no Supabase), AU residency, meaningful names

Prepared 2026‑11‑24. Owner goals: **drop Supabase entirely**, run on **Neon + AWS only**, **minimal cost
(~$0)**, **Australian data residency** (Sydney; offshore only if AU unavailable), and **meaningful DB names**
(see [[db_naming_convention]] — never random word-mixes; rename keepers, delete unused).

## Why
- Supabase **Free pauses after ~7 days idle** (unreachable until restored) → bad for availability/SOC2.
- Neon **Free scales-to-zero but never pauses** (auto-resume ~hundreds of ms) → better free option.
- Tangled accounts/regions: 2 Neon projects both named "VelosoLabs"; a Supabase org named "VelosoLabs"
  holding ZQX projects; the **live** gateway DB sits in **Singapore** (not AU) on a project a Confluence note
  wrongly marked "pending delete".

## Verified current state (2026‑11‑24)
**Neon — org "Pedro" (`org-twilight-king-90804298`, free):**
| Project (ID) | Region | Role now |
| --- | --- | --- |
| `proud-boat-42777651` (display "VelosoLabs") | **Singapore** ap‑se‑1 | 🟢 LIVE gateway DB (`velosolabs`): tenants, app_grants, connectors |
| `old-pond-55634779` (display "VelosoLabs") | Sydney ap‑se‑2 | idle ~31 MB — stale/abandoned migration target |
| `red-dew-92020820` (display "velosolabs-sso") | Sydney | SSO/IdP store, **~30 MB data**, archived/cold |

Neon — org "Appui" (`org-odd-sky-13372426`, Ben's): `royal-rice-47327848` (US‑East) — sprigboard; Pedro EDITOR. Out of scope.

**Supabase:**
| Project | Region | Role now |
| --- | --- | --- |
| `pocefahesgwsugicjtgw` | Sydney | 🟢 LIVE zqx prod (`zqx_owner`/`zqx_app`) — `zqx-api` connects here |
| `xmklzncqgnuhxagsfeaq` | Tokyo | 🔴 empty stale copy (0 MB), nothing live uses it |
| self-hosted (NAS `supabase-*`) | NAS | ResiLinked (dormant) — uses Supabase **Auth + Storage**, not just Postgres |

zqx **staging** uses the local `zqx-db` container on the AWS box (not Supabase).

## Target architecture (no Supabase)
| Need | Home | Cost |
| --- | --- | --- |
| Managed Postgres | **Neon, Sydney** (scale-to-zero, PITR on paid) | $0 free |
| Compute | AWS Lightsail box | $0 extra |
| Local DBs (WP, staging) | Postgres/MariaDB on the box | $0 |
| Object storage (replaces Supabase Storage) | **Cloudflare R2** | $0 free |
| Auth (replaces Supabase Auth) | **velosolabs hub OIDC** ([[reuse_shared_auth_sso_mcp]]) | $0 |

### Naming (meaningful; created/renamed during the work)
| Purpose | Neon project (display) | database | role |
| --- | --- | --- | --- |
| velosolabs hub | `velosolabs-hub` | `hub` | `hub_owner` |
| velosolabs gateway | `velosolabs-gateway` | `gateway` | `gateway_owner` |
| velosolabs SSO/IdP | `velosolabs-sso` | `sso` | `sso_owner` |
| zqx prod | `zqx-prod` | `zqx` | `zqx_owner` / `zqx_app` |
| zqx staging | `zqx-staging` (local box container) | `zqx_staging` | `zqx_owner` |

Caveat: Neon/Supabase keep an **immutable internal slug + endpoint host** (the random part in the connection
string) we can't rename; everything human-facing (display name, db, branch, role) we make meaningful. New
projects created with chosen names start clean.

## Sequenced migration (no destructive step without Pedro's go)
1. **Tokyo Supabase `xmklz` → delete.** Verified empty + unused. ⚠️ Deletion must be done by **Pedro in the
   Supabase dashboard** (our stored access token is invalid). Accompanying cleanup DONE this session (below).
2. **Gateway: Singapore → Sydney.** Create Neon Sydney project **`velosolabs-gateway`** (db `gateway`), dump
   `proud-boat`→restore, repoint gateway `GATEWAY_DATABASE_URL`, verify healthz, then **delete `proud-boat`**
   (Singapore) and the stale **`old-pond`** (after confirming it holds no unique data).
3. **velosolabs hub: SQLite → Neon Sydney `velosolabs-hub`** (db `hub`). App already supports `DATABASE_URL`
   (psycopg3 bundled). Import the real NAS `hub.db` data (5→3 real accounts, 3 tenants, 2 licenses, passkeys;
   drop the 2 junk unverified signups). Then the hub stops being on SQLite.
4. **zqx prod: Supabase Sydney `pocefah` → Neon Sydney `zqx-prod`** (db `zqx`). zqx is Prisma/Postgres;
   `pg_dump`→restore→swap `DATABASE_URL`. ⚠️ VERIFY FIRST zqx uses only plain Postgres (no Supabase
   Auth/Storage/Realtime/PostgREST). Then **delete the Supabase Sydney project**.
5. **SSO `red-dew`: rename db → `sso`** (and role) — do this *with* wiring its consumer so the connection
   string updates in lockstep (not standalone; it has 30 MB of crown-jewels data).
6. **ResiLinked (dormant):** when revived, DB→Neon, **Auth→hub OIDC**, **Storage→R2**; decommission the NAS
   self-hosted Supabase stack. The one genuine "de-Supabase" rework (it depends on Supabase Auth/Storage).
7. **Close the Supabase account(s)/org(s)** once everything is off. ⚠️ Check the Supabase **org switcher**
   first: if the login owning the Tokyo org also owns the Sydney `pocefah` org, do not close the account until
   after step 4.

## Cost
Target **$0** (Neon free + existing box + R2 free). Only likely paid item: put **just zqx-prod** on **Neon
Launch (~$19/mo)** if it must never cold-start or needs managed PITR. Everything else free.

## Verify before executing (read-only)
1. Does zqx use any Supabase-only features, or just plain Postgres? (determines step 4 difficulty)
2. zqx prod DB size (free-tier fit; free-vs-paid).
3. Does idle `old-pond` (Sydney) hold any unique data, or is it a discardable stale copy?
4. Supabase **org switcher**: is the Tokyo org's login the same account that owns Sydney `pocefah`?

## Done this session (2026‑11‑24)
- ✅ Repointed `.mcp.json` Supabase MCP connector from Tokyo `xmklz` → live Sydney `pocefahesgwsugicjtgw`
  (so deleting Tokyo won't orphan it).
- ✅ Removed the stale `SUPEBASE_CLOUD_ZQX_*` block (6 vars, Tokyo) from the deployer `.env`
  (backup `.env.bak-predbcleanup-20261124`). Only a harmless comment reference remains.
- ⏳ Tokyo Supabase project deletion itself — **waiting on Pedro** (dashboard; dead token).
- Deferred: SSO db rename (step 5, do with its consumer).
