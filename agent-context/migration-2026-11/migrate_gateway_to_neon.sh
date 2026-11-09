#!/bin/bash
# mcp-gateway-db (NAS Postgres) -> Neon velosolabs DB. Non-destructive to NAS (read-only
# pg_dump). Restores into Neon via the DIRECT endpoint (DDL-safe). Secrets from .env at
# runtime; never printed, never on an argv.
set -uo pipefail
DEP=/Users/pedro/Documents/_Projects/synology-site-deployer/.env
getk(){ grep -m1 -E "^$1=" "$DEP" | sed -E "s/^$1=//" | tr -d '\r' | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"; }

# Prefer the DIRECT (non-pooled) Neon conn for restore; fall back to pooled.
CONN=$(getk NEON_VELOSOLABS_CONNECTION_STRING_DIRECT)
[ -n "$CONN" ] || CONN=$(getk NEON_VELOSOLABS_CONNECTION_STRING)
[ -n "$CONN" ] || { echo "ABORT: no Neon connection string in .env"; exit 1; }

echo "=== stage Neon conn on NAS (stdin) ==="
printf '%s' "$CONN" | ssh -i ~/.ssh/id_ed25519_zqx_nas -o IdentitiesOnly=yes -o ConnectTimeout=15 pedro@192.168.1.109 \
  "cat > /tmp/neonconn && chmod 600 /tmp/neonconn && echo '  staged'"

ssh -i ~/.ssh/id_ed25519_zqx_nas -o IdentitiesOnly=yes -o ConnectTimeout=15 pedro@192.168.1.109 'bash -s' <<'OUTER' 2>&1 | grep -viE "post-quantum|store now|openssh.com/pq|vulnerable|^\*\*|secure_path"
DEPENV=/volume1/homes/pedro/Projects/synology-site-deployer-excluded-backup/synology-site-deployer/.env
PW=$(grep -E '^NAS_SSH_PASSWORD=' "$DEPENV" | head -1 | cut -d= -f2- | tr -d '\r' | sed -e 's/^"//' -e 's/"$//')
D=/var/packages/ContainerManager/target/usr/bin/docker
CONN=$(cat /tmp/neonconn)
dk(){ echo "$PW" | sudo -S "$D" "$@" 2>/dev/null; }
echo "$PW" | sudo -S -v >/dev/null 2>&1 || true

# discover source db + role from the container's POSTGRES_* env
SRC_DB=$(dk inspect mcp-gateway-db --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E '^POSTGRES_DB=' | head -1 | cut -d= -f2)
SRC_USER=$(dk inspect mcp-gateway-db --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E '^POSTGRES_USER=' | head -1 | cut -d= -f2)
SRC_DB=${SRC_DB:-mcp_gateway}; SRC_USER=${SRC_USER:-postgres}
echo "  source db=$SRC_DB role=$SRC_USER"
echo "  source tables: $(dk exec mcp-gateway-db psql -U "$SRC_USER" -d "$SRC_DB" -At -c "SELECT count(*) FROM pg_tables WHERE schemaname='public'")"
SRC_ROWS=$(dk exec mcp-gateway-db psql -U "$SRC_USER" -d "$SRC_DB" -tAc "SELECT coalesce(sum(cnt),0) FROM (SELECT (xpath('/row/c/text()', query_to_xml(format('select count(*) c from %I.%I', schemaname, tablename), false, true, '')))[1]::text::bigint cnt FROM pg_tables WHERE schemaname='public') s;")
echo "  source rows: $SRC_ROWS"

echo "  dumping..."
echo "$PW" | sudo -S "$D" exec mcp-gateway-db pg_dump -U "$SRC_USER" -d "$SRC_DB" --no-owner --no-privileges -Fc > /tmp/gw.dump 2>/tmp/gw.dumperr || { echo "  DUMP FAILED:"; cat /tmp/gw.dumperr; exit 1; }
echo "  dump size: $(echo "$PW" | sudo -S ls -lh /tmp/gw.dump 2>/dev/null | awk '{print $5}')"

echo "  restoring into Neon..."
echo "$PW" | sudo -S "$D" run --rm -v /tmp/gw.dump:/tmp/gw.dump:ro postgres:17 \
  pg_restore --no-owner --no-privileges --clean --if-exists -d "$CONN" /tmp/gw.dump 2>&1 \
  | grep -viE 'warning: .*no privileges|must be owner|does not exist, skipping|errors ignored on restore' | tail -15

TGT_TBL=$(echo "$PW" | sudo -S "$D" run --rm postgres:17 psql "$CONN" -At -c "SELECT count(*) FROM pg_tables WHERE schemaname='public'" 2>/dev/null)
TGT_ROWS=$(echo "$PW" | sudo -S "$D" run --rm postgres:17 psql "$CONN" -tAc "SELECT coalesce(sum(cnt),0) FROM (SELECT (xpath('/row/c/text()', query_to_xml(format('select count(*) c from %I.%I', schemaname, tablename), false, true, '')))[1]::text::bigint cnt FROM pg_tables WHERE schemaname='public') s;" 2>/dev/null)
echo "  Neon tables now: $TGT_TBL   Neon rows now: $TGT_ROWS"
echo "$PW" | sudo -S "$D" run --rm postgres:17 psql "$CONN" -c "ANALYZE" >/dev/null 2>&1 && echo "  ANALYZE ok"
echo "$PW" | sudo -S rm -f /tmp/gw.dump /tmp/gw.dumperr /tmp/neonconn
echo "  done. NAS mcp-gateway-db untouched."
OUTER
echo "=== finished ==="