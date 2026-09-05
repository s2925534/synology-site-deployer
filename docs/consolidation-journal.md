# NAS Container Consolidation — Journal

A running, detailed log of the container-consolidation effort across the veloso.dev /
systemsnotsilos / zqx / corroborly ecosystem on the Synology NAS (`192.168.1.109`).
Newest entries at the top. Auto-committed hourly by a launchd agent (see the end of this file);
also committed manually at meaningful checkpoints.

Container count is tracked as the fleet total (`docker ps -aq | wc -l`).

---

## 2026-09-05

### Session summary — fleet 48 → 45 containers, plus repo/naming cleanup

**Backend folds into the `ecosystem-services` hub (Node/Express, stateless, per-site API keys):**
- **tracktrace → hub.** Ported TrackAndTrace (TS) parcel-tracking relay to CommonJS under
  `src/track/` (detection, checksum, canada-post + correios adapters, TTL cache). Added public
  `GET /api/track` + host-aware static so the hub also serves `track.systemsnotsilos.com`. PR #3
  merged; CI test-gated + published image; deployed; Traefik route added; verified end-to-end.
  `tracktrace` container + NAS dir retired; repo retired → `Retired-tracktrace` (local
  `Retired-TrackAndTrace`).
- **sso-contact-relay → hub (config only).** It duplicated the hub's existing `/api/contact`
  mailer. Registered `systemsnotsilos-sso` site in `sites.json`; added its API key + reCAPTCHA
  (reusing the `systemsnotsilos` pair) to the hub `.env`. Repointed the Authentik login-page
  contact form (`flow.html`) to the hub. Removed the contact-relay service/CI/dir from
  `nas-sso-gateway` (PR #4 merged to main). Container retired. Verified: authed SSO-origin
  `/api/contact` → 400 reCAPTCHA (auth+CORS OK), no-auth → 401.

**Monitoring merge:**
- **uptime-kuma-sites → uptime-kuma.** Merged the 30 site-monitors + 1 notification (+30 links,
  push token preserved) from the `-sites` SQLite DB into the survivor via a Python `sqlite3`
  script (backup taken first). Survivor started with 36 monitors, actively monitoring. Second
  instance container + dir retired.

**Naming / repo cleanup:**
- Local dir renames: `nas-sso-gateway.` → `nas-sso-gateway`; `WPAIPoster` → `wp-ai-poster`;
  `veloso-plugin-hub` → `velosolabs`.
- **velosolabs (formerly veloso-plugin-hub)**: GitHub repo renamed `veloso-plugin-hub` →
  `velosolabs` (old URL redirects; git read+write verified). Image renamed by **retagging the
  exact running image** → `ghcr.io/s2925534/velosolabs:latest` (no rebuild — byte-identical, safe
  for this payments/licensing service). NAS compose image ref updated; container recreated,
  healthy. Confirmed the live domain is **velosolabs.com** (200, "Veloso Labs — small, sharp
  software"); the marker's `hub.veloso.dev` was stale (no public DNS).

**Investigations (verdicts):**
- Backend fold candidates: `url-shortener` BLOCKED (TS/Fastify + own SQLite); `health-veloso-dev`
  trivial REWRITE (Flask scaffold demo, no source on disk); `veloso-plugin-hub`/velosolabs,
  `wordpress-ai-publisher` BLOCKED (stateful products). Only tracktrace was a clean fold.
- Frontend static-consolidation candidates: `veloso.dev` STATIC (drop-in); `corroborly.com`
  static content but Next SSR (needs `output:"export"`); `lofas.org` static content but Astro SSR
  build **and no source repo located**; `velosolabs`/hub.veloso.dev and corroborly app
  (ResearchBoss) stay dynamic.
- `services2` Python hub: PREMATURE — the only live Python HTTP services (velosolabs, career-hub,
  ResearchBoss/corroborly) are all stateful products; no small stateless candidates exist.
- `addr.systemsnotsilos.com`: architecturally incompatible with the hub (5-container stack,
  third-party `addressr` image, OpenSearch) — stays as-is.

**Decisions recorded (memory):**
- Exclusions: zqx.io and ResiLinked stay dedicated. `url-shortener` carved out of ResiLinked —
  may move toward the hub, must keep `s.reslk.com` working; eventual alias **`s.zqx.io`**.
- Retired-repo convention: rename local dir + GitHub remote to start with `Retired`.

### Pending decisions (queued for Pedro)
- **url-shortener**: A1 rewrite storage→Supabase then fold (−1) · A2 leave standalone. Alias `s.zqx.io`.
- **health-veloso-dev**: B1 retire (scaffold demo; −1, clears volume1) · B2 fold `/health` · B3 keep as canary.
- **Frontend combined static container** (gated): F1 veloso.dev · F2 +corroborly.com · F3 +lofas.org. Needs lofas repo path.
- **velosolabs**: repo/image/domain rename — DONE. NAS project dir + marker still named `hub-veloso-dev` (cosmetic).
- **naming**: `ResearchBoss` vs `corroborly` both point to `corroborly.git` — clarify canonical; `wp-ai-poster` (plugin) vs `wordpress-ai-publisher` (app) — disambiguate?

### Leftovers (harmless)
- Old GHCR package `ghcr.io/s2925534/veloso-plugin-hub` orphaned.
- Dead `CONTACT_*` vars in NAS SSO `.env`; stray `README 2.md` in nas-sso-gateway.
- gh active account keeps reverting to `zqxdeveloper` (must be `s2925534` for pushes).

---

### 2026-09-05 — journaling + commit cadence settled

- This journal (`docs/consolidation-journal.md`) is committed to `main`; the `.claude/PROJECT_STATE.md`
  Notes section points here (that file is gitignored/local per the project-state skill).
- **Commit cadence:** "commit every hour" was clarified to mean **commit at every meaningful
  checkpoint** — not a timer. The earlier hourly launchd script/plist was built then **removed**;
  no daemon. Journal is updated + committed alongside each meaningful change. See
  [[consolidation-journal-and-commit-cadence]].

<!-- Add new dated entries above this line. -->
