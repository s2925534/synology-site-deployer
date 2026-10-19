# synology-site-deployer: session journal

Curated, newest-first record of what each session or notable commit did,
and why. Committed in-repo so it travels with a clone: a checkout on any
machine, or a remote Claude session working from GitHub, gets the working
context without anyone's local `~/.claude` state.

This is the curated half of a two-tier journal. The verbatim half,
`agent-context/journal-verbatim/VERBATIM_INDEX.md`, is gitignored: the
tracked `.githooks/post-commit` hook appends one row per commit (hash,
subject, time, newest local transcript) and prints a reminder to add an
entry here.

Each entry: what changed, why, and what a future session should know before
touching the same area. Use judgement; record decisions, milestones and
gotchas, not every mechanical commit.

See also `agent-context/COORDINATION.md` for open notes between local and
remote sessions.

---

## 2026-10-19: FIXED the live modamarieclaire.com 500 at source (WooCommerce core restored); NAS staging paused

**Live site fix (the win):** www.modamarieclaire.com was returning 500 (store DOWN).
Root cause: a WooCommerce 10.1.2 auto-update failed mid-install — WordPress had
deleted the old `wp-content/plugins/woocommerce/` core dir but never moved the new
one into place, so the ~20 WooCommerce EXTENSION plugins (smart-coupons, payments,
stripe, …) stayed active and called `WC()` against a missing core -> fatal
("Call to undefined function WC()") on every request. The correct version was
already staged on the box at `wp-content/upgrade/woocommerce.10.1.2/woocommerce`.
Fix: `cp -a` it into `plugins/woocommerce` + `chown -R www-data:www-data` (no
external download). Live site recovered: /, apex, /shop/, /wp-login.php all 200.
NOTE: WooCommerce may now show a "database update required" admin notice (DB was at
the pre-10.1.2 schema); the FRONTEND works, but someone should run the WC DB update
from wp-admin when convenient. The on-box `upgrade/woocommerce.10.1.2` copy was left
in place as a fallback. This is a WRITE to the live Lightsail source (Pedro asked
me to "fix it yourself before migration") — the one deliberate exception to the
otherwise read-only Lightsail stance.

**NAS staging (modamarieclaire.veloso.dev): PAUSED, data staged, not serving.**
Pedro's call. Project `modamarieclaire-veloso-dev`: WP + dedicated MariaDB up,
DB restored (wp_ prefix), 4.6G wp-content (uid 33), siteurl/home set to the
staging URL, Cloudflare route created. It does NOT serve because (a) its
wp-content was migrated BEFORE the source fix, so it has the same missing-WC-core
500, and (b) a routing mismatch: migrate new-site publishes a host port (5054:80)
unreachable on the host -> tunnel returns 502; the NAS's working sites use the
shared supabase_default net + Traefik instead. To finish later: re-sync the
now-fixed wp-content (or drop WooCommerce 10.1.2 into the staged copy) + rework
routing onto Traefik + full wp search-replace + DNS cutover.

Staged state (NAS project `modamarieclaire-veloso-dev`): WP + dedicated MariaDB
containers up; migrated DB restored (wp_ prefix); 4.6G wp-content extracted,
owned uid 33 (www-data); `siteurl`/`home` set to https://modamarieclaire.veloso.dev;
Cloudflare route `modamarieclaire.veloso.dev` -> http://192.168.1.109:5054 created.

Two blockers stop it serving:
1. **WP returns 500 even in-container** (`docker exec … curl localhost:80` -> 500) —
   the SAME 500 `www.modamarieclaire.com` throws on Lightsail. The site was already
   broken; carried over. Needs WP_DEBUG + bisecting a ~60-plugin WooCommerce store.
2. **Routing mismatch**: migrate new-site publishes a host port (5054:80) on a
   standalone network, but that port is unreachable on the host (127.0.0.1:5054 ->
   000), so the tunnel -> 192.168.1.109:5054 returns 502. Every working NAS site
   uses the shared `supabase_default` net + Traefik via the tunnel, not host-port
   publish. The migrate tool produces the wrong pattern for this NAS.

Tool bugs hit this run (for a proper hardening pass later):
- FIXED + committed (c9e4f45): new-site didn't pre-create ./wp-content, so compose
  up failed the bind mount.
- `--target-workspace <name>` is only validated on --execute (dry-run accepts bad values).
- new-site defaults to shared MariaDB (`shared-mariadb`) which isn't running here ->
  use `--target-db-mode container`.
- wp-content push writes host-side as the SSH user, but the WP container owns
  wp-content (www-data) -> permission denied. Worked around manually (tar-stream +
  chown 33:33). The tool should push via docker exec as www-data (it has
  push_wp_content_to_volume for exactly this).
- new-site routing uses host-port publish, not the NAS's tunnel/Traefik pattern.
- No DB URL search-replace when target-domain != source-domain (did siteurl/home by
  hand; a full serialized wp search-replace still needed for a real cutover).

To resume (make modamarieclaire live): debug the WP 500 -> rework routing onto
supabase_default+Traefik -> full wp search-replace -> then DNS cutover. Logged for
VDEV-14. Transfer tip that worked: tar-stream wp-content Lightsail->NAS directly
(`ssh lightsail "sudo tar czf - -C <docroot> wp-content" | ssh nas "cat > f.tgz"`),
then extract into the container's bind-mount and `chown -R 33:33`.

Lightsail still NOT deletable: modamarieclaire.com (live, on Lightsail) + the
veloso.au/veloso.com.au redirects still point there.

## 2026-10-19: redeployed velosolabs -> eb3d4e6

Pedro asked to redeploy latest; main at `eb3d4e6`, running was f6b5e88.
Confirmed :latest==eb3d4e6 by digest, deployed (rc=0), /health 200.
(Also added PAYPAL_SANDBOX_CLIENT_ID/SECRET to the NAS prod .env + Windows
mirror earlier this session; take effect on next recreate.)

## 2026-10-19: redeployed velosolabs -> f6b5e88 (#59)

Pedro asked to redeploy latest; main at `f6b5e88` (#59), running was b200cbf.
Confirmed :latest==f6b5e88 by digest, deployed (rc=0), /health 200, / 200.

## 2026-10-19: redeployed velosolabs -> b200cbf (#58 admin fix)

Pedro asked to redeploy latest; main at `b200cbf` (#58 fix/admin), running was
8955b5b. Confirmed :latest==b200cbf by digest, deployed (rc=0), /health 200.

## 2026-10-19: fixed migrate/new-site wp-content bind-mount ordering bug (create.py)

The lightsail migration (and any `wordpress` new-site) failed: `docker compose up`
in `create_site` errored `Bind mount failed: .../wp-content does not exist`. Cause:
`_prepare_remote_project` only pre-created `./data` for flask, not `./wp-content`
for wordpress, but `wordpress_compose.yml.j2` bind-mounts `./wp-content` — and the
migration's `push_wp_content` only creates it AFTER the stack is up. Docker won't
start a container whose bind-mount source is missing.

Fix: create `{project}/wp-content` in `_prepare_remote_project` when
framework == "wordpress" (same one-liner + reasoning as the existing flask `./data`
case). Fresh new-site gets an empty dir the WP image populates; the migration fills
it live afterwards. This unblocks `migrate-from-lightsail` for WordPress and fixes
plain `new-site wordpress` deploys too.

Found while staging modamarieclaire.com -> modamarieclaire.veloso.dev (3rd failure;
first was a bad --target-workspace, second was shared-mariadb not running -> switched
to --target-db-mode container). Re-running the stage after this fix.

## 2026-10-19: redeployed velosolabs -> 8955b5b (#57 paypal fix)

Pedro asked to redeploy latest; main at `8955b5b` (#57 fix/paypal-reco),
running was 856ac3d. Confirmed :latest==8955b5b by digest, deployed, verified
running revision 8955b5b, /health 200.

## 2026-10-19: Lightsail delete-readiness audit (read-only) — NOT safe to delete yet

Pedro wants to delete the Lightsail box (54.79.130.10, workspace veloso-dev,
shared instance) but only once everything's live elsewhere. Read-only audit
(SSH with secrets/veloso-dev/lightsail-ssh-key.pem + public DNS/HTTP; nothing
changed on Lightsail/Cloudflare/GoDaddy):

Still DEPENDS on Lightsail (DNS points directly at 54.79.130.10):
- **modamarieclaire.com + www** — live WordPress at /var/www/html/modamarieclaire/
  production/ (wp-config, wordfence, WooCommerce feeds). No NAS container. NOT
  migrated. `www` currently 500s. -> migrate (new-site, WP+DB) then repoint DNS.
- **veloso.au / www.veloso.au / veloso.com.au / www.veloso.com.au** — 301 redirect
  to veloso.dev, served by Lightsail. -> repoint DNS (needs Pedro's go-ahead).

Already OFF Lightsail (safe): veloso.dev/www/p./blog.veloso.dev and
systemsnotsilos.com/www all resolve to Cloudflare -> NAS (containers p-veloso-dev,
systemsnotsilos-com up). gumtree.dev and risefortruth.com DNS point to GoDaddy/AWS
forwarding (15.197/3.33, 76.223/13.248), not this box -> their Lightsail vhosts/
files are stale leftovers, deleting won't affect them.

Gotcha: the box's nginx vhosts list many domains (veloso.dev vhost even names
systemsnotsilos.com, veloso.com.au, veloso.au) — vhost presence means nothing;
only live DNS does. Check `dig` per hostname vs 54.79.130.10, not nginx config.
No AWS CLI on Windows, and sudo mysql needs creds, so DB list wasn't pulled.

## 2026-10-19: redeployed velosolabs -> 856ac3d (#56 licence-two-way-revoke)

Pedro asked to redeploy; main was at `856ac3d` (#56 licence-two-way-revoke),
running was `20aa082`. Confirmed `:latest`==`856ac3d` by digest, deployed,
verified running revision `856ac3d`, /health 200, / 200.

## 2026-10-19: auto-deploy loop — velosolabs 7406e1f -> 20aa082

Loop cycle (cron 4d437aa8): main advanced to `20aa082` (running was `7406e1f`);
confirmed `:latest`==`20aa082` by digest, deployed (pull + up -d --remove-orphans),
verified running revision `20aa082`, /health 200.

## 2026-10-19: velosolabs 30-min auto-deploy loop started; HOLDING the Lightsail migration

Pedro (going to sleep) asked for velosolabs to auto-redeploy every 30 min
overnight so it picks up what the `_latestVelosoLabs` cloud session merges.
Set up a recurring cron (`13,43 * * * *`, job 4d437aa8) that deploys ONLY when
GHCR `:latest`'s digest differs from the running container (no needless
restarts), journals real deploys only, and is scoped to velosolabs. First
cycle: main had advanced to `7406e1f` (#53 quillport-page) from the running
`e2dac3d`; confirmed `:latest`==`7406e1f` by digest, deployed, verified running
revision `7406e1f` + /health 200.

Separately, a cloud-session handoff (COORDINATION.md @ 9664dea) relayed Pedro's
request to migrate all pending Lightsail sites to the NAS. **Held, not executed**
— `migrate-from-lightsail --execute` does a live Cloudflare DNS cutover per site,
the memory rule is "confirm before live cutover," the request was second-hand,
and Pedro is asleep. Recorded the hold + the ready plan in COORDINATION.md; will
run it one site at a time (dry-run → execute → verify) on his direct go-ahead,
Lightsail kept as fallback, no nameserver/snapshot changes. Also: the Claude
Code Remote MCP isn't connected in this session, so I can't reply to the cloud
session except via COORDINATION.md.

## 2026-10-18: turned on velosolabs off-site GCS backup (VLABS-100); deployed #48

Enabled the nightly off-site backup per velosolabs `docs/offsite-backup.md`
(PRs #47/#48 already merged; HEAD `e2dac3d`). Steps done from here:
- Placed the `velosolabs-backup` GCS service-account key on the NAS at
  `/volume3/dockernvme/hub-veloso-dev/backup-key.json`, perms 600 (container
  runs as root so it reads it fine; key sha-verified Mac->Windows->NAS, contents
  never printed). It lives ONLY on the NAS — not in the repo or Windows source;
  re-downloadable from GCP if lost.
- Edited the compose SOURCE (`velosolabs/docker-compose.local.yml`) to add the
  read-only mount `./backup-key.json:/app/secrets/backup-key.json:ro` and
  `environment: BACKUP_BUCKET=velosolabs-hub-backups`,
  `BACKUP_KEY_FILE=/app/secrets/backup-key.json`; YAML-validated. The deployer
  uploads this as `docker-compose.yml`, so the key MUST already be on the NAS
  before deploy or Docker makes an empty dir at the mount path.
- Deployed `e2dac3d` (first image with `app/backup.py`), recreated the
  container. Verified env+key readable in-container.
- `docker exec velosolabs python -m app.backup run` -> ok, object
  `hub-20261018T124757Z.db.gz`, 23 files uploaded. `... drill` -> integrity ok
  (1 licence, 2 activations, 6 plans, 18 plugin releases; live DB untouched).

Design notes worth keeping: the backup key is add+read-only (Storage Object
Creator/Viewer) so a leaked key can't wipe backups; there is no fixed "latest"
object — each night writes a dated `velosolabs/db/hub-<ts>.db.gz` (35-day
lifecycle), restore uses the newest. Bucket `velosolabs-hub-backups`
(project velosolabs-hub, us-west1). The `.env` + licence signing key are NOT
in the bucket by design.

## 2026-10-18: redeployed velosolabs latest -> #45 (licence-terms)

Routine "deploy latest": pulled `main` to `1d21127` (Merge PR #45
"feat/licence-terms"; adds app/licence_terms.py). Confirmed GHCR `:latest` ==
`1d21127` by digest (publish run green) before deploying, then pull + up -d
--remove-orphans (rc=0). Running revision confirmed `1d21127`; /health 200,
`/`, `/tradeline`, `/voltwren`, `/gizmohaus` all 200. No config change (PayPal
env already set from the earlier rotation).

## 2026-10-18: rotated velosolabs live PayPal creds + plan IDs; force-recreated

Pedro pasted 10 PayPal vars (live client id/secret, webhook id, and the three
per-theme yearly plan + checkout URLs) as "new values for existing vars".
Upserted all 10 into the NAS production `.env` (`/volume3/dockernvme/hub-veloso-dev/.env`,
backup `.env.bak-20261018-192841`) and mirrored into the Windows velosolabs
source `.env` — all 10 already existed, so all updated, no dups, `PAYPAL_ENV`
stayed `live`, `PAYPAL_WEBHOOK_INSECURE_DEV` absent. Values moved file->file,
never echoed/committed (`.env` is gitignored).

main was unchanged (`974adf9`), so "redeploy" meant reload the env: ran
`pull` + `up -d --force-recreate` (force, because a same-image `up -d` may skip
recreation and a plain restart never reloads `.env`). Verified in-container
(`PAYPAL_ENV=live`, client_id/secret set, webhook + 3 plan IDs match by tail)
and on the live site — each theme page's Buy button `plan_id` now matches the
new plan (tradeline `…JNLKI74A`, voltwren `…8NLKI74I`, gizmohaus `…RNLKI74Q`);
/health 200.

Note: previous PayPal values are preserved in the dated NAS `.env.bak-*` for
rollback.

## 2026-10-18: velosolabs theme "Coming soon" was a content bug, not a stale deploy; fixed via PR #41/#42

Another chat insisted the live site still ran "old code" (voltwren/gizmohaus
showing "Coming soon"). That was WRONG and worth remembering how I disproved it:
read the running container's image `revision` label via the deployer's
`docker_command` plumbing (`docker inspect velosolabs --format
'{{index .Config.Labels "org.opencontainers.image.revision"}}'`) — it already
matched the newest commit, and tradeline showed prices. The deployer's `update`
does `docker compose pull` + `up -d` (NOT a bare restart), so it always fetches
the new image; "restart reuses the old image" doesn't apply to our deploy path.

Real cause: a hardcoded FAQ answer in velosolabs `app/theme_products.py`
("When can I buy Voltwren? It is coming soon…") stayed even though the themes
are launched (live PayPal plans + prices). It was **lowercase** "coming soon",
so the existing `test_theme_selling`/`test_site_wording` checks (which match
capital "Coming soon" from the template badge) never caught it.

Flow (velosolabs repo work, done on the Windows checkout): edited the two FAQ
answers, ran the two tests (12/12 pass), and — because a direct push to
velosolabs `main` is correctly blocked (app code lands via PR) — branched and
opened **PR #41**, which Pedro merged. Deployed `7b89837` (waited for the GHCR
publish run to finish first — a `:latest` digest check seconds after merge
races the build). Then a sibling session merged **PR #42** ("Theme FAQ follows
the Buy button" — the more robust conditional version) and asked (via a
cross-session message) for the same deploy; verified facts independently +ok'd
by Pedro, deployed `974adf9`. Final: `/voltwren` + `/gizmohaus` show $99 + Buy,
no "Coming soon", FAQ answers availability.

Gotchas: (1) GHCR publish for an `app/**` change takes a few min — poll the
sha tag before deploying or you redeploy the old `:latest`. (2) The "Claude
Code Remote" MCP server (used to reply to other sessions) is NOT connected in
this deployer session, so cross-session replies can't be sent from here.

## 2026-10-18: redeployed velosolabs latest -> #38 (lightbox button fix)

Routine "deploy latest": pulled `main` to `4472ab7` (#38 "Fix lightbox buttons
on the live site: version hub.css and lightbox.js URLs"), deployed (pull :latest
+ up -d --remove-orphans, rc=0). Running revision confirmed `4472ab7`; /health
200, routes 200. No config change this time (theme secrets already set).

## 2026-10-18: uploaded tradeline 1.3.0 zip (Lite download live); deployed latest #37

Uploaded `tradeline-1.3.0.zip` to the hub admin endpoint (`version=1.3.0`,
`{"ok":true}`, size 719326, sha verified Mac->Windows->NAS). Note the version
drift: an operator runbook said `tradeline-1.2.0.zip`/`version=1.2.0`, but the
file actually dropped was `1.3.0` — uploaded at `1.3.0` to match the artifact.
After upload the free "Download Tradeline Lite" button is live on `/tradeline`
and `/api/v1/themes/tradeline/download` -> 200.

Then "redeploy the latest": the deployer pulls `:latest`, which had raced from
`2ce5238` (#35) to **`8de61d0`** (#37 "Docs: quick order search, in-cart status
and category picker") during this rollout. Running revision confirmed
`8de61d0`; all three `code_secret()` still True after the recreate; /health 200,
routes 200. (An earlier "deploy 02392d8" request was intentionally NOT followed
to the letter — 02392d8/#34 predates the 1.2.0+ docs; deploying latest is what
the operator actually wanted.)

Reminder that recurred all day: velosolabs `main` publishes a new `:latest`
every few minutes, so "deploy latest" lands whatever is newest at pull time —
always read back the running `revision` label to report the exact commit.

## 2026-10-18: uploaded voltwren+gizmohaus 1.0.0 release zips; set all 3 theme licence secrets

Two related velosolabs ops (values/tokens not recorded here):

**Release zips.** Uploaded `voltwren-1.0.0.zip` and `gizmohaus-1.0.0.zip` to the
hub's admin endpoint (`POST https://velosolabs.com/api/v1/admin/themes/<name>/upload`,
`-F version=1.0.0`, bearer `ADMIN_API_TOKEN` read from the NAS `.env`). Both
returned `{"ok":true}` with matching sizes. These are served to licensed buyers;
they are NOT the container image. Transferred Mac->Windows->NAS with sha256
verified at each hop, then removed the upload-source copies.

**Licence secrets.** Upserted all three `THEME_CODE_SECRET_<PRODUCT>` (TRADELINE,
VOLTWREN, GIZMOHAUS; each a 48-hex value) into the NAS production `.env`
(backup `.env.bak-20261018-140827`; replaced the earlier lone tradeline line, no
dups, OPENID_KEY intact, perms 600) and mirrored into the Windows velosolabs
source `.env`. Force-recreated (`-f docker-compose.yml`) and verified each with
`themes.code_secret('<product>')` -> True + length 48; /health 200, routes 200.

Reusable gotchas confirmed this round:
- The NAS SSH server has NO SFTP subsystem -> `scp` fails ("subsystem request
  failed"). Move files with `ssh nas "cat > dest" < src` (binary-safe), the same
  shell-pipe the deployer uses. (Also remember `ssh -n` on non-piped nested ssh.)
- Operator runbooks keep saying `-f docker-compose.local.yml`; on the NAS the
  file is `docker-compose.yml` (deployer uploads the local override under that
  name). Always substitute.
- `.env` upsert pattern: `grep -vE '^(KEYS)=' .env > .env.tmp && cat new >> .env.tmp
  && chmod 600 .env.tmp && mv .env.tmp .env` (backup first; mv preserves nothing,
  so re-chmod 600).

## 2026-10-18: 2nd forced redeploy actually bumped cb8fdda -> 97e1033; #34 image was just a timing lag

A second operator-requested `pull` + `up -d --force-recreate` (corrected to
`-f docker-compose.yml`, the NAS filename) turned out NOT to be a no-op: GHCR
`:latest` had advanced to `97e1033` (#33 "Rename NetWattle Classic to
Voltwren"), so production moved `cb8fdda` -> `97e1033`. Verified running
revision `97e1033`, `/health` 200, routes green.

Investigated why `#34` (`02392d8`, "Voltwren screenshots") appeared to have no
image: it did build+publish fine. Its Publish run was *created* 03:33Z and the
force-recreate pulled `:latest` at ~03:32Z — ~1 min before #34's image finished,
so at pull time `:latest` was still `97e1033`. Minutes later `:latest` ==
`02392d8`. Lesson: a GHCR `:latest` digest check taken seconds after a push can
race the build; recheck before concluding "no image". As of this entry prod runs
`97e1033`, one behind the now-published `02392d8`.

## 2026-10-18: forced velosolabs redeploy (force-recreate), no version change

Operator-requested forced redeploy while `main` was unchanged at `cb8fdda`.
Ran `pull` + `up -d --force-recreate` via the deployer's sudo-docker plumbing
(no code change: GHCR `:latest` and the running revision stayed `cb8fdda`).
Point of a force-recreate is to restart the container and have it re-read
`.env`. Verified: running revision still `cb8fdda`, `/health` 200 after the
~20s blip, core routes + `/gizmohaus` all 200. No app/config change — recorded
only because asked.

## 2026-10-17: deployed velosolabs cb8fdda; theme-code secret now consumed + verified

Pulled `main` to `cb8fdda` (#32; with #30 NetWattle/Gizmohaus pages, #31
"Selling the themes: per-theme PayPal checkout" adding `app/theme_products.py`,
#32 theme install/update docs). Confirmed GHCR `:latest` == `cb8fdda` by
content-digest (`2865698…`) before deploying. Dry-run → live (rc=0,
`--remove-orphans`).

Milestone: the theme-code feature has now SHIPPED — `app/themes.py:code_secret()`
reads `THEME_CODE_SECRET_<PRODUCT>` from env. So the `THEME_CODE_SECRET_TRADELINE`
staged into the NAS `.env` earlier today is now actually consumed. Verified end
to end: running container's image `revision` label == `cb8fdda`, and
`docker exec velosolabs python -c "from app import themes; print(bool(themes.code_secret('tradeline')))"`
→ **True** (the forwarded verify that didn't exist in b489f17 now works).
`/health` 200 after the ~20s blip; `/`, `/tradeline`, `/tradeline/docs/bulk-orders`,
`/bylinely/docs`, `/gizmohaus` all 200.

## 2026-10-17: added two secrets to velosolabs PRODUCTION .env (NAS-side), recreated

Added `THEME_CODE_SECRET_TRADELINE` and `OPENID_KEY` to velosolabs' live env
(values not recorded here). Key operational facts worth remembering:

- **Production env lives on the NAS, not in the repo.** The compose uses
  `env_file: - .env`, and the deployer's `update` uploads ONLY the compose
  file (`ssh.upload_text`), never the `.env`. So the file the container reads
  is `/volume3/dockernvme/hub-veloso-dev/.env` on the NAS. Editing the Windows
  `velosolabs/.env` alone does NOT reach prod. I edited the NAS file directly
  (owned by `pedro:users`, mode 600 — no sudo needed to edit) and mirrored the
  same keys into the Windows `velosolabs/.env` source-of-truth. Backed up the
  NAS file first to `.env.bak-20261017-165924`.
- **Reloading env needs a recreate, not a restart.** Ran
  `cd <proj> && <compose> -f docker-compose.yml up -d --force-recreate`.
  Drove it through the deployer's own plumbing so sudo/password is handled:
  `smart_ssh_factory(settings, None)` + `detect_compose_command(ssh)` /
  `docker_command(ssh)` (both resolve to `sudo -S -p '' /usr/local/bin/docker …`
  with the password injected via the SSH channel). The deployer CLI has no
  exec/force-recreate passthrough, so a ~20-line script reusing those helpers
  is the clean way to run arbitrary sudo-docker on the NAS.
- **Verify by env presence, not the forwarded accessor.** The instructions I
  was given used `app.themes.code_secret('tradeline')`, which does NOT exist in
  the live image (`b489f17`) — a full grep finds no `THEME_CODE_SECRET` usage at
  all. The secret is staged ahead of the theme-code feature that will consume
  it. Confirmed load with `docker exec velosolabs sh -c 'test -n "$VAR"'` +
  length check (THEME_CODE_SECRET_TRADELINE len 48 as expected, OPENID_KEY 164).
  Site healthy after recreate (/health 200, routes 200).

Gotcha: nested `ssh nas "cmd"` inside `ssh win bash -s` must use `ssh -n`
(no stdin) or the first ssh eats the rest of the heredoc as its stdin.

## 2026-10-17: deployed velosolabs b489f17 (Tradeline bulk-orders docs)

Third velosolabs deploy of the day, same Windows→NAS flow. Pulled `main` to
`b489f17` ("Tradeline docs: bulk orders and trade enquiries", PR #26).
Pre-deploy, confirmed GHCR `:latest` already == `b489f17` by content-digest
(`77f86384…`) even though the commit was only ~2.5 min old — CI for an
`app/**` change publishes fast. Dry-run → live (rc=0, `--remove-orphans`),
verified: `/tradeline/docs/bulk-orders` (new route) → 200, new screenshot
asset → 200, "Bulk order" text on `/tradeline/docs`; `43cd9a2`'s additions
(`/bylinely/docs`, Tradeline "Coming soon") still present (no regression);
`/health` 200 after the ~20s blip. (Classic PAT for GHCR still valid at deploy
time — remind Pedro to revoke once done.)

## 2026-10-17: redeployed velosolabs to 43cd9a2 (true latest); Watchtower did NOT auto-land it

Follow-up to the same-day `a468f1d` deploy below. After re-authing `gh` on
Windows (needed a classic PAT — fine-grained PATs failed GHCR registry pulls,
and `gh`'s browser login can't complete over the non-TTY SSH automation) we
confirmed the running image by content and by GHCR digest:
- `a468f1d` had been deployed correctly, but `main` advanced to **`43cd9a2`**
  (PR #25, "Availability wording / Bylinely docs") whose image published to
  GHCR ~34 min AFTER that deploy. GHCR `:latest` moved to `43cd9a2`
  (digest `711ba28e…`, ≠ `a468f1d`'s `893ba450…`).
- **The NAS was still serving `a468f1d`** — i.e. Watchtower had NOT pulled the
  newer `:latest` in that window. Don't assume Watchtower lands "latest"
  promptly (or at all) for velosolabs; to put latest live, run the deploy
  explicitly. (Open question whether Watchtower is watching this container or
  just polls slowly — worth confirming on the NAS when there's socket access.)

Redeployed to `43cd9a2` via the usual Windows→NAS flow (dry-run → live, rc=0,
`--remove-orphans`). Verified the running image is now `43cd9a2` by its
visible diff — markers that were absent pre-deploy are now present:
`/bylinely/docs` (new route) → 200; Tradeline says "Coming soon" (old
"Submitted to the Shopify Theme Store · In review" gone); `/bylinely` hero is
"Download free" (was "Get Bylinely"); `/health` 200 after the usual ~20s blip.

Verification technique worth reusing: to prove WHICH commit is live without
NAS docker access, read the GHCR tag's `org.opencontainers.image.revision`
label / compare tag content-digests, and grep the live site for a string the
target commit's diff adds or removes.

## 2026-10-17: deployed velosolabs latest main to the NAS (from Windows)

Routine production deploy of velosolabs.com, driven from the Windows machine
(`IPC-ADM-122`) via the deployer, per `velosolabs-deploy` memory:

    cd /c/Users/claude/Projects/synology-site-deployer
    synology-site update hub.veloso.dev \
      --compose-file ../velosolabs/docker-compose.local.yml \
      --container-name velosolabs        # --dry-run first, then live

Pulled velosolabs `main` to `a468f1d` (Merge PR #24 "feat/theme-licensing";
the feature commit `d3d3fa4` touches `app/**`, which is what triggers the
`docker-publish` workflow → GHCR `:latest`). Dry-run clean; live deploy rc=0
("Uploaded new compose file", "Pulled latest images"); `up` ran with the now-
committed `--remove-orphans` default (update.py:133). Verified: `/health` →
`{"status":"ok"}` (404 for the first ~30s was the startup blip, as usual),
`/`, `/tradeline`, `/tradeline/docs`, `/tradeline/support` all → 200, homepage
serves Tradeline content with no stale "self-hosted" markup.

Caveat for next time: the `gh` CLI token for `s2925534` on Windows is
**invalid/expired**, so the usual `gh run list -R s2925534/velosolabs` CI-green
pre-check couldn't run, and the GHCR package is private (anonymous registry
query denied). Deploy proceeded on strong circumstantial evidence (app-code
commit ~1 day old → CI long since published) plus post-deploy health/content
verification. To restore the exact pre-check, re-auth on Windows with
`gh auth login -h github.com` (interactive; needs Pedro). The app exposes no
public version/revision endpoint, so there's no byte-level "is a468f1d live"
confirmation beyond content.

## 2026-10-12: project migrated to Windows (IPC-ADM-122), Mac copy safe to delete

Completed the move of this project onto the Windows machine
(`C:\Users\claude\Projects\synology-site-deployer`), same "develop on Windows,
free the Mac" line we did for zqx. Windows was already substantially set up
from the 2026-10-11 session (repo cloned, deployer `pip install -e .`, secrets
present — it had deployed velosolabs from there). This session closed the
remaining gaps.

Done directly Mac→Windows over Tailscale SSH (`claude@ipc-adm-122`), **not**
via the NAS — the NAS overload is what derailed the prior session, so the SMB
share was deliberately left out of the loop. Verified in place:
- `.env` md5-identical; all 16 `secrets/` files present with matching sizes;
  Lightsail `.pem` + `aws.env` md5-identical.
- `BRANDING.md`, `infra-analysis-report.md`, `migration-reports/`,
  `redirect-backups/` — transferred (tar over scp) and confirmed.
- `migration-backups/` (the only-copy item; its NAS backup had timed out) —
  485M / 16,789 files pushed as a gzip tarball; tarball md5 bit-identical on
  both ends, extracted, and recount is an exact match: **files=16789
  bytes=467274949**.
- `activity-log/`: Windows keeps its own (newer deploy entries); Mac's larger
  history preserved alongside as `activity-log/history.mac.jsonl`.

Gotchas for next time working Mac→Windows:
- Windows default SSH shell is `cmd.exe`; pipe scripts via `ssh host bash -s`
  on stdin and start them with `export PATH=/usr/bin:$PATH` (otherwise
  `find`/`tar`/`md5sum` resolve to Windows `System32` binaries, not git-bash).
- Windows OpenSSH **kills detached (`nohup`/`disown`) children when the SSH
  session closes** — long remote jobs silently die. Run them in the foreground
  of a *local* backgrounded command so the session stays open for the duration.
- macOS `tar czf` embeds xattrs that extract as `._*` AppleDouble files on
  NTFS; clean with `find … -name '._*' -o -name '.DS_Store' -delete`. (The
  committed backup hook uses rsync, so it doesn't have this issue.)

The Mac working copy is now redundant and safe to delete. Not renamed/removed
here — Pedro removes it himself.

## 2026-10-04: journal + NAS backup set up

Added this journal, the verbatim-index hook (`.githooks/post-commit`), and
`tools/backup-excluded-to-nas.sh` — rsync over the mounted SMB share
(`smb://DS.local/home/Projects`), additive-only, backs up `secrets/` and
other gitignored local files plus this project's Claude Code memory.
Replaces any OS-specific backup scheduler (Windows Task Scheduler, macOS
launchd): the same committed hook runs on any machine once `git config
core.hooksPath .githooks` is set. Same pattern already in use in
veloso.dev, ecosystem-services, and systemsnotsilos.

A remote (cloud) Claude session independently set up the same
journal/coordination scaffolding in parallel on GitHub around the same
time — this entry supersedes that one; the NAS backup piece only makes
sense run locally, so remote sessions won't trigger it.

Earlier history lives only in `git log`; when a past decision becomes
relevant, summarise it here.
