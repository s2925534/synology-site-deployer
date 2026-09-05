# NAS Container Consolidation — Journal

A running, detailed log of the container-consolidation effort across the veloso.dev /
systemsnotsilos / zqx / corroborly ecosystem on the Synology NAS (`192.168.1.109`).
Captures not just **what was done**, but **what was discussed, the options weighed, the
decisions made, and why**. Newest entries at the top. Committed at every meaningful checkpoint
(commit cadence = per meaningful change, not a timer).

Container count = fleet total (`docker ps -aq | wc -l`).

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
1. **url-shortener**: A1 rewrite→Supabase+fold · A2 standalone. Alias `s.zqx.io`.
2. **health-veloso-dev**: B1 retire · B2 fold `/health` · B3 keep.
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
