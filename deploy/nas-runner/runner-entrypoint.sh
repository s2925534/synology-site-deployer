#!/usr/bin/env bash
# VDEV-33 — ephemeral GitHub Actions runner, authenticated via the "VelosoLabs CI
# Watchdog" GitHub App (no PAT). Registers one-shot (--ephemeral), runs a single
# job, de-registers, then loops with a fresh token. Docker builds go to the dind
# sidecar via DOCKER_HOST (TLS), never the NAS's own Docker socket.
#
# Required env:
#   APP_ID                GitHub App id (5960516)
#   APP_INSTALLATION_ID   installation id for the target org/owner
#   APP_PRIVATE_KEY_FILE  path to the App private key PEM (mounted read-only)
#   GH_SCOPE              "org" or "repo"
#   GH_TARGET             org login (scope=org) or "owner/repo" (scope=repo)
#   RUNNER_NAME           unique runner name
#   RUNNER_LABELS         e.g. "self-hosted,nas"
#   RUNNER_GROUP          org runner group (scope=org only); default "Default"
# Optional:
#   DOCKER_HOST           tcp://dind:2376 (set in compose); DOCKER_TLS_* for TLS
set -euo pipefail

: "${APP_ID:?}" "${APP_INSTALLATION_ID:?}" "${APP_PRIVATE_KEY_FILE:?}"
: "${GH_SCOPE:?}" "${GH_TARGET:?}" "${RUNNER_NAME:?}" "${RUNNER_LABELS:=self-hosted,nas}"
RUNNER_GROUP="${RUNNER_GROUP:-Default}"
API="https://api.github.com"

b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }

app_jwt() {
  local now header payload si sig
  now=$(date +%s)
  header=$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)
  payload=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' "$((now-60))" "$((now+540))" "$APP_ID" | b64url)
  si="${header}.${payload}"
  sig=$(printf '%s' "$si" | openssl dgst -sha256 -sign "$APP_PRIVATE_KEY_FILE" -binary | b64url)
  printf '%s.%s' "$si" "$sig"
}

installation_token() {
  curl -fsS -X POST \
    -H "Authorization: Bearer $(app_jwt)" \
    -H "Accept: application/vnd.github+json" \
    "$API/app/installations/${APP_INSTALLATION_ID}/access_tokens" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])'
}

registration_token() {
  local itok="$1" url
  if [ "$GH_SCOPE" = "org" ]; then
    url="$API/orgs/${GH_TARGET}/actions/runners/registration-token"
  else
    url="$API/repos/${GH_TARGET}/actions/runners/registration-token"
  fi
  curl -fsS -X POST \
    -H "Authorization: token ${itok}" \
    -H "Accept: application/vnd.github+json" "$url" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])'
}

runner_url() {
  if [ "$GH_SCOPE" = "org" ]; then echo "https://github.com/${GH_TARGET}"
  else echo "https://github.com/${GH_TARGET}"; fi
}

cleanup() {
  # Best-effort de-register if we die mid-job.
  if [ -f .runner ]; then
    local itok; itok=$(installation_token) || return 0
    ./config.sh remove --token "$(registration_token "$itok")" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

echo "[$(date -u +%FT%TZ)] ${RUNNER_NAME}: scope=${GH_SCOPE} target=${GH_TARGET} group=${RUNNER_GROUP}"

while true; do
  ITOK=$(installation_token)
  REG=$(registration_token "$ITOK")
  GROUP_ARG=""; [ "$GH_SCOPE" = "org" ] && GROUP_ARG="--runnergroup ${RUNNER_GROUP}"
  ./config.sh \
    --url "$(runner_url)" \
    --token "$REG" \
    --name "$RUNNER_NAME" \
    --labels "$RUNNER_LABELS" \
    $GROUP_ARG \
    --work _work \
    --ephemeral \
    --unattended \
    --replace
  # --ephemeral: run exactly one job, then exit cleanly (auto de-registers).
  ./run.sh || true
  echo "[$(date -u +%FT%TZ)] ${RUNNER_NAME}: job cycle done, re-registering"
  sleep 2
done
