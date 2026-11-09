#!/usr/bin/env bash
# cutover-mcp-gateway-to-neon.sh  — repoint mcp-gateway DB -> Neon (pooled).
# Reversible: backs up .env, keeps NAS mcp-gateway-db running (--no-deps), auto-fails if health!=200.
set -u
DEPLOYER_ENV="/Users/pedro/Documents/_Projects/synology-site-deployer/.env"
SSH_KEY="$HOME/.ssh/id_ed25519_zqx_nas"
NAS="pedro@192.168.1.109"
DOCKER="/var/packages/ContainerManager/target/usr/bin/docker"
SSH_FILTER='post-quantum|store now|vulnerable|openssh.com/pq'
HEALTH_URL="https://mcp.velosolabs.com/healthz"
TS="$(date +%Y%m%d-%H%M%S)"
getenv() { grep -m1 -E "^$1=" "$DEPLOYER_ENV" | sed -E "s/^$1=//" | tr -d '\r'; }

PW="$(getenv NAS_SSH_PASSWORD)"
CONN="$(getenv NEON_VELOSOLABS_CONNECTION_STRING)"
[ -n "$PW" ]   || { echo "FATAL: NAS_SSH_PASSWORD missing"; exit 1; }
[ -n "$CONN" ] || { echo "FATAL: NEON_VELOSOLABS_CONNECTION_STRING missing"; exit 1; }

REMOTE='
  set -eu
  IFS= read -r PW
  IFS= read -r CONN
  export CONN
  cd /volume3/dockernvme/mcp-gateway
  cp -p .env ".env.bak-'"$TS"'"
  echo "[backup] mcp-gateway/.env.bak-'"$TS"'"
  python3 - <<"PY"
import os
f=".env"; val=os.environ["CONN"]; key="GATEWAY_DATABASE_URL"
lines=open(f).read().splitlines(); out=[]; done=False
for ln in lines:
    if ln.startswith(key+"="):
        out.append(key+"="+val); done=True
    else:
        out.append(ln)
if not done: raise SystemExit("[FAIL] "+key+" not found in .env")
open(f,"w").write("\n".join(out)+"\n")
print("[edit] rewrote "+key+" -> Neon")
PY
  echo "[verify] key now (value redacted):"
  grep -n "^GATEWAY_DATABASE_URL=" .env | sed -E "s#(://[^:]*:)[^@]*@[^/]*#\1REDACTED@HOST#g"
  echo "$PW" | sudo -S '"$DOCKER"' compose up -d --force-recreate --no-deps mcp-gateway mcp-gateway-admin
  echo "[info] mcp-gateway-db left running as fallback"
'
echo "=== mcp-gateway -> Neon ==="
printf '%s\n%s\n' "$PW" "$CONN" | ssh -i "$SSH_KEY" -o IdentitiesOnly=yes "$NAS" "$REMOTE" 2>&1 | grep -viE "$SSH_FILTER"
rc="${PIPESTATUS[1]}"
[ "$rc" = 0 ] || { echo "ABORTED (remote rc=$rc)"; exit 1; }

echo "[health] waiting for $HEALTH_URL ..."
ok=0
for i in 1 2 3 4 5 6 7 8 9 10; do
  code="$(curl -s -o /dev/null -w '%{http_code}' "$HEALTH_URL" || echo 000)"
  echo "  attempt $i -> $code"
  [ "$code" = 200 ] && { ok=1; break; }
  sleep 3
done
if [ "$ok" = 1 ]; then
  echo "[ok] mcp-gateway live on Neon. NAS mcp-gateway-db kept as fallback. (.env.bak-$TS on NAS)"
else
  echo "[FAIL] $HEALTH_URL not 200 -- ROLLING BACK"
  RB='set -eu; cd /volume3/dockernvme/mcp-gateway; IFS= read -r PW; cp -p ".env.bak-'"$TS"'" .env; echo "$PW" | sudo -S '"$DOCKER"' compose up -d --force-recreate --no-deps mcp-gateway mcp-gateway-admin; echo "[rolledback] restored .env.bak-'"$TS"'"'
  printf '%s\n' "$PW" | ssh -i "$SSH_KEY" -o IdentitiesOnly=yes "$NAS" "$RB" 2>&1 | grep -viE "$SSH_FILTER"
  exit 1
fi