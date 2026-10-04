#!/bin/bash
# Portable NAS backup of the git-excluded / local-only parts of this project
# (live .env secrets, deploy/recovery staging, this project's Claude Code
# memory) plus a full working-tree mirror minus regenerable artifacts.
# Destination: smb://DS.local/home/Projects/<project>-excluded-backup/ — the
# same pattern the sibling projects use.
#
# Driven by .githooks/post-commit so it runs on every commit on ANY machine
# (macOS, Windows git-bash, Linux) with no OS-specific scheduler. It derives
# everything from the git repo and the current machine's $HOME, so the same
# committed script works wherever the code is checked out.
#
# Whole-folder, not curated: the repo is mirrored in full minus an exclude
# list of regenerable output (.git, node_modules, build, caches) that a clone
# / reinstall reproduces for free. This captures the gitignored files git
# never carries (infra/wordpress.env, backup-plans/*/backup.env, secrets/,
# .claude, .deploy-stage, RESTORE-SNS.sh, agent-context/journal-verbatim/).
#
# Safe by design: additive rsync only (never --delete); no `set -e`; and it
# exits 0 and skips quietly whenever rsync is missing or the NAS share is not
# mounted, so it can never block or fail a commit.

set -uo pipefail

# Repo root (works regardless of CWD or which machine this runs on).
ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null)" || ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="$(basename "$ROOT")"
LOG="$ROOT/tools/.backup-excluded-to-nas.log"
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG" 2>/dev/null; }

command -v rsync >/dev/null 2>&1 || { log "SKIP: rsync not available on this machine"; exit 0; }

# Locate the NAS "home" share's Projects dir: env override first, then the
# first existing candidate (macOS auto-mount, Windows git-bash UNC, common
# mapped drive letters).
CANDIDATES=("${NAS_PROJECTS_DIR:-}" "/Volumes/home/Projects" "//DS.local/home/Projects" "/z/Projects" "/y/Projects" "/n/Projects")
PROJECTS_DIR=""
for c in "${CANDIDATES[@]}"; do
  [ -n "$c" ] && [ -d "$c" ] && { PROJECTS_DIR="$c"; break; }
done
[ -n "$PROJECTS_DIR" ] || { log "SKIP: NAS Projects share not mounted (set NAS_PROJECTS_DIR to override)"; exit 0; }

DEST="$PROJECTS_DIR/${PROJECT}-excluded-backup"
mkdir -p "$DEST" 2>/dev/null || { log "SKIP: cannot create $DEST"; exit 0; }
log "START ($PROJECTS_DIR)"

REGEN=(.git node_modules dist build coverage __pycache__ '*.pyc' .pytest_cache htmlcov '*.egg-info' .venv .idea .DS_Store 'tools/.backup-excluded-to-nas.log')

sync_tree() { # <label> <src> <dst> <exclude...>
  local label="$1" src="$2" dst="$3"; shift 3
  local ex=(); for p in "$@"; do ex+=(--exclude="$p"); done
  [ -d "$src" ] || return 0
  mkdir -p "$dst" 2>/dev/null || return 0
  if rsync -a "${ex[@]}" "$src/" "$dst/" 2>> "$LOG"; then log "OK: $label"; else log "FAILED: $label (retry next commit)"; fi
}

# The mechanism itself, so a fresh machine finds this script on the NAS.
mkdir -p "$DEST/backup-mechanism" 2>/dev/null
cp "$ROOT/tools/backup-excluded-to-nas.sh" "$DEST/backup-mechanism/" 2>> "$LOG"

# This project's Claude Code memory/transcripts, per the repo-path slug under
# this machine's own home (so it adapts to whatever machine runs it).
SLUG="$(printf '%s' "$ROOT" | sed 's/[^A-Za-z0-9]/-/g')"
for parent in "$HOME"/.claude "$HOME"/.claude-account2; do
  src="$parent/projects/$SLUG"
  [ -d "$src" ] && sync_tree "claude-memory ($(basename "$parent"))" "$src" "$DEST/claude-memory/$(basename "$parent")" \
    cache 'daemon.lock' 'daemon.log' 'daemon-auth-cooldown' 'daemon-auth-status.json' '*.tmp.*'
done

# The whole working tree (carries every gitignored secret + local-only file).
sync_tree "$PROJECT (whole tree)" "$ROOT" "$DEST/$PROJECT" "${REGEN[@]}"

if [ ! -f "$DEST/README.md" ]; then
  cat > "$DEST/README.md" <<EOF
# ${PROJECT}-excluded-backup

Local-network NAS backup of the git-excluded / local-only parts of the
$PROJECT project plus a full working-tree mirror minus regenerable artifacts.
Source of truth for tracked code is GitHub; this backs up what git does not
carry, for machine-migration continuity.

Written by $PROJECT/tools/backup-excluded-to-nas.sh, invoked from
.githooks/post-commit on every commit (no OS scheduler). Additive rsync only,
never --delete. Enable the hook once per checkout with
\`git config core.hooksPath .githooks\`.
EOF
fi

log "DONE"
