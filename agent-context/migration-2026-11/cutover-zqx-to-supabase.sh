#!/usr/bin/env bash
# cutover-zqx-to-supabase.sh — repoint zqx-api DB -> Supabase (IPv4 session pooler).
# Reversible: backs up compose, keeps NAS zqx-db running (--no-deps), auto-rolls back if health!=200.
# Staging left OFF (separate zqx_staging DB). Run:  ! bash <thisfile>
set -u
DEPLOYER_ENV="/Users/pedro/Documents/_Projects/synology-site-deployer/.env"
SSH_KEY="$HOME/.ssh/id_ed25519_zqx_nas"
NAS="pedro@192.168.1.109"
DOCKER="/var/packages/ContainerManager/target/usr/bin/docker"
SSH_FILTER='post-quantum|store now|vulnerable|openssh.com/pq'
TS="$(date +%Y%m%d-%H%M%S)"
getenv() { grep -m1 -E "^$1=" "$DEPLOYER_ENV" | sed -E "s/^$1=//" | tr -d '\r'; }

PW="$(getenv NAS_SSH_PASSWORD)"
POOLED="$(getenv SUPEBASE_CLOUD_ZQX_CONNECTION_STRING)"        # IPv4 session pooler (set by migration)
DIRECT="$(getenv SUPEBASE_CLOUD_ZQX_DIRECT_CONNECTION_STRING)"
[ -n "$DIRECT" ] || DIRECT="$POOLED"
[ -n "$PW" ]     || { echo "FATAL: NAS_SSH_PASSWORD missing"; exit 1; }
[ -n "$POOLED" ] || { echo "FATAL: SUPEBASE_CLOUD_ZQX_CONNECTION_STRING missing"; exit 1; }

DIR="api-zqx-io"; SVC="api"; PORT="5105"
REMOTE='
  set -eu
  IFS= read -r PW
  IFS= read -r CONN_APP
  IFS= read -r CONN_OWNER
  export CONN_APP CONN_OWNER
  cd "/volume3/dockernvme/'"$DIR"'"
  cp -p docker-compose.yml "docker-compose.yml.bak-'"$TS"'"
  echo "[backup] '"$DIR"'/docker-compose.yml.bak-'"$TS"'"
  python3 - <<"PY"
import os,re
f="docker-compose.yml"
repl={"APP_DATABASE_URL":os.environ["CONN_APP"],"DATABASE_URL":os.environ["CONN_OWNER"]}
def yq(v):
    v=v.replace("$","$$")
    return "'"'"'"+v.replace("'"'"'","'"'"''"'"'")+"'"'"'"
out=[]; done=set()
for ln in open(f).read().splitlines():
    m=re.match(r"^(\s*)(APP_DATABASE_URL|DATABASE_URL)\s*:\s*.*$",ln)
    if m and m.group(2) in repl:
        out.append(m.group(1)+m.group(2)+": "+yq(repl[m.group(2)])); done.add(m.group(2))
    else:
        out.append(ln)
open(f,"w").write("\n".join(out)+"\n")
missing=[k for k in repl if k not in done]
if missing: raise SystemExit("[FAIL] keys not found: "+",".join(missing))
print("[edit] rewrote "+", ".join(sorted(done))+" -> cloud")
PY
  echo "[verify] keys now (value redacted):"
  grep -nE "DATABASE_URL\s*:" docker-compose.yml | sed -E "s#(://[^:]*:)[^@]*@[^/\"'"'"']*#\1REDACTED@HOST#g"
  echo "$PW" | sudo -S '"$DOCKER"' compose up -d --force-recreate --no-deps '"$SVC"'
  sleep 6
  code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:'"$PORT"'/health || echo 000)
  echo "[health] http://127.0.0.1:'"$PORT"'/health -> $code"
  if [ "$code" != 200 ]; then
    echo "[FAIL] health != 200 -- ROLLING BACK"
    cp -p "docker-compose.yml.bak-'"$TS"'" docker-compose.yml
    echo "$PW" | sudo -S '"$DOCKER"' compose up -d --force-recreate --no-deps '"$SVC"'
    echo "[rolledback] restored compose + recreated on NAS zqx-db"
    exit 1
  fi
  echo "[ok] '"$SVC"' live on Supabase (NAS zqx-db still running as fallback)"
'
echo "=== zqx-api (prod) -> Supabase ==="
printf '%s\n%s\n%s\n' "$PW" "$POOLED" "$DIRECT" | ssh -i "$SSH_KEY" -o IdentitiesOnly=yes "$NAS" "$REMOTE" 2>&1 | grep -viE "$SSH_FILTER"
rc="${PIPESTATUS[1]}"
[ "$rc" = 0 ] && echo "=== DONE. app/field/portal need no change (they reach the DB via zqx-api). ===" || { echo "ABORTED (rc=$rc)"; exit 1; }