# NAS self-hosted GitHub Actions runners (VDEV-33)

Ephemeral GitHub Actions runners on the NAS (8 CPU / 31 GiB), so CI builds use no
GitHub-hosted minutes. Images are pushed to GHCR and deployed to Lightsail by the
existing Watchtower — unchanged. A Cloudflare Worker watchdog flips CI back to
GitHub-hosted runners automatically if the NAS drops, so **deployments never stall**.

## How it works
- Each runner authenticates with the **"VelosoLabs CI Watchdog" GitHub App** (no PATs).
  `runner-entrypoint.sh` mints an App JWT → installation token → runner registration
  token, registers with `--ephemeral` (one job, then re-register), and loops.
- Each runner has its **own Docker-in-Docker sidecar over TLS** (`DOCKER_HOST=tcp://dind-N:2376`).
  Builds never touch the NAS's Docker socket. The dind volume keeps a warm layer cache.
- A workflow runs here only when its `CI_RUNNER` variable == `nas` (see each repo's
  Phase-A workflow switch). Until then runners sit **idle** and nothing routes to them.

## Scope (important)
A GitHub self-hosted runner attaches to **one scope** — an **org** or a **single repo**;
it cannot serve multiple orgs. So:
- **This stack → the `zqxio` org** (`GH_SCOPE=org`, `GH_TARGET=zqxio`): one runner group
  serves `zqx` + `zqx-node` (the biggest minutes consumer). ✅ no repo moves needed.
- **`s2925534` personal repos** (velosolabs, resilinked, winnow-bid, …): GitHub does **not**
  support user-account runner groups. To cover them with shared runners, move the active
  product repos into the **`velosolabs` org** and run a second copy of this stack scoped to
  it (`GH_TARGET=velosolabs`, install id `186673212`). Until then, those repos keep running
  on GitHub-hosted runners (their Phase-A switch stays inert). Per-repo runners are possible
  (`GH_SCOPE=repo`) but one runner set only serves one repo, so it doesn't scale.

## Deploy (on the NAS)
1. Put the App key on the NAS, not in git:
   `mkdir -p /volume3/dockernvme/nas-ci-runner && cp <key> /volume3/dockernvme/nas-ci-runner/ci-watchdog-app.pem && chmod 600 …`
2. Copy this directory next to it, `cp .env.example .env`, and fill `.env`.
3. `docker compose --env-file .env up -d --build`
4. Confirm 3 idle runners appear: GitHub → org **Settings → Actions → Runners**
   (or `gh api orgs/zqxio/actions/runners`). They should be **Idle**.
5. Add the project in **Container Manager** so it auto-starts with the Docker package.

## Operations
- **Take the NAS offline (test fallback):** `docker compose down`. Within ~5 min the
  watchdog sees no heartbeat and sets `CI_RUNNER=github` on the org; CI continues on
  GitHub-hosted runners. Bring it back with `up -d`; the watchdog flips back to `nas`.
- **Force fallback manually:** set the org variable `CI_RUNNER=github`
  (`gh variable set CI_RUNNER -o zqxio --body github`) or delete it.
- **Rotate the App key / HMAC secret:** replace the file / `.env` value and
  `docker compose up -d --force-recreate`; update the matching Worker secret.

## Security / SOC 2 notes
- dind is privileged but **contained to the sidecar**; the NAS Docker socket is never mounted.
- No NAS shared folders are mounted into runners — only named volumes + the App key (read-only).
- Per-container CPU/RAM caps; no published ports (outbound only).
- Runners are **private-repo only** (the App is installed on private repos); no fork-PR code runs.
- Accepted residual risk: runners share the NAS host kernel with other NAS containers
  (documented in each product's `docs/soc2-report.md`).
