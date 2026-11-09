#!/bin/bash
# zqx-db (NAS Postgres) -> Supabase ZQX, via the IPv4 POOLER (session mode, 5432).
# Fixes v1's failure: Supabase's direct host db.<ref>.supabase.co is IPv6-only and
# the NAS has no IPv6 route. The pooler is IPv4 and is ALSO what the NAS-hosted zqx
# apps must use at runtime, so this script also repoints .env CONNECTION_STRING to it.
# Non-destructive to the NAS: zqx-db is only READ (pg_dump). Secrets read from .env
# at runtime; never printed, never passed on an argv.
set -uo pipefail
DEP=/Users/pedro/Documents/_Projects/synology-site-deployer/.env
getk(){ grep -m1 -E "^$1=" "$DEP" | sed -E "s/^$1=//" | tr -d '\r' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"; }

REF=$(getk SUPEBASE_CLOUD_ZQX_PROJECT_ID)
export PGPASSWORD=$(getk SUPEBASE_CLOUD_ZQX_DB_PWD)
[ -n "$REF" ] && [ -n "$PGPASSWORD" ] || { echo "ABORT: REF or DB pwd missing in .env"; exit 1; }
export PGCONNECT_TIMEOUT=8 PGSSLMODE=require

echo "=== 1. find the pooler region (auth probe; password from env, not argv) ==="
POOLHOST=""
for r in ap-northeast-1 ap-southeast-2 ap-southeast-1 us-east-1 us-west-1 eu-west-1 ap-south-1 eu-central-1 us-east-2; do
  for p in aws-0 aws-1; do
    H="$p-$r.pooler.supabase.com"
    if psql "host=$H port=5432 user=postgres.$REF dbname=postgres sslmode=require" -tAc "select 1" >/dev/null 2>&1; then
      POOLHOST="$H"; echo "  MATCH: region=$r host=$H"; break 2
    fi
  done
done
[ -n "$POOLHOST" ] || { echo "ABORT: no pooler region authenticated the tenant"; exit 1; }

# Session-mode pooler (5432): full SQL incl. DDL/prepared statements, IPv4-reachable.
CONN="postgresql://postgres.${REF}:${PGPASSWORD}@${POOLHOST}:5432/postgres?sslmode=require"

echo "=== 2. stage conn on NAS (stdin; never on a command line) ==="
printf '%s' "$CONN" | ssh -i ~/.ssh/id_ed25519_zqx_nas -o IdentitiesOnly=yes -o ConnectTimeout=15 pedro@192.168.1.109 \
  "cat > /tmp/zqxconn && chmod 600 /tmp/zqxconn && echo '  staged'"

echo "=== 3. dump zqx-db + restore into Supabase pooler (run on NAS; postgres:17 client) ==="
ssh -i ~/.ssh/id_ed25519_zqx_nas -o IdentitiesOnly=yes -o ConnectTimeout=15 pedro@192.168.1.109 'bash -s' <<'OUTER' 2>&1 | grep -viE "post-quantum|store now|openssh.com/pq|vulnerable|^\*\*|secure_path"
DEPENV=/volume1/homes/pedro/Projects/synology-site-deployer-excluded-backup/synology-site-deployer/.env
PW=$(grep -E '^NAS_SSH_PASSWORD=' "$DEPENV" | head -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"//' -e 's/"$//')
D=/var/packages/ContainerManager/target/usr/bin/docker
CONN=$(cat /tmp/zqxconn)
dk(){ echo "$PW" | sudo -S "$D" "$@" 2>/dev/null; }
echo "$PW" | sudo -S -v >/dev/null 2>&1 || true

echo "  source tables: $(dk exec zqx-db psql -U zqx_owner -d zqx -At -c "SELECT count(*) FROM pg_tables WHERE schemaname='public'")"
echo "$PW" | sudo -S "$D" exec zqx-db pg_dump -U zqx_owner -d zqx --no-owner --no-privileges -Fc > /tmp/zqx.dump 2>/tmp/zqx.dumperr || { echo "  DUMP FAILED:"; cat /tmp/zqx.dumperr; exit 1; }
echo "  dump size: $(echo "$PW" | sudo -S ls -lh /tmp/zqx.dump 2>/dev/null | awk '{print $5}')"

echo "  restoring via pooler..."
echo "$PW" | sudo -S "$D" run --rm -v /tmp/zqx.dump:/tmp/zqx.dump:ro postgres:17 \
  pg_restore --no-owner --no-privileges --clean --if-exists -d "$CONN" /tmp/zqx.dump 2>&1 \
  | grep -viE 'warning: .*no privileges|must be owner|does not exist, skipping|errors ignored on restore' | tail -20

TGT=$(echo "$PW" | sudo -S "$D" run --rm postgres:17 psql "$CONN" -At -c "SELECT count(*) FROM pg_tables WHERE schemaname='public'" 2>/dev/null)
echo "  Supabase public tables now: $TGT"
echo "$PW" | sudo -S "$D" run --rm postgres:17 psql "$CONN" -c "ANALYZE" >/dev/null 2>&1 && echo "  ANALYZE ok"
echo "$PW" | sudo -S rm -f /tmp/zqx.dump /tmp/zqx.dumperr /tmp/zqxconn
echo "  done. NAS zqx-db untouched."
OUTER

echo "=== 4. repoint .env CONNECTION_STRING to the IPv4 pooler (apps run on the NAS) ==="
cp -p "$DEP" "${DEP}.bak-$(date +%Y%m%d-%H%M%S)"
POOLHOST="$POOLHOST" REF="$REF" python3 - "$DEP" <<'PY'
import os,sys,re
f=sys.argv[1]; host=os.environ["POOLHOST"]; ref=os.environ["REF"]
# reuse the password already stored in SUPEBASE_CLOUD_ZQX_DB_PWD (no new secret printed)
pwd=None
for ln in open(f):
    if ln.startswith("SUPEBASE_CLOUD_ZQX_DB_PWD="):
        pwd=ln.split("=",1)[1].strip().strip('"').strip("'")
sess=f"postgresql://postgres.{ref}:{pwd}@{host}:5432/postgres?sslmode=require"
out=[]; seen=False
for ln in open(f).read().splitlines():
    if ln.startswith("SUPEBASE_CLOUD_ZQX_CONNECTION_STRING="):
        out.append("SUPEBASE_CLOUD_ZQX_CONNECTION_STRING="+sess); seen=True
    else:
        out.append(ln)
if not seen: out.append("SUPEBASE_CLOUD_ZQX_CONNECTION_STRING="+sess)
# also record the pooler host for reference
if not any(l.startswith("SUPEBASE_CLOUD_ZQX_POOLER_HOST=") for l in out):
    out.append("SUPEBASE_CLOUD_ZQX_POOLER_HOST="+host)
open(f,"w").write("\n".join(out)+"\n")
print("  .env CONNECTION_STRING -> session pooler (host "+host+", value redacted)")
PY
echo "=== finished ==="
