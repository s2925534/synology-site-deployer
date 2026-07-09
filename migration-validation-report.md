# Docker/SSD Migration — Read-Only Validation Report

Generated 2026-07-09 via a read-only SSH survey of the live NAS (192.168.1.109). No files were
written, no containers were started/stopped/pulled, and no destructive commands were run against
the NAS during this review.

## A. Executive Summary

**Partially safe.** The backup/dump mechanics themselves are sound and already running
successfully on schedule with no disruption to live containers. But there's one structural finding
that should be resolved before touching Container Manager: **the actual SSD copy did not land
where expected.** `/volume2/DockerSSD/apps` (the stated target) doesn't exist — the real data is
nested under `/volume2/DockerSSD/archive/copied-from-docker-ssd/apps`, alongside a separate
`compose/` folder with what looks like the same files, and a third, currently-empty
`/volume2/DockerSSD/ssd-deploy` directory. There are also a few concrete gaps in the backup
scripts (a silent-failure edge case, no interlock between the two nightly jobs) and one container
(`cloudflared`) that isn't managed by any compose file at all. None of this is urgent or dangerous
today — nothing live has been touched — but all of it should be resolved before starting the
Container Manager export/import.

## B. Current State Confirmed

- **Live containers** (`docker ps -a`, still all on `/volume1/docker`, none touched): all 20
  expected containers exist and are `Up`, **except `realtime-dev.supabase-realtime`, which is
  currently `Exited (0)`** — not running.
- **Compose files** found under `/volume1/docker/`: `newsite-example`, `supabase` (12 compose
  files — base + dev/caddy/envoy/logs/nginx/pg15/pg17/rustfs/s3/override/tests),
  `resilinked-api-example-com`, `resilinked-app-example-com`, `proxy-resilinked-example-com`,
  `resilinked-watchtower-example-com`, `health-example-com`, `test-example-com`. Each
  `resilinked-*-example-com` folder also contains a full nested git clone (`repo/`) with its own
  `infra/*/docker-compose.*.yml` files — these are **not** the ones actually running (see D10).
- **`/volume2/DockerSSD` actual layout**: `archive/copied-from-docker-ssd/{apps,compose,web,databases,logs,notes}`,
  `backups/{...}`, and an empty `ssd-deploy/`. **`apps/` directly under `DockerSSD/` does not exist.**
- **`/volume2/docker-ssd`** (lowercase, separate top-level dir) exists but is root-owned,
  permission-denied even to the `pedro` account.
- **`backup-databases.sh`**: present, functional, 3 successful runs logged (2026-07-08 21:13,
  2026-07-09 01:45, 02:45), each producing both dump files + container-inspect JSON + a
  `docker ps -a` snapshot, `gzip -t` passing every time.
- **`Volume2-incremental-backups-volume2.sh`**: present, 2 successful rsync snapshot runs logged
  (2026-07-08 21:06, 2026-07-09 02:00), hardlink-incremental via `--link-dest`, `latest` symlink
  maintained, lock-file guarded.
- **Original migration snapshot** (`/volume1/docker-migration-backup/20260708-203436`) already
  contains a full pre-migration inventory: `docker-{containers,images,info,networks,volumes}.txt`
  and path-tree dumps of both volumes — good due diligence already done before anything changed.
- **`cloudflared`** is running as a standalone container — not defined in any compose file
  anywhere (only found in unused `config.yml.example` reference files inside the two
  `resilinked-*` repo clones).
- **`newsite-example`** has a second, separate legacy backup mechanism (`backup.sh` +
  `backup.env`, S3-based) alongside the new centralized `backup-databases.sh`.

### Secrets inventory (paths and variable names only — no values read or printed)

| File | Variable names (sample) | Back up? | Protect? | Include in CM export planning? |
|---|---|---|---|---|
| `/volume1/docker/supabase/.env` | `POSTGRES_PASSWORD`, `JWT_SECRET`, `ANON_KEY`, `SERVICE_ROLE_KEY`, `DASHBOARD_PASSWORD`, `SMTP_PASS`, `OPENAI_API_KEY`, +~65 more | Yes | Yes (currently `600`-equivalent, fine) | Yes — must travel with the project |
| `/volume1/docker/resilinked-api-example-com/.env` | `DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, `RESEND_API_KEY`, `SENTRY_DSN` | Yes | Yes | Yes |
| `/volume1/docker/resilinked-app-example-com/.env` | `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SENTRY_DSN` | Yes | Lower sensitivity (client-exposed anyway) | Yes |
| `/volume1/docker/newsite-example/.env` | `MARIADB_ROOT_PASSWORD`, `WORDPRESS_DB_PASSWORD`, `GITHUB_SYNC_TOKEN`, `GITHUB_SYNC_WEBHOOK_SECRET` | Yes | Yes (currently `600`) | Yes |
| `/volume1/docker/newsite-example/backup.env` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `DB_PASSWORD`, `S3_BUCKET` | Yes | **Flagged — see D8** | Only if legacy script stays in use |

The archive copy at `/volume2/DockerSSD/archive/copied-from-docker-ssd/apps/*` has the same
`.env`/`backup.env` files mirrored — same handling applies.

## C. Things That Look Correct

- Dumps run via `docker exec` against the **live** container, not raw file copies — correctly
  avoids inconsistent-file-backup risk.
- `mariadb-dump --single-transaction --routines --events --triggers --all-databases` — correct
  flags for a consistent, complete logical backup.
- `pg_dumpall --clean --if-exists` — correct for a full-instance dump including roles, appropriate
  for Supabase's multi-role setup.
- Both dumps read DB credentials from the **container's own environment**, not duplicated on the
  host — minimizes secret sprawl.
- `gzip -t` integrity check built into the script right after each dump.
- 30-day retention pruning on both backup scripts.
- `rsync -aHAX --numeric-ids --delete --link-dest` — correct, efficient hardlink-incremental
  snapshot pattern.
- Lock-file + `trap cleanup` on the incremental script prevents concurrent self-overlap.
- Backup scripts are root-owned, `700`-equivalent — sensible hardening.
- All live containers remain cleanly on `/volume1/docker` — no premature live migration has
  occurred.
- Restart policies (`unless-stopped`) are consistent across every compose file inspected.
- Traefik + Watchtower + Cloudflare Tunnel architecture is coherent: Watchtower scoped only to
  labeled containers, Traefik on host port 8080 (correctly avoiding the port-80 conflict with DSM
  Web Station).

## D. Issues or Risks Found

1. **Path mismatch (highest priority).** The stated target `/volume2/DockerSSD/apps` doesn't
   exist. The real copy sits at `/volume2/DockerSSD/archive/copied-from-docker-ssd/apps`, with a
   sibling `compose/` folder containing overlapping compose files, plus an empty `ssd-deploy/`.
   Three candidate layouts exist with no canonical one chosen.
2. **`cloudflared` has no compose definition.** It won't be captured by any Container Manager
   *project* export/import — it'll need to be recreated manually or wrapped in its own compose
   file first.
3. **`realtime-dev.supabase-realtime` is currently `Exited (0)`**, not part of the "healthy"
   baseline that would be migrated from.
4. **Silent-failure gap in `backup-databases.sh`**: `set -eu` is present but not
   `set -o pipefail`. In `docker exec ... | gzip > file.gz`, if the dump command fails, the
   pipeline's exit status is `gzip`'s (likely 0), so the script won't stop or flag it — `gzip -t`
   afterward only proves the `.gz` container is well-formed, not that it holds a real dump.
5. **No minimum dump-size check** — nothing catches a near-empty/truncated `.sql.gz` from a silent
   failure like #4.
6. **No interlock between the two nightly jobs.** The 1:45 AM dump and 2:00 AM `/volume2` rsync
   rely on a fixed 15-minute gap with no dependency check — a slow dump run could get captured
   mid-write by the rsync snapshot.
7. **Two parallel backup mechanisms for `newsite-example`**: legacy `backup.sh`/`backup.env`
   (S3) alongside the new centralized script — unclear which is authoritative.
8. **`backup.env` (AWS keys + DB password) shows POSIX bits `-rwxrwxrwx+`** (world read/write),
   versus `.env` in the same folder correctly showing `-rw-------`. The trailing `+` means a
   Synology ACL may be enforcing tighter real access than the POSIX bits show, but `getfacl`
   isn't available on this NAS's shell to confirm — needs a DSM File Station check.
9. **This repo's own deploy tool still targets `/volume1/docker`** (`NAS_DOCKER_ROOT` in `.env`)
   — expected for now, but will need updating once containers actually cut over, or future
   `deploy`/`update` runs will keep hitting the old path.
10. **`resilinked-api-example-com`/`resilinked-app-example-com`'s running compose files use
    `build.context: ../..`**, a path pattern that only resolves correctly two directories inside
    a repo checkout (matching the *unused* nested `repo/infra/*` files, not the actual top-level
    file's location). Harmless today since normal deploys pull prebuilt GHCR images (`build:` is
    just the `--build` fallback), but worth a sanity check if `--build` is ever run post-migration
    from a remapped path.

## E. Recommended Fixes Before Migration

- Pick one canonical SSD app-folder path and reconcile the three current candidates (D1) — don't
  proceed with remapping until this is settled.
- Add `set -o pipefail` to `backup-databases.sh`.
- Add a minimum-size assertion on each `.sql.gz` before the script declares success.
- Add an explicit dependency/wait between the two Task Scheduler jobs rather than a fixed time
  offset.
- Decide which `newsite-example` backup path is authoritative; retire or clearly separate the
  other.
- Verify `backup.env`'s real effective permissions via DSM File Station → Properties →
  Permission; tighten if the ACL isn't already restrictive.
- Author a compose file for `cloudflared` before relying on project-based export/import.
- Investigate the `realtime-dev.supabase-realtime` exit before treating current state as the
  known-good baseline.
- Plan the `NAS_DOCKER_ROOT` update in this repo for *after* cutover, not before.

## F. Container Manager Export/Import Checklist

- [ ] Settle the canonical `/volume2/DockerSSD/apps` path (D1/E1) before anything else.
- [ ] Export each compose project via Container Manager's **Project** export (captures compose
      file + bind-mounted folder): `newsite-example`, `supabase`, `resilinked-api-example-com`,
      `resilinked-app-example-com`, `proxy-resilinked-example-com`,
      `resilinked-watchtower-example-com`, `health-example-com`, `test-example-com`.
- [ ] Handle `cloudflared` separately — it's not a compose project; give it one before or during
      migration.
- [ ] Remap bind mounts: `/volume1/docker/<project>` → final canonical
      `/volume2/DockerSSD/apps/<project>` path. No compose file has a hardcoded absolute
      `/volume1` path (the only literal hit, `RESILINKED_BACKUP_DIR:-/volume1/resilinked-backups`
      in `backup-postgres.sh`, points at a directory that doesn't currently exist anyway).
- [ ] Remap `/volume1/web` → `/volume2/DockerSSD/web` — nothing found actually bind-mounts
      `/volume1/web` into a container today (WordPress uses a named volume), but re-confirm DSM
      Web Station / Cloudflare Tunnel service URLs before decommissioning it.
- [ ] Confirm named Docker volumes (`newsite-example-wp-content`, `newsite-example-db-data`,
      `db-config`, `deno-cache`) survive the project import intact.
- [ ] `supabase_default` is `external: true` and depended on by `newsite-example`,
      `resilinked-api-example-com`, `resilinked-app-example-com`, `proxy-resilinked-example-com` —
      `supabase` must be imported/started first.
- [ ] Start order: **1)** `supabase` → **2)** `newsite-example`, `resilinked-api-example-com`,
      `resilinked-app-example-com` → **3)** `proxy-resilinked-example-com` → **4)**
      `resilinked-watchtower-example-com`, `health-example-com`, `test-example-com` (no dependencies)
      → **5)** `cloudflared` last, once backends are reachable.
- [ ] `resilinked-api-example-com`/`resilinked-app-example-com`/`proxy-resilinked-example-com` are
      simple enough to just redeploy as fresh compose projects from their moved directories rather
      than reconstructing via per-container import. `supabase`'s 12-file compose set is more
      complex — prefer Container Manager's native project import there.

## G. Post-Migration Verification Checklist

```
docker inspect <container> --format '{{json .Mounts}}'      # confirm Source paths now read /volume2/DockerSSD/...
docker compose -f /volume2/DockerSSD/apps/<project>/docker-compose.yml config   # validates paths resolve from new location
docker ps --format '{{.Names}}\t{{.Status}}'                # confirm all 20 are Up/healthy, incl. realtime this time
docker network inspect supabase_default                     # confirm all dependent containers attached
docker volume inspect <name>                                # confirm each named volume's mountpoint is now under /volume2
```

Plus: re-run `backup-databases.sh` once manually and confirm it still finds both DB containers and
produces non-trivial dump sizes; confirm the two Task Scheduler jobs' script paths
(`/volume2/DockerSSD/backups/database-dumps/backup-databases.sh`,
`/volume1/Volume2-incremental-backups-volume2.sh`) are unaffected by the app-folder move (they
live outside any per-project path).

## H. Do Not Touch Yet

- The live containers currently running from `/volume1/docker/*`.
- `/volume1/web` — still the actual served content, until Web Station/Tunnel config is ready to
  repoint.
- The two Task Scheduler jobs — leave as-is against current `/volume1` containers + `/volume2`
  backup destinations.
- `/volume1/docker-migration-backup/20260708-203436` — the pre-migration safety snapshot; keep
  immutable until migration is fully verified.
- Container Manager itself — not yet uninstalled/moved per stated status; don't touch until every
  project above is re-validated post-import.

## I. Questions Requiring Human Confirmation

1. What's the intended final canonical SSD app-folder path — the originally-stated
   `/volume2/DockerSSD/apps`, the current `archive/copied-from-docker-ssd/apps`, or the empty
   `ssd-deploy/`?
2. Why do both `apps/` and `compose/` exist under `archive/copied-from-docker-ssd/` with
   overlapping compose files — two different snapshots, or intentional duplication?
3. Is `realtime-dev.supabase-realtime` expected to be exited right now, or is that an active,
   unrelated problem?
4. Is the legacy `newsite-example/backup.sh` + `backup.env` (S3) still in active use, or fully
   superseded?
5. Was `cloudflared` deliberately deployed outside compose, or should it be wrapped in a compose
   file before migration?
6. What's stored in the root-owned, inaccessible `/volume2/docker-ssd` — obsolete intermediate
   copy, or still needed?
7. Can `backup.env`'s real effective ACL be confirmed via DSM File Station, since `getfacl` isn't
   installed on this NAS and guessing at Synology's ACL tooling on a live system was avoided?
