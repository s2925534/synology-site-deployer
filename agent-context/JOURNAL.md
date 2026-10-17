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
