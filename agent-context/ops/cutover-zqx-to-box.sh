#!/usr/bin/env bash
# PRODUCTION CUTOVER: zqx.io  NAS tunnel (563c6977…) -> AWS box tunnel (98135949…, velosolabs-aws).
#
# Prereqs (DONE + verified): all 10 zqx containers run on the box (prod api -> Supabase Sydney
# pocefahesgwsugicjtgw; staging api -> box zqx-db/zqx_staging; 7 frontends). The velosolabs-aws tunnel
# already has ingress for the 9 hostnames below -> zqx containers (inert until this DNS flip).
#
# Flips 9 CNAMEs (the 3 retired hostnames connect/control/status are NOT touched — dead on the NAS already).
# Reversible: ROLLBACK=1 flips them back. Optional second phase STOP_NAS=1 stops the NAS zqx containers
# AFTER a clean soak (keeps them, restart=no).
#
# Run from repo root:  ! bash agent-context/ops/cutover-zqx-to-box.sh
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
EMAIL=$(grep -E '^CLOUDFLARE_EMAIL=' .env | head -1 | cut -d= -f2-)
GKEY=$(grep -E '^CLOUDFLARE_GLOBAL_API_KEY=' .env | head -1 | cut -d= -f2-)
NEW=98135949-50a1-4deb-a74b-4ff60dec2085.cfargotunnel.com
OLD=563c6977-9a9e-4338-ac35-cebaffdb991b.cfargotunnel.com
HOSTS="zqx.io www.zqx.io api.zqx.io app.zqx.io field.zqx.io portal.zqx.io api.staging.zqx.io app.staging.zqx.io portal.staging.zqx.io"
cf(){ curl -s -H "X-Auth-Email: $EMAIL" -H "X-Auth-Key: $GKEY" -H "Content-Type: application/json" "$@"; }
ZID=$(cf "https://api.cloudflare.com/client/v4/zones?name=zqx.io" | python3 -c 'import sys,json;r=json.load(sys.stdin)["result"];print(r[0]["id"] if r else "")')
[ -z "$ZID" ] && { echo "no zqx.io zone"; exit 1; }
TGT="$NEW"; [ "${ROLLBACK:-0}" = "1" ] && TGT="$OLD"

if [ "${STOP_NAS:-0}" = "1" ]; then
  echo "=== STOP NAS zqx containers (restart=no, kept) ==="
  PW=$(grep -E '^NAS_SSH_PASSWORD=' .env | head -1 | cut -d= -f2-)
  D=/var/packages/ContainerManager/target/usr/bin/docker
  NH=192.168.1.109; ssh -i ~/.ssh/id_ed25519_zqx_nas -o IdentitiesOnly=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=no pedro@$NH 'echo ok' >/dev/null 2>&1 || NH=100.107.233.45
  ssh -i ~/.ssh/id_ed25519_zqx_nas -o IdentitiesOnly=yes -o StrictHostKeyChecking=no pedro@$NH \
    "echo '$PW' | sudo -S sh -c 'for c in zqx-api zqx-api-staging zqx-app zqx-app-staging zqx-field zqx-field-staging zqx-portal zqx-portal-staging zqx-site zqx-db; do $D update --restart=no \$c >/dev/null 2>&1; $D stop \$c >/dev/null 2>&1 && echo stopped \$c; done' 2>/dev/null" 2>/dev/null
  echo "DONE stop. (zqx-connect/zqx-control already down.)"; exit 0
fi

echo "=== flip 9 zqx.io CNAMEs -> $TGT ==="
for H in $HOSTS; do
  RID=$(cf "https://api.cloudflare.com/client/v4/zones/$ZID/dns_records?name=$H&type=CNAME" | python3 -c 'import sys,json;r=json.load(sys.stdin)["result"];print(r[0]["id"] if r else "")')
  [ -z "$RID" ] && { echo "  !! no CNAME for $H — skip"; continue; }
  cf -X PATCH "https://api.cloudflare.com/client/v4/zones/$ZID/dns_records/$RID" \
     --data "{\"content\":\"$TGT\",\"proxied\":true}" \
     | python3 -c 'import sys,json;d=json.load(sys.stdin);print("  '"$H"' ->", d["result"]["content"] if d["success"] else ("ERR",d.get("errors")))'
done
echo "=== verify (allow edge propagation) ==="
sleep 6
for H in zqx.io app.zqx.io api.zqx.io portal.zqx.io field.zqx.io api.staging.zqx.io; do
  printf '  %-26s ' "$H"; curl -s -o /dev/null -w 'HTTP %{http_code}\n' -m 15 "https://$H/health" 2>&1 || echo "(no /health; try /)"
done
echo
echo "DONE flip. zqx now served from the AWS box. NAS zqx still running as fallback."
echo "After a clean soak, stop the NAS copies:  ! STOP_NAS=1 bash agent-context/ops/cutover-zqx-to-box.sh"
echo "Rollback:                                 ! ROLLBACK=1 bash agent-context/ops/cutover-zqx-to-box.sh"
