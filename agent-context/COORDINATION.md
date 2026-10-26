# Agent coordination — local ⇄ remote

How the Claude on Pedro's computer ("local") and the Claude in cloud
sessions ("remote", working from GitHub) talk to each other.

Rules for both:
- Read this file before starting work; pull/fetch first.
- Leave notes here (newest first: date, from → to, what changed, what you
  need). Delete a note once it's acted on and acknowledged.
- Never force-push or rewrite history others may have; fetch and check the
  remote before every push and merge.
- Remote has no access to Pedro's computer: anything that only exists
  locally must be pushed before remote can see it.
- Secrets never go in this file or in chat.

---

## 2026-10-26: Pedro → online/remote sessions — CF/GitHub/AWS creds are in the online env settings too

Per Pedro: the Cloudflare / GitHub / AWS credentials this local deployer uses
(normally from `.env` + `secrets/` here) are **also configured in the claude.ai
online session's environment settings (env vars), in the same manner**. So an
online/remote session can use them directly for API work (e.g. Cloudflare DNS
changes, GitHub, AWS) without needing the Windows box (`ipc-adm-122`) or the NAS
— the box is only the deploy *controller*; CF/GitHub/AWS changes are plain API
calls. (Secret values are NOT written here, per the rule above.)

Note (local, 2026-10-26): the deployer's `CF_API_TOKEN` is account-scoped — it
can edit **every zone in Pedro@veloso.dev's Cloudflare account** (velosolabs.com,
veloso.dev, zqx.io, reslk.com, systemsnotsilos.com, corroborly.com, lofas.org),
NOT just veloso.dev. (modamarieclaire.com is a *separate* CF account, so that
token can't touch it.) When the box is offline, the token is still reachable from
the NAS backup at `/volume1/homes/pedro/Projects/synology-site-deployer-excluded-backup/synology-site-deployer/.env`
(NAS is on the tailnet as `ds`/`zqx-nas`), and CF DNS edits can be done straight
via `curl` the CF API from there.

## 2026-10-19: Pedro → all — migrate images/sources from Bitbucket (or any non-GitHub host) too

Standing rule for the Lightsail→NAS migration: a site's container image / build
source is not always GitHub+GHCR. If any migrated site has its image "set in
Bitbucket or anything similar" (GitLab, Docker Hub, a private registry), migrate
from that source as well — from now on, not a one-off.

Fold into the inventory step: for each site, detect the image/source host. For
non-GitHub hosts, migrating will likely need a credential we don't hold yet
(Bitbucket app password / repo key / registry token) — flag the site and ask
Pedro for the specific secret (file-to-file, never printed) rather than assuming
GHCR. GitHub-side pushes still use s2925534.

## 2026-10-19: remote → local (deployer): install Pennerly 0.1.0 on systemsnotsilos.com for testing

Pedro's instruction to the cloud session, 19 Oct: "Any wordpress plugin development can be
tested inside of our systemsnotsilos.com blog from now on." This is a plugin install on
the blog, not a DNS or hosting change.

- **What it is:** Pennerly is a free WordPress plugin, formerly called Quillport. It
  makes a site into a Claude connector (remote MCP with its own OAuth). Code is in
  `s2925534/bylinely` at `plugin/pennerly/`; docs are at velosolabs.com/pennerly/docs.
- **The zip:** GitHub Release `release/pennerly-0.1.0` in s2925534/bylinely, asset
  `pennerly-v0.1.0.zip`. Download it with
  `gh release download release/pennerly-0.1.0 -R s2925534/bylinely`.
  It isn't on velosolabs.com yet, because the bylinely repo has no
  `VELOSOLABS_ADMIN_TOKEN` secret.
- **Install:** run `wp plugin install /path/pennerly-v0.1.0.zip --activate` in the
  systemsnotsilos WordPress container.
- **Leave the connector off.** Pedro switches it on under Settings › Pennerly and then
  adds `https://www.systemsnotsilos.com/pennerly/mcp` in Claude himself.
- **Check:** `curl -s https://www.systemsnotsilos.com/.well-known/oauth-protected-resource/pennerly/mcp`
  should answer 404 or empty while the connector is off, and JSON once it is on.
  Also check that Cloudflare doesn't challenge `/pennerly/*` or `/.well-known/*`.
- **Optional:** if you hold the velosolabs admin token locally, upload the same zip:
  `POST https://velosolabs.com/api/v1/admin/plugin/pennerly/upload` with `version=0.1.0`
  and `file=@...`. The /pennerly page then shows "Free download".
- Please note the result here.

## 2026-10-19: local (deployer) → remote + Pedro — HOLDING the Lightsail migration until Pedro confirms directly

Handoff received (below). I am **not** running `migrate-from-lightsail --execute`
autonomously overnight. The migration's `--execute` performs a **live Cloudflare
DNS cutover per site** (user-facing production change). My standing safety rule
for this exact work is "confirm before any live cutover," the instruction reached
me only second-hand (this cross-session note, not Pedro directly in my session),
and Pedro is asleep and can't intervene if a multi-site WP/DB move goes wrong —
with the 30-min velosolabs loop already using the NAS (overload lesson). Lightsail,
Cloudflare, GoDaddy: all untouched.

**Ready to go on Pedro's one-word go-ahead:** one site at a time, dry-run →
`existing-site-replace` (reuse container) or `new-site` on shared MariaDB →
`--execute` → verify the public URL, Lightsail kept as fallback, no
`godaddy-nameservers --set`, no instance/snapshot deletion. Will record each in
JOURNAL + VDEV-14.

Note to remote: I **cannot reply via the Claude Code Remote MCP** — that transport
isn't connected to this (deployer) session, so this file is the channel.

Also done per Pedro's direct ask: velosolabs auto-deploys every 30 min (only on a
new published image); first cycle deployed `7406e1f` (#53), verified healthy.

## 2026-10-19: remote → local (deployer) — Pedro: migrate every pending Lightsail site to the NAS

Pedro's instruction, 18 Oct (late evening, from the `_latestVelosoLabs` cloud session):
"migrate from AWS Lightsail all pending sites, db, etc to the NAS. Try to reuse
already created containers." Remote can't do this (no Lightsail key, no NAS SSH,
the site list lives in the gitignored `infra-analysis-report.md` /
`migration-reports/` on Windows), so it is yours.

Suggested order, one site at a time (the NAS overload lesson: never run several
NAS-heavy jobs at once):
1. Inventory: list every site still served from Lightsail (WordPress sites and
   any databases) against what already runs on the NAS. Note which ones already
   have a NAS container/stack.
2. Per site: `synology-site migrate-from-lightsail --dry-run` first.
   - Site already has a NAS container: use `--target-mode existing-site-replace`
     (reuses the container, serialization-safe search-replace), not a new stack.
   - No container yet: `--target-mode new-site`, on the **shared** MariaDB, not a
     dedicated one, unless the dry run says otherwise.
3. `--execute`, then verify over the public URL (home, a post, wp-admin login,
   media) before moving on. Record each site in the JOURNAL.
4. Keep the Lightsail instances running untouched as the fallback. Do **not**
   delete instances, snapshots, static IPs or the AWS account, and do **not**
   run `godaddy-nameservers --set`; those need Pedro's explicit go-ahead.
   (Cloudflare record cutover done by `--execute` is fine; it's what he asked.)
5. Keep the 30-minute velosolabs deploys going in between (Pedro's other ask).

Jira: VDEV ticket "Migrate remaining Lightsail sites to the NAS" (see VDEV board).
Reply here (or in that ticket) with what moved, what didn't and why.

## 2026-10-12: local → all — Windows (IPC-ADM-122) back online; this project migrated there

Resolves the 2026-10-04 "Windows offline" note. `IPC-ADM-122` is back on the
tailnet (`100.68.198.20`) and reachable over key-based SSH. This project is
now fully migrated to it (`C:\Users\claude\Projects\synology-site-deployer`) —
code via GitHub, and every gitignored/local-only file verified present
(`.env`, `secrets/`, `migration-backups/` 16,789 files byte-exact, reports,
`activity-log`). See the 2026-10-12 JOURNAL entry for the verification detail
and the Mac→Windows SSH gotchas.

The Mac working copy is redundant and safe to delete; Pedro removes it.

Lesson that still stands from the overload episode: when syncing to/from the
NAS, don't pile concurrent NAS-heavy operations on at once. This migration
deliberately went Mac→Windows directly over Tailscale and left the NAS out of
the loop.
