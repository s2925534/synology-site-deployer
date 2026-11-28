#!/usr/bin/env bash
# VDEV-33 — NAS runner-host heartbeat. POSTs an HMAC-signed beat to the Cloudflare
# watchdog every 60s. If these stop arriving for >5 min the watchdog flips
# CI_RUNNER to 'github' so deploys never stall. The HMAC secret lives only here
# (NAS .env) and as a Worker secret — never in git or chat.
#
# Required env:
#   WATCHDOG_URL          e.g. https://ci-watchdog.velosolabs.workers.dev/heartbeat
#   HEARTBEAT_HMAC_SECRET shared secret (also a Worker secret)
# Optional:
#   HOST_ID               identifier for this NAS host (default: nas)
#   INTERVAL              seconds between beats (default: 60)
set -euo pipefail
: "${WATCHDOG_URL:?}" "${HEARTBEAT_HMAC_SECRET:?}"
HOST_ID="${HOST_ID:-nas}"
INTERVAL="${INTERVAL:-60}"

while true; do
  TS=$(date +%s)
  BODY=$(printf '{"host":"%s","ts":%d}' "$HOST_ID" "$TS")
  SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$HEARTBEAT_HMAC_SECRET" | awk '{print $NF}')
  curl -fsS -m 10 -X POST "$WATCHDOG_URL" \
    -H "Content-Type: application/json" \
    -H "X-Signature: sha256=${SIG}" \
    --data "$BODY" >/dev/null 2>&1 \
    && echo "[$(date -u +%FT%TZ)] heartbeat ok" \
    || echo "[$(date -u +%FT%TZ)] heartbeat FAILED (watchdog unreachable)"
  sleep "$INTERVAL"
done
