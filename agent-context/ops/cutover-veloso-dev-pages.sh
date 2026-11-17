#!/usr/bin/env bash
# PRODUCTION CUTOVER: move veloso.dev off the NAS onto Cloudflare Pages (project veloso-dev).
# Pages deploy already done + verified (real content) at https://veloso-dev.pages.dev.
# This: attaches custom domains + repoints DNS off the NAS tunnel, then stops the NAS container.
# Reversible: PATCH the CNAMEs back to 563c6977-...cfargotunnel.com + start p-veloso-dev.
#   Run:  ! bash agent-context/ops/cutover-veloso-dev-pages.sh
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
EMAIL=$(grep -E '^CLOUDFLARE_EMAIL=' .env | head -1 | cut -d= -f2-)
GKEY=$(grep -E '^CLOUDFLARE_GLOBAL_API_KEY=' .env | head -1 | cut -d= -f2-)
ACCT=c0d5c842ba1e9bea5a5ad662ddb22e83
ZID=32316fb6f792d0125902ed1f51c086d0      # veloso.dev zone
PAGES=veloso-dev.pages.dev
PW=$(grep -E '^NAS_SSH_PASSWORD=' .env | head -1 | cut -d= -f2-)
D=/var/packages/ContainerManager/target/usr/bin/docker
NAS="ssh -i $HOME/.ssh/id_ed25519_zqx_nas -o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o ConnectTimeout=12 pedro@192.168.1.109"
cf(){ curl -s -H "X-Auth-Email: $EMAIL" -H "X-Auth-Key: $GKEY" -H "Content-Type: application/json" "$@"; }

# veloso.dev + www are the primary site; p/pv/cv/resume are same-content aliases (move so they don't 502
# when the NAS container stops). test.veloso.dev is left as-is.
HOSTS="veloso.dev www.veloso.dev p.veloso.dev pv.veloso.dev cv.veloso.dev resume.veloso.dev"

for H in $HOSTS; do
  RID=$(cf "https://api.cloudflare.com/client/v4/zones/$ZID/dns_records?name=$H&type=CNAME" | python3 -c 'import sys,json;r=json.load(sys.stdin)["result"];print(r[0]["id"] if r else "")')
  if [ -n "$RID" ]; then
    cf -X PATCH "https://api.cloudflare.com/client/v4/zones/$ZID/dns_records/$RID" \
       --data "{\"content\":\"$PAGES\",\"proxied\":true}" \
       | python3 -c 'import sys,json;d=json.load(sys.stdin);print("  DNS '"$H"' ->",d["result"]["content"] if d["success"] else ("ERR",d.get("errors")))'
  else echo "  (no CNAME for $H — skip)"; fi
  cf -X POST "https://api.cloudflare.com/client/v4/accounts/$ACCT/pages/projects/veloso-dev/domains" \
     --data "{\"name\":\"$H\"}" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("  Pages domain '"$H"':", "added" if d.get("success") else d.get("errors"))' 2>/dev/null
done

echo "=== verify (allow edge + cert) ==="
sleep 8
for H in veloso.dev www.veloso.dev; do
  curl -s -o /dev/null -w "  https://$H/ => %{http_code}\n" --max-time 15 "https://$H/"
done

echo "=== stop NAS p-veloso-dev (kept, restart=no) ==="
$NAS "echo '$PW' | sudo -S sh -c '$D update --restart=no p-veloso-dev >/dev/null 2>&1; $D stop p-veloso-dev >/dev/null 2>&1 && echo stopped' 2>/dev/null" 2>/dev/null
echo "DONE. Rollback: PATCH the CNAMEs back to 563c6977-9a9e-4338-ac35-cebaffdb991b.cfargotunnel.com + start p-veloso-dev."
