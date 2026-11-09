#!/bin/bash
set -uo pipefail
DEP=/Users/pedro/Documents/_Projects/synology-site-deployer/.env
getk(){ grep -m1 -E "^$1=" "$DEP" | sed -E "s/^$1=//" | tr -d '\r' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"; }
REF=$(getk SUPEBASE_CLOUD_ZQX_PROJECT_ID)
HOST=$(getk SUPEBASE_CLOUD_ZQX_POOLER_HOST)
export PGPASSWORD=$(getk SUPEBASE_CLOUD_ZQX_DB_PWD)
export PGCONNECT_TIMEOUT=10 PGSSLMODE=require

# dynamic total row count across all public tables
SQL="SELECT coalesce(sum(cnt),0) FROM (SELECT (xpath('/row/c/text()', query_to_xml(format('select count(*) c from %I.%I', schemaname, tablename), false, true, '')))[1]::text::bigint cnt FROM pg_tables WHERE schemaname='public') s;"

echo "=== TARGET (Supabase pooler, ap-northeast-1) ==="
TGT_TBL=$(psql "host=$HOST port=5432 user=postgres.$REF dbname=postgres sslmode=require" -tAc "SELECT count(*) FROM pg_tables WHERE schemaname='public'")
TGT_ROWS=$(psql "host=$HOST port=5432 user=postgres.$REF dbname=postgres sslmode=require" -tAc "$SQL")
echo "  tables=$TGT_TBL  total_rows=$TGT_ROWS"
echo "  sample:"; psql "host=$HOST port=5432 user=postgres.$REF dbname=postgres sslmode=require" -tAc \
  "SELECT '    '||t||': '||(xpath('/row/c/text()', query_to_xml(format('select count(*) c from public.%I',t),false,true,'')))[1]::text FROM (VALUES ('users'),('bookings'),('audit_entries')) v(t)"

echo "=== SOURCE (NAS zqx-db) ==="
ssh -i ~/.ssh/id_ed25519_zqx_nas -o IdentitiesOnly=yes -o ConnectTimeout=15 pedro@192.168.1.109 'bash -s' <<'OUTER' 2>&1 | grep -viE "post-quantum|store now|openssh.com/pq|vulnerable|^\*\*|secure_path"
DEPENV=/volume1/homes/pedro/Projects/synology-site-deployer-excluded-backup/synology-site-deployer/.env
PW=$(grep -E '^NAS_SSH_PASSWORD=' "$DEPENV" | head -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"//' -e 's/"$//')
D=/var/packages/ContainerManager/target/usr/bin/docker
SQL="SELECT coalesce(sum(cnt),0) FROM (SELECT (xpath('/row/c/text()', query_to_xml(format('select count(*) c from %I.%I', schemaname, tablename), false, true, '')))[1]::text::bigint cnt FROM pg_tables WHERE schemaname='public') s;"
echo "  total_rows=$(echo "$PW" | sudo -S "$D" exec zqx-db psql -U zqx_owner -d zqx -tAc "$SQL" 2>/dev/null)"
echo "  sample:"; echo "$PW" | sudo -S "$D" exec zqx-db psql -U zqx_owner -d zqx -tAc \
  "SELECT '    '||t||': '||(xpath('/row/c/text()', query_to_xml(format('select count(*) c from public.%I',t),false,true,'')))[1]::text FROM (VALUES ('users'),('bookings'),('audit_entries')) v(t)" 2>/dev/null
OUTER
echo "=== done ==="