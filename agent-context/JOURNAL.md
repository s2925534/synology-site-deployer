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

## 2026-10-04: journal + NAS backup set up

Added this journal, the verbatim-index hook (`.githooks/post-commit`), and
`tools/backup-excluded-to-nas.sh` — rsync over the mounted SMB share
(`smb://DS.local/home/Projects`), additive-only, backs up `secrets/` and
other gitignored local files plus this project's Claude Code memory.
Replaces any OS-specific backup scheduler (Windows Task Scheduler, macOS
launchd): the same committed hook runs on any machine once `git config
core.hooksPath .githooks` is set. Same pattern already in use in
veloso.dev, ecosystem-services, and systemsnotsilos. Earlier history lives
only in `git log`; when a past decision becomes relevant, summarise it here.
