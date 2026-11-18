# systemsnotsilos → off the NAS (clean rebuild onto the AWS box)

Prepared 2026-11-18 while the NAS is offline. Combines the **clean rebuild** (incident 2026-11-16) with the
**move off the flaky NAS** in one operation — rebuild systemsnotsilos CLEAN directly on the AWS box so it
leaves the NAS entirely (the last important thing on it). Ready to run once the NAS is reachable again.

## Context / where it stands
- systemsnotsilos.com WP was compromised (owned ~2.5 months); **contained** (web container stopped, restart=no;
  backdoors already eradicated by the earlier rebuild pass: `wp-compat-*`, `aGt`, `wp-file-manager`,
  mu-plugins loaders removed; `active_plugins` emptied). Forensic snapshot taken (`forensics-20261118-…`).
- Social plugin = **`wp-ai-poster`** (Pedro's own), config in `wp_options` (`wpaip_settings`) — **preserve**.
- All rotated creds already wired into the NAS `.env` (see below). No Jetpack involved.

## Prerequisite (blocking)
- **NAS reachable via SSH** to extract the cleaned `wp-content` + DB. (Currently DOWN — tunnel `veloso-nas`
  0 conns, SSH LAN+Tailscale timing out. Recover first: LAN/physical → `nas-docker-autorecover.sh`, and ensure
  Docker + cloudflared + Tailscale restarted.)

## Target
- **AWS Lightsail `velosolabs-prod`** (Sydney), **$0 extra** — same pattern as hub/gateway/zqx.
- `wordpress:latest` container (fresh core) + DB as a new `systemsnotsilos` database on the **existing box
  `mariadb` container** (no new DB container). Compose project `systemsnotsilos` in `~/systemsnotsilos/`.
- Served via the **`velosolabs-aws` tunnel** (`98135949-…`); add `systemsnotsilos.com` + `www` ingress.

## Steps (run top-to-bottom once NAS is up)
1. **Extract from NAS (read-only):** `mysqldump` the cleaned `systemsnotsilos` DB from `systemsnotsilos-com-db`;
   `tar` the cleaned `wp-content` (uploads, active theme, the legit `wp-ai-poster` plugin, `sso-loader.php`
   mu-plugin) **excluding** the already-removed backdoors. Stream both over SSH → box (scp is disabled).
2. **Fresh WP on box:** bring up `wordpress:latest` mounting ONLY the extracted clean `wp-content`; generate a
   fresh `wp-config` (new salts); DB → box `mariadb`, new `systemsnotsilos` DB + new DB user/password.
3. **Import content:** create the DB, load the dump.
4. **Finalize in DB (wp-cli):** delete the 3 rogue admins (`root_*`, `fwefwefi@mail.com`); create the
   `pedro@veloso.dev` admin (strong pw); reassign content authorship; confirm `active_plugins` = legit only
   (`wp-ai-poster` + required); scrub any residual injected `wp_options`.
5. **Wire creds** into the box env / `wp_options`: Mailjet subaccount (`68bf…`), `WPAIP_OPENAI_KEY`
   (SystemsNotSilos key), `GITHUB_SYNC_TOKEN` + `GITHUB_SYNC_WEBHOOK_SECRET`, reCAPTCHA (when Pedro provides) +
   the other wp-ai-poster provider keys (when provided). Set `siteurl`/`home` = `https://systemsnotsilos.com`.
6. **Tunnel ingress:** add `systemsnotsilos.com` + `www.systemsnotsilos.com` → the box WP container (CF API;
   tunnel `98135949-…`, acct `c0d5c842…`).
7. **Verify (pre-flip):** on a temp hostname / internal curl — site loads, admin login works, NO backdoors,
   `wp-ai-poster` config intact, content present, no rogue users.
8. **DNS cutover (Pedro's go):** flip `systemsnotsilos.com` + `www` CNAMEs → box tunnel (`98135949-…`). NOTE:
   `services.systemsnotsilos.com` + `track.systemsnotsilos.com` already run on the CF compat-proxy/track-worker
   — untouched; this is the main WP site only.
9. **Decommission NAS:** the NAS `systemsnotsilos-com` + `-db` stay stopped (already); remove later.

## Creds status
- ✅ ready/rotated: Mailjet subaccount, `GITHUB_SYNC_TOKEN`, webhook secret, `WPAIP_OPENAI_KEY` (SystemsNotSilos);
  DB pw + WP salts generated fresh during the rebuild.
- ⏳ from Pedro (site works without; features light up when added): **reCAPTCHA** (site+secret), wp-ai-poster
  providers (Anthropic, SerpAPI, Scopus, Google CSE, Semantic Scholar + license).

## Risks / notes
- **Box RAM** (4 GB; hub+gateway+zqx already there). WP+DB ≈ 0.6–1 GB — check headroom at run; trim or resize if tight.
- Reuse the box `mariadb` (don't stand up a second DB engine).
- Keep `wp_options` `wpaip_settings` intact (preserves wp-ai-poster config) through the DB import.
- **Rollback:** NAS systemsnotsilos containers kept (stopped) — could restart + flip DNS back, though the NAS's
  flakiness is the reason we're leaving it.
