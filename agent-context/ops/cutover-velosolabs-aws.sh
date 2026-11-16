#!/usr/bin/env bash
# PRODUCTION CUTOVER: velosolabs.com + mcp.velosolabs.com  NAS tunnel -> velosolabs-aws (Lightsail).
#
# Prereqs already in place (done during the migration, verified on staging):
#   - Box velosolabs-prod runs hub (`velosolabs`) + gateway/admin on compose project `velosolabs`.
#   - velosolabs-aws tunnel ingress already contains BOTH prod hostnames (inert until DNS flips).
#   - Staging verified: hub-staging.velosolabs.com/health=200, mcp-staging.velosolabs.com/healthz=200.
#
# What this does:
#   1. Takes a FRESH consistent hub SQLite snapshot from the NAS (sqlite .backup, no downtime on NAS)
#      and loads it into the box volume (brief box-hub restart) so no licence/account writes are lost.
#   2. Flips the two prod CNAMEs to the new tunnel.
#   3. Verifies prod URLs.
# NAS containers are left running (rollback = flip the 2 CNAMEs back to 563c6977-...).
#
# Run from repo root:  ! bash agent-context/ops/cutover-velosolabs-aws.sh
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
ENVF=.env
PW=$(grep -E '^NAS_SSH_PASSWORD=' "$ENVF" | head -1 | cut -d= -f2-)
EMAIL=$(grep -E '^CLOUDFLARE_EMAIL=' "$ENVF" | head -1 | cut -d= -f2-)
GKEY=$(grep -E '^CLOUDFLARE_GLOBAL_API_KEY=' "$ENVF" | head -1 | cut -d= -f2-)
ZID=3d751b83ed956fd384025f287844759c
NEW_TUN=98135949-50a1-4deb-a74b-4ff60dec2085
TGT="$NEW_TUN.cfargotunnel.com"
OLD_TGT="563c6977-9a9e-4338-ac35-cebaffdb991b.cfargotunnel.com"  # rollback target
DOCKER=/var/packages/ContainerManager/target/usr/bin/docker
TMP=/Users/pedro/.claude-account2/jobs/1439e211/tmp   # has boxssh.sh (fresh-cert ssh helper)
NAS="ssh -i $HOME/.ssh/id_ed25519_zqx_nas -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o ConnectTimeout=15 pedro@192.168.1.109"
cf(){ curl -s -H "X-Auth-Email: $EMAIL" -H "X-Auth-Key: $GKEY" -H "Content-Type: application/json" "$@"; }

echo "=== 1/3 fresh hub SQLite snapshot NAS -> box ==="
# Consistent online backup inside the NAS hub container, stream to box, swap into the live volume.
$NAS "echo '$PW' | sudo -S $DOCKER exec velosolabs sh -c 'sqlite3 /app/data/hub.db \".backup /tmp/hub.db\" && cat /tmp/hub.db && rm -f /tmp/hub.db' 2>/dev/null" 2>/dev/null \
  | "$TMP/boxssh.sh" "cat > /tmp/hub.db && \
      docker cp /tmp/hub.db velosolabs-velosolabs-1:/app/data/hub.db && \
      docker restart velosolabs-velosolabs-1 >/dev/null && echo 'hub.db refreshed + hub restarted'"
echo "   (theme-releases/downloads already copied at migration; re-run the migration tar if they changed)"

echo "=== 2/3 flip the two prod CNAMEs to velosolabs-aws ==="
for H in velosolabs.com mcp.velosolabs.com; do
  RID=$(cf "https://api.cloudflare.com/client/v4/zones/$ZID/dns_records?name=$H&type=CNAME" | python3 -c 'import sys,json;r=json.load(sys.stdin)["result"];print(r[0]["id"] if r else "")')
  [ -z "$RID" ] && { echo "  !! no CNAME found for $H — ABORT"; exit 1; }
  cf -X PATCH "https://api.cloudflare.com/client/v4/zones/$ZID/dns_records/$RID" \
     --data "{\"content\":\"$TGT\",\"proxied\":true}" \
     | python3 -c 'import sys,json;d=json.load(sys.stdin);print("  '"$H"' ->",d["result"]["content"] if d["success"] else ("ERR",d.get("errors")))'
done

echo "=== 3/3 verify prod (allow a few seconds for edge update) ==="
sleep 5
curl -s -m 25 -o /dev/null -w "  https://velosolabs.com/        HTTP %{http_code}\n" https://velosolabs.com/
curl -s -m 25 -o /dev/null -w "  https://velosolabs.com/health  HTTP %{http_code}\n" https://velosolabs.com/health
curl -s -m 25 -o /dev/null -w "  https://mcp.velosolabs.com/healthz HTTP %{http_code}\n" https://mcp.velosolabs.com/healthz
echo
echo "DONE. Rollback if needed: PATCH both CNAMEs back to $OLD_TGT"
echo "After a clean soak, stop the NAS hub + mcp-gateway containers (they remain up as fallback until then)."
