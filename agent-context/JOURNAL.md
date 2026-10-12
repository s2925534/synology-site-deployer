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
