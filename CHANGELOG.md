# Changelog

Notable changes to this project, most recent first. Each entry says what changed and, for new
functionality, where to find usage in the README.

## 2026-08-05
- Added `run-hdd-db-fix` command: uploads and runs a pinned `007revad/Synology_HDD_db` release on
  the NAS on demand (the live-execution counterpart to `drive-compat-fix-plan --include-hdd-db`'s
  boot-time script). Added `synology_site/hdd_db.py`, a shared fetch-with-local-cache helper
  (`vendor/synology_hdd_db/<version>/`, gitignored) used by both this command and
  `drive-compat-fix-plan`, so a pinned release only needs to be downloaded once and survives the
  upstream repo disappearing. See
  [Running the HDD DB Fix Right Now](README.md#running-the-hdd-db-fix-right-now-run-hdd-db-fix).
- Corrected the record on the third-party-drive fix after a real end-to-end run: disabling
  `support_disk_compatibility` (`allow-third-party-drives`) plus `create-storage-pool` gets a pool
  *created* on 2025-series-or-later Plus models (confirmed on a real DS1525+), but Storage Manager
  still refused "Create Volume" on it, reporting the drives "Unrecognized"/Critical -- a separate
  per-drive compatibility-database check, not the global flag. Running a pinned copy of
  [`007revad/Synology_HDD_db`](https://github.com/007revad/Synology_HDD_db) (`v3.6.137`) resolved
  it: it added the drives' exact model+firmware as explicit "supported" database entries (and, in
  doing so, re-enabled `support_disk_compatibility` -- the correct end state once real per-drive
  entries exist, not a global bypass). Volume creation then worked immediately, no reboot needed.
  `drive-compat-fix-plan --include-hdd-db` now bundles this fix for the boot-time safety net too.
  README updated in the [Third-Party Drives](README.md#third-party-drives-storage-manager),
  [Creating the Pool Directly](README.md#creating-the-pool-directly-create-storage-pool), and
  [Surviving DSM Updates](README.md#surviving-dsm-updates-drive-compat-fix-plan) sections.
- Added `create-storage-pool` command: creates a DSM storage pool directly via `synostgpool`,
  bypassing a separate wizard-specific restriction in Storage Manager that
  `allow-third-party-drives` alone doesn't clear. Requires an explicit `--nvme`/`--hdd` target and
  `--raid-level`; refuses to touch any device that already has a filesystem signature or RAID
  membership; `--hdd` additionally refuses outright on any model listed in
  `PROTECTED_HDD_MODELS` (ships with `DS1525+`, a real NAS whose regular bays already hold live
  pools). See
  [Creating the Pool Directly](README.md#creating-the-pool-directly-create-storage-pool).
- Added `drive-compat-fix-plan` command: generates a boot-time script (DSM Task Scheduler
  Boot-up trigger or crontab `@reboot`) that re-applies the `allow-third-party-drives` fix on
  every boot, so a future DSM version update can't silently re-block third-party drives and
  strand a pool built from them. See
  [Surviving DSM Updates](README.md#surviving-dsm-updates-drive-compat-fix-plan).
- Added `allow-third-party-drives` command: toggles DSM's `support_disk_compatibility` flag and
  restarts the storage daemon so Storage Manager stops hard-filtering non-Synology-certified
  drives (e.g. third-party NVMe SSDs) out of "available drives" for pool creation. Supports
  `--status`, `--revert`, `--yes`, `--workspace`. See
  [Third-Party Drives (Storage Manager)](README.md#third-party-drives-storage-manager).
- Started this changelog.

## 2026-07-31
- Added `redirect-ruleset` command for Cloudflare Redirect Rules.

## 2026-07-27
- Redesigned blog-redirect rules to avoid the Cloudflare `matches` (regex) operator.

## 2026-07-22
- Added GoDaddy registrar support and `migrate-from-lightsail --execute` for real Lightsail-to-NAS
  cutovers, plus reliability fixes found during a real migration.
- Added `swap-fix-plan` command: generates NAS swap-file setup/release scripts and DSM Task
  Scheduler/crontab instructions.

## 2026-07-21
- Fixed `health` using the LAN IP instead of the configured Tailscale host when Tailscale is
  enabled.

## 2026-07-20
- Added `--remove-orphans` to `remove`/`stop`.
- Fixed `restart-policy` detection (was matching a literal `\t` instead of a real tab).
- Fixed port reuse validation to reject a port still registered to a stopped site.

## 2026-07-19
- Added `start-resilinked-api` command (handles its `supabase-db` dependency and name-conflict
  recovery).
- Fixed `docker ps`/`inspect` format strings; added a memory gate to `restart-all`.

## 2026-07-18
- Added `doctor` and `restart-all` commands for safe fleet health checks and recovery.
- Added `--compose-file` to `update` for applying a compose-only change in place.
- Added scheduled tunnel recovery safety net (`tunnel-fix-plan`) and Uptime Kuma monitor
  instructions.
- Fixed `list`/`create`/`deploy` always using the remote transport instead of trying LAN first.

## 2026-07-15
- Added read-only NAS diagnostics (`check-nas`, `ps`, `logs`); fixed silent deploy failures.

## 2026-07-14
- Added `registry-login` command for one-time NAS Docker registry auth; token piped via SSH
  stdin rather than a temp file.

## 2026-07-10
- Implemented `migrate-from-lightsail --dry-run` for Lightsail-to-NAS migration planning.

## 2026-07-07
- Added `check-nas --remote` (LAN vs. remote auto-detection) and `configure-tailscale` (automates
  writing `TAILSCALE_ENABLED`/`TAILSCALE_NAS_HOST` from the Tailscale API).
