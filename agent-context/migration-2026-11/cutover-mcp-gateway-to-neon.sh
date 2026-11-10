#!/usr/bin/env bash
# cutover-mcp-gateway-to-neon.sh  — repoint mcp-gateway DB -> Neon (pooled).
# Health gate = the container's OWN Docker healthcheck (python urlopen /healthz:8080 INSIDE
# the container), NOT an external HTTP probe: mcp.velosolabs.com does not expose /healthz
# through the tunnel (returns 404 by design). Reversible: backs up .env, keeps NAS
# mcp-gateway-db running (--no-deps), auto-rolls back if the container doesn't go healthy
# or the logs show DB connection errors.
set -u
DEPLOYER_ENV="/Users/pedro/Documents/_Projects/synology-site-deployer/.env"
SSH_KEY="$HOME/.ssh/id_ed25519_zqx_nas"
NAS="pedro@192.168.1.109"
DOCKER="/var/packages/ContainerManager/target/usr/bin/docker"
SSH_FILTER='post-quantum|store now|vulnerable|openssh.com/pq|^\*\*|secure_path'
TS="$(date +%Y%m%d-%H%M%S)"
getenv() { grep -m1 -E "^$1=" "$DEPLOYER_ENV" | sed -E "s/^$1=//" | tr -d '\r'; }

PW="$(getenv NAS_SSH_PASSWORD)"
CONN="$(getenv NEON_VELOSOLABS_CONNECTION_STRING)"
[ -n "$PW" ]   || { echo "FATAL: NAS_SSH_PASSWORD missing"; exit 1; }
[ -n "$CONN" ] || { echo "FATAL: NEON_VELOSOLABS_CONNECTION_STRING missing"; exit 1; }

REMOTE='
  set -u
  IFS= read -r PW
  IFS= read -r CONN
  export CONN
  D='"$DOCKER"'
  dk(){ echo "$PW" | sudo -S "$D" "$@"; }
  cd /volume3/dockernvme/mcp-gateway
  cp -p .env ".env.bak-'"$TS"'"
  echo "[backup] mcp-gateway/.env.bak-'"$TS"'"
  python3 - <<"PY"
import os
f=".env"; val=os.environ["CONN"]; key="GATEWAY_DATABASE_URL"
out=[]; done=False
for ln in open(f).read().splitlines():
    if ln.startswith(key+"="): out.append(key+"="+val); done=True
    else: out.append(ln)
if not done: raise SystemExit("[FAIL] "+key+" not found in .env")
open(f,"w").write("\n".join(out)+"\n")
print("[edit] rewrote "+key+" -> Neon")
PY
  echo "[verify] key now (redacted):"
  grep -n "^GATEWAY_DATABASE_URL=" .env | sed -E "s#(://[^:]*:)[^@]*@[^/]*#\1REDACTED@HOST#g"
  dk compose up -d --force-recreate --no-deps mcp-gateway mcp-gateway-admin >/dev/null 2>&1
  echo "[recreate] mcp-gateway + admin recreated on Neon (mcp-gateway-db left running)"

  # ---- health gate: poll the container Docker healthcheck (hits /healthz:8080 internally) ----
  st=starting
  for i in $(seq 1 30); do
    st=$(echo "$PW" | sudo -S "$D" inspect mcp-gateway --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" 2>/dev/null)
    echo "  [health $i] mcp-gateway=$st"
    [ "$st" = healthy ] && break
    [ "$st" = unhealthy ] && break
    sleep 4
  done
  DBERR=$(echo "$PW" | sudo -S "$D" logs mcp-gateway --tail 60 2>&1 | grep -iE "could not connect|connection refused|password auth|does not exist|FATAL|OperationalError|no route to host|timeout expired" | grep -ivE "GET /healthz" | tail -5)

  if [ "$st" = healthy ] && [ -z "$DBERR" ]; then
    echo "[ok] mcp-gateway HEALTHY on Neon; no DB errors in logs. NAS mcp-gateway-db kept as fallback. (.env.bak-'"$TS"')"
    exit 0
  fi
  echo "[FAIL] status=$st; db-errors:"; echo "$DBERR" | sed "s/^/    /"
  echo "[rollback] restoring .env.bak-'"$TS"'"
  cp -p ".env.bak-'"$TS"'" .env
  dk compose up -d --force-recreate --no-deps mcp-gateway mcp-gateway-admin >/dev/null 2>&1
  echo "[rolledback] mcp-gateway restored on NAS mcp-gateway-db"
  exit 1
'
echo "=== mcp-gateway -> Neon ==="
printf '%s\n%s\n' "$PW" "$CONN" | ssh -i "$SSH_KEY" -o IdentitiesOnly=yes "$NAS" "$REMOTE" 2>&1 | grep -viE "$SSH_FILTER"
rc="${PIPESTATUS[1]}"
[ "$rc" = 0 ] && echo "=== DONE: mcp-gateway live on Neon ===" || { echo "=== ABORTED (rolled back; rc=$rc) ==="; exit 1; }