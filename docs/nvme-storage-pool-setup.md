# NVMe Storage Pool Setup & Third-Party Drive Compatibility

A step-by-step manual for taking non-Synology-certified NVMe (or SATA) drives from "just
installed" to "a working DSM volume, surviving reboots and DSM updates" using this project's
CLI. Validated end-to-end on a real Synology DS1525+ (a 2025-series Plus model) with two
Samsung SSD 9100 PRO 2TB NVMe drives.

Every command below is the exact one that worked. Anything that can trip you up if you skip a
step or run something out of order is called out as a footnote[^order] rather than folded into
the main flow, so the steps below are a clean, repeatable path.

## Prerequisites

- This project's `.env` configured with working NAS SSH access (`NAS_HOST`/`NAS_SSH_PASSWORD` or
  key, and `TAILSCALE_ENABLED`/`TAILSCALE_NAS_HOST` if you're off the NAS's LAN).
- The drives physically installed in the NAS already.
- `synology-site check-nas` (or `check-nas --remote` if off-LAN) returns all green before you
  start.[^checknas]

---

## Part 1 — Create the Storage Pool (RAID 1, RAID 0, or a Single Drive)

### Step 1.1 — Allow third-party drives

```bash
synology-site allow-third-party-drives
```

Disables DSM's `support_disk_compatibility` flag and restarts the storage daemon so Storage
Manager stops hard-filtering non-certified drives out of "available drives." Confirm with `y`
when prompted, or pass `--yes` to skip the prompt.[^flagalone]

Check the current state any time with:

```bash
synology-site allow-third-party-drives --status
```

### Step 1.2 — Create the pool

Pick **one** of `--nvme` or `--hdd` (never both, never neither — the command requires exactly
one, precisely so there's no ambiguity about which physical bays get touched), and a
`--raid-level`:

```bash
# RAID 1 (mirror) across two NVMe drives -- the common case
synology-site create-storage-pool --nvme --raid-level raid1

# RAID 0 (stripe) across two or more NVMe drives
synology-site create-storage-pool --nvme --raid-level raid0

# A single drive, no RAID at all
synology-site create-storage-pool --nvme --raid-level basic --device /dev/nvme0n1
```

- `--nvme` supports `basic`, `raid0`, `raid1`. `--hdd` (regular SATA bays) additionally supports
  `raid5`, `raid6`, `raid10`, `raid_f1`, `linear`, `shr1`, `shr2`.
- `--device <path>` (repeatable) picks specific drives instead of auto-detecting every bay of the
  chosen type — required for `basic` if more than one candidate drive is found, since picking one
  automatically would be a guess.
- The command shows you the exact resolved device list and asks for confirmation before touching
  anything; add `--yes` to skip that for scripting.
- `--description "My pool"` sets the pool's DSM description.

This creates the actual RAID array and DSM storage pool directly via `synostgpool`, bypassing
Storage Manager's own pool-creation wizard.[^wizard] It also refuses to touch any device that
already shows a filesystem signature or RAID membership, and refuses `--hdd` outright on models
listed in `PROTECTED_HDD_MODELS` in `create_storage_pool.py` — remove a model from that set only
if you specifically intend to run `--hdd` against that exact NAS.[^partition]

### Step 1.3 — Make DSM recognize the drives for volume creation

```bash
synology-site run-hdd-db-fix
```

On 2025-series-or-later Plus models, this step is **required**, not optional — Step 1.1 alone is
enough to *create* the pool, but Storage Manager will still refuse to create a *volume* on it,
reporting the drives "Unrecognized"/Critical.[^volumeblock] This command uploads a pinned copy of
[`007revad/Synology_HDD_db`](https://github.com/007revad/Synology_HDD_db) to the NAS and runs it
with `-s -n`, adding your drives' exact model+firmware as explicit "supported" entries in DSM's
per-model compatibility database. Confirm the prompt (or pass `--yes`).

### Step 1.4 — Create the volume in DSM

This last step is manual, in the DSM web UI:

**Storage Manager → Storage Pool → (select the new pool) → Create Volume.**

Use the defaults (Btrfs recommended) and finish the wizard. No reboot needed if Steps 1.1–1.3
were all run first.[^reboot]

---

## Part 2 — Deploying the Fix So It Survives Reboots and DSM Updates

Steps 1.1 and 1.3 fix DSM's state *right now*, over SSH. A future DSM **version update** (not a
routine reboot) can silently reset both — re-enabling `support_disk_compatibility` and/or
refreshing the certified-drive database — which can make an already-working pool/volume show as
"missing" until the fix is reapplied. This part makes that automatic.

### Step 2.1 — Generate the boot-time scripts

```bash
synology-site drive-compat-fix-plan --include-hdd-db --output-dir drive-compat-fix-plan
```

This writes, into `drive-compat-fix-plan/`:

- `run-hdd-db-fix.sh` — re-runs the Step 1.3 fix (idempotent, no-op if nothing changed).
- `syno_hdd_db.sh` / `syno_hdd_vendor_ids.txt` — the pinned third-party script itself, bundled
  locally (also cached under `vendor/synology_hdd_db/<version>/` so later runs, and this whole
  workflow, don't depend on the upstream repo still existing).
- `drive-compat-fix.sh` — the lighter, Step-1.1-only fallback (not needed if you're using
  `run-hdd-db-fix.sh`; don't schedule both, they'd fight over the same flag).[^bothscripts]
- `README.md`, `crontab.example`, `synology-task-commands.txt` — setup instructions.

Add `--hdd-db-version vX.Y.Z` to pin a specific release; defaults to the version validated for
this manual.

### Step 2.2 — Copy the scripts to the NAS

```bash
scp -P "$NAS_PORT" drive-compat-fix-plan/run-hdd-db-fix.sh \
  drive-compat-fix-plan/syno_hdd_db.sh \
  drive-compat-fix-plan/syno_hdd_vendor_ids.txt \
  "$NAS_USER@$NAS_HOST:/volume1/docker/hdd-db-fix/"
```

(Create `/volume1/docker/hdd-db-fix/` on the NAS first if it doesn't exist. Any writable path
works — this is just the one already used elsewhere in this project.)

### Step 2.3 — Schedule it in DSM Task Scheduler

1. **DSM → Control Panel → Task Scheduler → Create → Triggered Task → Boot-up.**
2. User: **root**.
3. Run command: `bash /volume1/docker/hdd-db-fix/run-hdd-db-fix.sh` (see the generated
   `synology-task-commands.txt` for the exact line).
4. Save, then right-click the task → **Run** once manually to confirm it exits cleanly before
   relying on it at the next real reboot/update.[^cronalt]

From here on, every boot (routine or post-update) reapplies the fix automatically, before Storage
Manager gets a chance to act on stale state.

---

## Optional — Migrating Existing Container Data to the New Pool

Not required for the storage pool itself, but if the goal was faster storage for an existing
app's data:

1. Stop the container: `docker compose down` in its project directory.
2. Create the destination as a **proper DSM Shared Folder** first — Control Panel → Shared
   Folder → Create — on the new volume, *before* copying anything there.[^sharedfolder]
3. Copy the data preserving attributes: `cp -a /volume1/docker/<project>/data/. /volumeN/<shared-folder>/<project>/data/`.
4. Update the project's `docker-compose.yml` bind mount (and any `HOST_DATA_PATH`-style env var)
   to the new absolute path.
5. Restart: `docker compose up -d`.
6. Verify the app and its data are intact before deleting the old copy.

---

## Footnotes

[^order]: These are things that went wrong in testing when a step was skipped, run out of
    order, or done a different way than described above — included so you can recognize and fix
    them quickly if you hit one, not because they're expected.

[^checknas]: If `check-nas` can't reach the NAS at all, nothing below will work — fix
    connectivity first (see `docs/remote-nas-access.md`) rather than debugging storage pool
    commands against a NAS you can't actually SSH into.

[^flagalone]: Disabling `support_disk_compatibility` alone is *not* sufficient on
    2025-series-or-later Plus models — it gets you a created pool, but Storage Manager will still
    block volume creation until Step 1.3 runs too. Don't stop after this step expecting the
    volume wizard to work.

[^wizard]: Even with the flag disabled, Storage Manager's own pool-creation *wizard* can still
    refuse to list the drives as "available" — a separate, wizard-specific restriction, not the
    same check the flag controls. If you try the GUI wizard directly and see "No drives are
    available or meet the requirements," that's why — use `create-storage-pool` instead of the
    wizard, don't spend time trying to make the wizard itself accept the drives.

[^partition]: Don't manually partition the drives first (e.g. `synodisk --partition` or
    `synopartition`) before running `create-storage-pool` — `synostgpool` partitions the raw
    device internally as part of pool creation. Passing an already-partitioned path, or trying to
    partition ahead of time, doesn't match what the tool expects and isn't necessary.

[^volumeblock]: If you see "No available storage pool for creating a new volume," or the pool's
    drives show **Drive Status: Unrecognized** with a Critical health warning, this is what's
    happening — go back and run Step 1.3, don't reboot as a first response (a reboot alone does
    not fix this).

[^reboot]: If Storage Manager still shows the pool/drives as unrecognized immediately after Step
    1.3, try logging out of DSM and back in (or a private browser window) before concluding
    anything is actually broken — the DSM web session can hold stale state briefly.

[^bothscripts]: `drive-compat-fix.sh` (Step-1.1-only) and `run-hdd-db-fix.sh` (Step-1.3, which
    also manages the same flag) manage `support_disk_compatibility` differently — one forces it
    off, the other re-enables it correctly alongside real per-drive entries. Scheduling both on
    the same boot means whichever runs last wins, which is not a state you want to depend on.
    Schedule only one — `run-hdd-db-fix.sh` if you completed Step 1.3.

[^cronalt]: A crontab `@reboot` entry (see the generated `crontab.example`) works as an
    alternative to DSM Task Scheduler, but if you use it, remember it survives independently of
    DSM's own task list — don't set up both for the same script.

[^sharedfolder]: Creating the destination directory on the new volume with a plain `mkdir` over
    SSH instead of DSM's Shared Folder UI is unsafe: on a later reboot, Container Manager's
    startup process can silently rename it (e.g. `docker` → `docker_1`) if it tries to claim that
    same name for its own managed shared folder, breaking every compose file's bind mount
    pointing at the old path. No data is lost (it's a rename, not a delete), but every container
    relying on that path will fail to start until the compose files are repointed. Always create
    the destination as a registered Shared Folder first.
