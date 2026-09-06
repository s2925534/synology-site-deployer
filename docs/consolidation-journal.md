# NAS Container Consolidation — Journal

A running, detailed log of the container-consolidation effort across the veloso.dev /
systemsnotsilos / zqx / corroborly ecosystem on the Synology NAS (`192.168.1.109`).
Captures not just **what was done**, but **what was discussed, the options weighed, the
decisions made, and why**. Newest entries at the top. Committed at every meaningful checkpoint
(commit cadence = per meaningful change, not a timer).

Container count = fleet total (`docker ps -aq | wc -l`).

---

## 2026-09-06

### url-shortener → rebuilt on the zqx stack + deployed (Phases 1 & 2 done)

- **Decision (Pedro):** move the shortener off ResiLinked onto the **zqx stack** — same stack
  (NestJS 11 + Prisma 6), **share the zqx Postgres**, serve on **s.zqx.io** (s.reslk.com kept as
  alias until fully cut over). Rationale: the shortener is stateful (needs a DB); the DB-less hub
  was a bad fit, but zqx already runs Postgres → clean home, and the domain becomes s.zqx.io.
- **Phase 1 (code):** rebuilt Fastify/SQLite → **NestJS 11 + Prisma 6** (`feat/rebuild-on-zqx-stack`,
  PR #7 merged to `main`). Prisma targets the shared `zqx` DB isolated in a `shortener` schema
  (`?schema=shortener`). SQLite→Postgres migration script preserves short codes. Dockerfile switched
  `npm ci`→`npm install` (lockfile regenerated in the rebuild).
- **Phase 2 (live, on the NAS):**
  - Synced code to the NAS (SFTP disabled → `cat`-pipe transfer); preserved the old `data/shortener.db`.
  - Brought up **`zqx-db`** (was down; rest of the zqx stack stays down); created the `shortener`
    schema + a **least-privilege `shortener_app` role** (granted `CREATE ON DATABASE` — needed for
    Prisma's init `CREATE SCHEMA`; **hardening follow-up:** could revoke after init migration).
  - Built the image on the NAS (clean-FS build = the real gate; local build impossible under iCloud).
  - Migrated the 2 links incl. **`8GQJDb → veloso.dev`** (the signature target) — verified in Postgres.
  - Added **`s.zqx.io`** to the shared `veloso-nas` tunnel ingress (same Traefik target as
    s.reslk.com, inserted before the catch-all, all 44 rules preserved) + DNS CNAME (via CF API).
  - **Verified externally:** `s.zqx.io/8GQJDb` and `s.reslk.com/8GQJDb` both **302 → veloso.dev**;
    `/health` 200. The signature link is live again (was down before).
- **Phase 3 (pending):** repoint `SIGNATURE_URL` `s.reslk.com/8GQJDb` → `s.zqx.io/8GQJDb` across the
  sites, committed per-project. Not urgent — the signature already works via s.reslk.com.

### health-veloso-dev — retired (Pedro chose B1)

- **Decision:** Pedro picked **B1** from the earlier B-options (B1 retire · B2 fold `/health` · B3
  keep as canary). Rationale: it's the deployer's Flask **scaffold demo** — no source on disk,
  referenced nowhere, **no Traefik/public route** (LAN-only on host port 5052), so removing it
  breaks nothing.
- **Actions:** removed the container; retired its **volume1** dir →
  `/volume1/docker/health-veloso-dev.retired-20260906`; deleted its Kuma monitor
  (`health.veloso.dev`, 220 heartbeats + notification/tls links + the monitor row) so it doesn't
  sit red. Backups taken (`kuma.db.prehealthdel3-*`).
- **Gotcha (recorded for next Kuma DB edit):** Kuma's schema has a table named `group` (a SQLite
  reserved word) — `pragma table_info(group)` / `delete from group` fail unless the identifier is
  double-quoted. The delete script must quote table names and wrap per-table ops in try/except,
  else it aborts mid-way and never commits (happened twice before the quoted version worked).
- **Result:** fleet **45 → 44**; Kuma **36 → 35** monitors, restarted healthy.
- **Note:** volume1 is **not** fully clear yet — the `ecosystem-services` hub still deploys from
  `/volume1/docker/services-systemsnotsilos-com` (plus stale dirs: `p-veloso-dev`,
  `systemsnotsilos-com`, `hdd-db-fix`, `swap-fix`, `zqx-api-migrate`). Moving the hub off volume1
  is a separate item.

---

## 2026-09-05

### Goal & approach
Reduce NAS container count by folding **small, same-language, stateless** backends into the shared
`ecosystem-services` "hub" (Node/Express, stateless, per-site API keys), and by combining
duplicates — while **minimizing containers without compromising code quality or performance**. A
service is a clean fold only if it's the hub's language (JS/TS) **and** stateless (or on shared
Supabase). Anything with its own datastore, a different language needing a rewrite, or that's a
full product, is not a drop-in.

### Decisions & rationale (the discussion)

- **Fold tracktrace → hub.** Discussed: it's a stateless parcel-tracking relay, no DB/secrets.
  Decision: port TS→CommonJS as a hub module (`/api/track` + host-aware static for
  `track.systemsnotsilos.com`). Clean fold. **Done.**
- **Fold contact-relay → hub.** Discussed: the SSO login-page contact form duplicated the hub's
  existing `/api/contact` mailer. Decision: retire it via **config only** (register a
  `systemsnotsilos-sso` site, repoint the Authentik `flow.html`), no new hub code. **Done.**
- **Exclude zqx.io** (Pedro's call). Keep zqx on its own dedicated container(s) even though
  `zqx-site`/`portal`/`control`/`connect` share one image (an obvious 4→1 collapse). Why: he wants
  zqx as a standalone project. **Off-limits.**
- **Exclude ResiLinked / reslk.com** (Pedro's call). Keeps its own stack.
- **url-shortener — carve-out from ResiLinked.** Pedro approved moving it out of ResiLinked toward
  the hub, provided `s.reslk.com` keeps working; eventual alias decided = **`s.zqx.io`**.
  Investigation verdict: **BLOCKED for a clean fold** — it's TS/Fastify with its **own SQLite DB
  (Prisma, volume)**; the hub is DB-less. Options: **A1** rewrite storage → shared Supabase then
  fold (careful migration of live links); **A2** leave standalone, just decoupled. **Pending
  Pedro's A1/A2 pick.**
- **addr.systemsnotsilos.com — leave as-is** (Pedro: if too heavy, leave + record). Verdict:
  architecturally incompatible — 5-container stack, third-party `mountainpass/addressr` image,
  OpenSearch (stateful JVM). Can't fold into a Node hub. **Recorded for future.**
- **velosolabs.com identity.** Pedro said the veloso hub "moved to velosolabs.com"; the dir was
  mislabeled. Confirmed: `veloso-plugin-hub` **is** "Veloso Labs" (velosolabs.com) — a **dynamic
  Python** (FastAPI + SQLite + RS256 licensing + Lemon Squeezy payments + portal). Therefore it is
  **not** a static frontend host and **can't** fold into the hub; it stays standalone. Renamed for
  clarity (local dir + GitHub repo + GHCR image via byte-identical retag). Live domain
  `velosolabs.com` confirmed serving; the marker's `hub.veloso.dev` was stale (no public DNS).
- **Frontend consolidation — GATED.** Pedro: tell me which frontends can combine *before* merging
  any. A single host-aware static container could serve **veloso.dev** (static, drop-in) and
  **corroborly.com** (static content but Next SSR → needs `output:"export"` first) and possibly
  **lofas.org** (Pedro says static, but its deployment is Astro SSR **and no source repo was
  located** — needs the repo + conversion). velosolabs is NOT this container (it's a dynamic
  backend). Pedro's suggestion validated: corroborly *frontend* → combined static container;
  corroborly *backend* → services (the marketing site actually has no backend; the real app is the
  separate dynamic `ResearchBoss`). Options: **F1** veloso.dev only · **F2** +corroborly.com ·
  **F3** +lofas.org. **Pending Pedro's pick + lofas repo path.**
- **`services2` (a Python hub) — deferred.** Pedro suggested a Python equivalent of the hub for
  Python backends. Investigation: the only live Python HTTP services (velosolabs, career-hub,
  ResearchBoss/corroborly) are all **stateful products** — zero small stateless candidates. A hub
  now would be empty. **Deferred until 2–3 stateless Python services exist.**
- **uptime-kuma 2→1 — merged.** Two identical Kuma instances; merged the 30 site-monitors +
  notification (push token preserved) from `-sites` into the survivor via a Python `sqlite3` merge
  (backup first). **Done.**
- **health-veloso-dev.** It's the deployer's Flask scaffold **demo** (no source on disk, referenced
  nowhere). Options: **B1** retire (−1, clears volume1) · **B2** fold `/health` into the hub then
  retire · **B3** keep as an independent canary. Leaning B1. **Pending.**
- **Naming cleanup.** Renamed local dirs: `nas-sso-gateway.`→`nas-sso-gateway`,
  `WPAIPoster`→`wp-ai-poster`, `veloso-plugin-hub`→`velosolabs`. Ambiguous, **pending Pedro**:
  `ResearchBoss` and `corroborly` both point at `corroborly.git` (which is canonical?);
  `wp-ai-poster` (plugin) vs `wordpress-ai-publisher` (app) — disambiguate?
- **Don't move repos off iCloud for now** (Pedro). So the git-hang workarounds stay in play.
- **Commit cadence.** "Commit every hour" clarified = **commit at every meaningful checkpoint**,
  not a timer. An hourly launchd script was built then **removed**.

### Actions completed (fleet 48 → 45 containers)
- tracktrace → hub; container + repo retired (`Retired-tracktrace`; local `Retired-TrackAndTrace`).
  PR #3 (ecosystem-services) test-gated in CI, merged, deployed, Traefik route added, verified.
- sso-contact-relay → hub `/api/contact`; `flow.html` repointed; nas-sso-gateway service/CI/dir
  removed (PR #4 merged to main); container retired; wiring verified (authed 400 reCAPTCHA / 401).
- uptime-kuma-sites → uptime-kuma (36 monitors); second instance retired.
- velosolabs rename: local dir + GitHub repo (`veloso-plugin-hub`→`velosolabs`, redirects; git
  read+write verified) + GHCR image (retag, byte-identical); NAS compose repointed; healthy;
  velosolabs.com serving.
- Naming: `nas-sso-gateway.`, `WPAIPoster` local dirs renamed.
- This journal + PROJECT_STATE.md Notes pointer established (journal committed to main).

### Pending decisions (options menu for Pedro)
1. **url-shortener**: ✅ RESOLVED — rebuilt on the **zqx stack** (NestJS+Prisma, shared zqx Postgres), deployed, `s.zqx.io` + `s.reslk.com` live (see 2026-09-06 entry). Only Phase 3 (signature repoint) remains.
2. **health-veloso-dev**: ✅ RESOLVED — B1 (retired 2026-09-06). See the 2026-09-06 entry.
3. **Frontend combined static container** (gated): F1 veloso.dev · F2 +corroborly.com · F3 +lofas.org.
   Needs the **lofas repo path**.
4. **Naming clarify**: ResearchBoss vs corroborly (canonical?); wp-ai-poster vs wordpress-ai-publisher.
5. velosolabs domain cutover already effectively done (velosolabs.com live).

### Leftovers (harmless)
- Old GHCR package `ghcr.io/s2925534/veloso-plugin-hub` orphaned.
- Dead `CONTACT_*` vars in NAS SSO `.env`; stray `README 2.md` (untracked) in nas-sso-gateway.
- gh active account drifts to `zqxdeveloper` (must be `s2925534` for pushes).
- NAS project dir/marker still `hub-veloso-dev` / `hub.veloso.dev` (cosmetic; container serves velosolabs.com).

<!-- Add new dated entries above this line. -->
