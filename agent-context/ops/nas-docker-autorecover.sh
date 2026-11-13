#!/bin/bash
# NAS Docker auto-recovery — run at boot by Synology Task Scheduler (Triggered Task,
# event "Boot-up", user root). Heals the recurring post-unclean-shutdown failure:
#   btrfs scrub on /volume1 starves IO -> ContainerManager's first start times out ->
#   its usr-local-linker never runs -> package binaries (containerd, runc, shims) are
#   not in PATH -> dockerd can't exec managed containerd -> Docker stays down.
# See agent-context/JOURNAL.md (2026-11-12 recovery) + the matching memory.
#
# SAFE + idempotent: it does nothing unless Docker is still down after a grace period,
# so a healthy boot is a no-op and a legitimately-scheduled scrub is left alone.
# Runs as root under Task Scheduler (no sudo needed).
set -uo pipefail
export PATH=/usr/syno/bin:/usr/syno/sbin:/bin:/usr/bin:/sbin:/usr/sbin

D=/var/packages/ContainerManager/target/usr/bin/docker
B=/var/packages/ContainerManager/target/usr/bin
LOG=/volume1/docker/ops/logs/nas-docker-autorecover.log
mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
log(){ echo "$(date '+%F %T') $*" >> "$LOG" 2>/dev/null; }

log "=== boot auto-recovery start (uptime:$(cut -d. -f1 /proc/uptime)s) ==="

# 0. Grace: let the normal boot bring Docker up on its own (healthy boot ~1-2 min).
for i in $(seq 1 18); do            # up to ~3 min
  if "$D" info >/dev/null 2>&1; then log "Docker already up (grace attempt $i) -- nothing to do"; exit 0; fi
  sleep 10
done
log "Docker still down after grace -- starting recovery"

# 1. Cancel a running /volume1 scrub (it starves IO and blocks ContainerManager's start).
if btrfs scrub status /volume1 2>/dev/null | grep -qi 'running for'; then
  btrfs scrub cancel /volume1 >/dev/null 2>&1 && log "cancelled running /volume1 scrub"
fi

# 2. Recreate the package binary symlinks the failed start never created.
mkdir -p /usr/local/bin
for f in "$B"/*; do ln -sf "$f" /usr/local/bin/"$(basename "$f")"; done
for n in containerd containerd-shim containerd-shim-runc-v1 containerd-shim-runc-v2 runc docker-init docker-proxy ctr; do
  [ -e "$B/$n" ] && ln -sf "$B/$n" /usr/bin/"$n"
done
log "recreated binary symlinks (containerd -> $(command -v containerd 2>/dev/null || echo 'NOT FOUND'))"

# 3. Start ContainerManager.
synopkg start ContainerManager >/dev/null 2>&1
log "issued: synopkg start ContainerManager"

# 4. Wait for Docker and report.
for i in $(seq 1 18); do            # up to ~3 min
  sleep 10
  if "$D" info >/dev/null 2>&1; then
    n=$("$D" ps -q 2>/dev/null | wc -l | tr -d ' ')
    log "Docker UP after recovery (attempt $i); ${n} containers running"
    exit 0
  fi
done
log "ERROR: Docker still down after recovery -- manual intervention needed"
exit 1
