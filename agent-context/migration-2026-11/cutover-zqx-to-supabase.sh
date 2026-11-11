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
APP_CONN="$(getenv SUPEBASE_VELOSOLABS_APP_CONNECTION_STRING)"   # zqx_app (RLS-enforced) -> APP_DATABASE_URL
OWNER_CONN="$(getenv SUPEBASE_VELOSOLABS_CONNECTION_STRING)"     # zqx_owner (BYPASSRLS) -> DATABASE_URL
[ -n "$PW" ]         || { echo "FATAL: NAS_SSH_PASSWORD missing"; exit 1; }
[ -n "$APP_CONN" ]   || { echo "FATAL: SUPEBASE_VELOSOLABS_APP_CONNECTION_STRING missing"; exit 1; }
[ -n "$OWNER_CONN" ] || { echo "FATAL: SUPEBASE_VELOSOLABS_CONNECTION_STRING missing"; exit 1; }

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
  echo "[recreate] done; polling /health (up to ~100s, app connects to a Tokyo pooler)"
  ok=0
  for i in $(seq 1 20); do
    sleep 5
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:'"$PORT"'/health || echo 000)
    echo "  [health $i] $code"
    if [ "$code" = 200 ]; then ok=1; break; fi
  done
  if [ "$ok" != 1 ]; then
    echo "[FAIL] /health never returned 200 -- ROLLING BACK"
    cp -p "docker-compose.yml.bak-'"$TS"'" docker-compose.yml
    echo "$PW" | sudo -S '"$DOCKER"' compose up -d --force-recreate --no-deps '"$SVC"'
    echo "[rolledback] restored compose + recreated on NAS zqx-db"
    exit 1
  fi
  echo "[ok] '"$SVC"' live on Supabase (NAS zqx-db still running as fallback)"
'
echo "=== zqx-api (prod) -> Supabase ==="
printf '%s\n%s\n%s\n' "$PW" "$APP_CONN" "$OWNER_CONN" | ssh -i "$SSH_KEY" -o IdentitiesOnly=yes "$NAS" "$REMOTE" 2>&1 | grep -viE "$SSH_FILTER"
rc="${PIPESTATUS[1]}"
[ "$rc" = 0 ] && echo "=== DONE. app/field/portal need no change (they reach the DB via zqx-api). ===" || { echo "ABORTED (rc=$rc)"; exit 1; }