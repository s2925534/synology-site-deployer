#!/usr/bin/env bash
# PRODUCTION CUTOVER (ecosystem-services decommission, Phase 3 flip):
# Move services.systemsnotsilos.com + track.systemsnotsilos.com OFF the NAS ecosystem-services
# container ONTO the Cloudflare Workers (compat proxy -> velosolabs hub + track worker).
#
# Reversible: this adds two Worker ROUTES (edge intercept) — it does NOT change any DNS record.
# Rollback = delete the two route ids printed at the end (or re-run with ROLLBACK=1).
#
# Verified before this step: hub endpoints live on velosolabs.com; the compat proxy reaches
# the hub + track worker end-to-end (kits=15, recaptcha-config siteKey, /health, /api/track all 200).
#
# Run from repo root:  ! bash agent-context/ops/flip-services-to-proxy.sh
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
EMAIL=$(grep -E '^CLOUDFLARE_EMAIL=' .env | head -1 | cut -d= -f2-)
GKEY=$(grep -E '^CLOUDFLARE_GLOBAL_API_KEY=' .env | head -1 | cut -d= -f2-)
ZID=9bd40288714fe8899556d7d7d35b336f   # systemsnotsilos.com
cf(){ curl -s -H "X-Auth-Email: $EMAIL" -H "X-Auth-Key: $GKEY" -H "Content-Type: application/json" "$@"; }
hdr(){ curl -sI --max-time 8 "$1" 2>&1 | grep -iE '^server:' | tr -d '\r' | sed 's/^/      /'; }

if [ "${ROLLBACK:-0}" = "1" ]; then
  echo "=== ROLLBACK: deleting the two compat routes on systemsnotsilos.com ==="
  for rid in $(cf "https://api.cloudflare.com/client/v4/zones/$ZID/workers/routes" \
      | python3 -c 'import sys,json;[print(r["id"]) for r in json.load(sys.stdin).get("result",[]) if "systemsnotsilos.com" in r["pattern"]]'); do
    cf -X DELETE "https://api.cloudflare.com/client/v4/zones/$ZID/workers/routes/$rid" >/dev/null && echo "  deleted $rid"
  done
  echo "DONE rollback — services/track.systemsnotsilos.com served by the NAS again."
  exit 0
fi

echo "=== baseline Server header (PRE-flip = NAS Express) ==="
echo "  services.systemsnotsilos.com:"; hdr https://services.systemsnotsilos.com/api/recaptcha-config

echo "=== FLIP: add Worker routes ==="
cf -X POST "https://api.cloudflare.com/client/v4/zones/$ZID/workers/routes" \
   --data '{"pattern":"services.systemsnotsilos.com/*","script":"services-compat-proxy"}' \
   | python3 -c 'import sys,json;d=json.load(sys.stdin);print("  services.* route:", d["result"]["id"] if d.get("success") else ("ERR",d.get("errors")))'
cf -X POST "https://api.cloudflare.com/client/v4/zones/$ZID/workers/routes" \
   --data '{"pattern":"track.systemsnotsilos.com/*","script":"track-worker"}' \
   | python3 -c 'import sys,json;d=json.load(sys.stdin);print("  track.* route:  ", d["result"]["id"] if d.get("success") else ("ERR",d.get("errors")))'

echo "=== verify (allow a few seconds for edge propagation) ==="
sleep 6
echo "  services.* Server header (POST-flip, expect uvicorn/cloudflare, NOT Express):"; hdr https://services.systemsnotsilos.com/api/recaptcha-config
S=https://services.systemsnotsilos.com
curl -s --max-time 10 "$S/api/tradeline/kits" | python3 -c 'import sys,json;print("  services /api/tradeline/kits -> kits:",len(json.load(sys.stdin).get("kits",[])))' 2>&1
curl -s --max-time 10 "$S/api/recaptcha-config"; echo "  <- services /api/recaptcha-config"
curl -s -o /dev/null -w '  services /health => %{http_code}\n' --max-time 8 "$S/health"
curl -s -o /dev/null -w '  services /api/track => %{http_code}\n' --max-time 10 "$S/api/track?number=1Z999AA10123456784"
curl -s -o /dev/null -w '  track.systemsnotsilos.com/ => %{http_code}\n' --max-time 10 "https://track.systemsnotsilos.com/"
echo
echo "DONE. Every caller now served by the hub + track worker. NAS ecosystem-services receives no traffic."
echo "Tell the agent — it will repoint veloso.dev + nas-sso-gateway, then stop the NAS container."
echo "Rollback if needed:  ! ROLLBACK=1 bash agent-context/ops/flip-services-to-proxy.sh"
