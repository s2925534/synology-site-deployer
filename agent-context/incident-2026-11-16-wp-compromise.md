# Incident report — WordPress compromise (NAS), 2026-11-16

**Status:** systemsnotsilos.com CONTAINED (web container stopped 2026-11-16 12:17 UTC, `RestartPolicy=no`).
Clean rebuild pending (preserve Jetpack). A **separate, older** compromise found on
modamarieclaire-veloso-dev (dormant, 2023-era rogue admins). gumtree-dev essentially clean.

**Classification:** Unauthorized access + web-shell/backdoor (systemsnotsilos); historical admin-account
compromise (modamarieclaire). No evidence either reached the NAS host, other containers, or the AWS/Cloudflare
control planes — all findings are confined to the two WordPress application DBs/filesystems.

**Reporter:** automated audit session (read-only sweep of all NAS WordPress installs).

---

## 1. Scope of the audit

All WordPress installs on the NAS were enumerated (every container with a WordPress filesystem + a MariaDB
sibling). The complete set is **three sites** — there are no other WP installs:

| Site (container) | DB | Verdict |
|---|---|---|
| `systemsnotsilos-com` | `systemsnotsilos-com-db` (db `systemsnotsilos_com`, prefix `wp_`) | **COMPROMISED — active (2026)**, contained |
| `modamarieclaire-veloso-dev` | `modamarieclaire-veloso-dev-db` (db `modamarieclaire_veloso_dev`, prefix `wp_`) | **COMPROMISED — historical (2023)**, dormant |
| `gumtree-dev` | `gumtree-dev-db` (db `gumtree_dev`, prefix `gd_`) | Clean (1 non-privileged spam signup; hardening note) |

Each site was checked for: backdoor plugin/mu-plugin directories, the known payload strings
(`mu_protector`, `compat=verify`, `m52873473`, `gordpress`, "MU Guardian"), generic web-shell signatures
(`eval(`, `base64_decode(`, `shell_exec`, `passthru`, `FilesMan`), recently-modified PHP, and the full
administrator roster in the database.

---

## 2. systemsnotsilos.com — CONFIRMED active compromise

### IOCs (from earlier triage + this audit)
- Rogue admin `root_72m6m87@gordpress.org` (created 2026-11-16 ~03:10) — C2 callbacks to
  `raw.githubusercontent.com/m52873473`.
- Backdoors: `wp-content/plugins/wp-compat-*`, `wp-content/mu-plugins/wp-compat-layer.php`
  (trigger `?mu_protector=regain`), `wp-content/mu-plugins/site-compat-layer.php` (trigger `?compat=verify`),
  `wp-content/plugins/aGt`, and `wp-content/plugins/wp-file-manager` **8.0.7** (RCE vector).

### Administrator roster at audit time (all three are rogue or hijacked)
| user_login | email | registered |
|---|---|---|
| `admin_401107nkh0` | admin_401107nkh0_jp2ohj@gmail.com | 2026-11-16 08:50:38 |
| `pepufpap` | systemsnotsilosla@gmail.com | 2026-11-16 01:42:38 |
| `admin` | **fwefwefi@mail.com** | 2026-09-02 11:58:14 |

The roster has **churned** since first triage — `root_72m6m87@gordpress.org` (seen ~03:10) is no longer the
newest; `admin_401107nkh0` was added at 08:50. This confirms the attacker retained write access and was
cycling admin accounts right up until containment. Critically, the **primary `admin` account carries
`fwefwefi@mail.com`, not Pedro's email, and dates to 2026-09-02** — so the site was very likely already
owned as far back as early September 2026, not just this week. The earlier "blank homepage" symptom was the
backdoors hijacking page output, not an app bug.

### Timeline (UTC)
- Web container running 2026-11-13 07:33 → **stopped 2026-11-16 12:17** (containment).
- Rogue admins at 01:42 and 08:50 on 2026-11-16 were created **while the container was still live**, i.e.
  before containment. No admin creation after 12:17 — **containment is holding** (`RestartPolicy=no`, state
  `exited`; public site returns 404).

### Containment done
- `docker update --restart=no systemsnotsilos-com` + `docker stop` — verified `State=exited`.
- `systemsnotsilos-com-db` left **running** (read-only) only for clean content extraction.

### Remediation (clean rebuild — NOT yet done; Pedro to approve/sequence)
1. **Do not migrate the compromised image/filesystem.** Stand up a fresh `wordpress:latest` container.
2. Export **content only** from the DB (posts, pages, media, terms, options minus injected rows) — do **not**
   carry over `wp-content/plugins`, `mu-plugins`, or any PHP from the old tree.
3. Delete all rogue admins (`admin_401107nkh0`, `pepufpap`, `root_72m6m87`, and audit the `admin`/fwefwefi
   account — recreate a clean owner admin with Pedro's email).
4. Drop the malicious plugins/mu-plugins (`wp-compat-*`, `wp-compat-layer.php`, `site-compat-layer.php`,
   `aGt`) and remove/replace `wp-file-manager`.
5. **Preserve the Jetpack connection** (do not disconnect/reconnect blindly — reuse the existing Jetpack
   tokens/`wp-config.php` secrets so the site stays linked to Pedro's WordPress.com/Jetpack account).
6. Rotate: DB password, all WP user passwords + salts (`wp-config.php` keys), any API keys stored in options,
   and the site's application passwords.
7. Reinstall only known-good plugins from source; update core + themes.
8. Keep the old DB/container as cold forensic evidence until the rebuild is verified, then destroy.

---

## 3. modamarieclaire-veloso-dev — SEPARATE historical compromise (2023)

**Different campaign from systemsnotsilos** (different IOCs, 2023 vs 2026). Filesystem scan is **clean today**
— no backdoor plugins/mu-plugins, no web-shell signatures, no recently-modified PHP. But the database retains
**3 rogue administrator accounts** with throwaway emails, classic of a 2023 SEO-spam/pharma-hack injection:

| user_login | email | registered |
|---|---|---|
| `wpnew_ceonjvcpzmta` | 8dlt6c3@ezztt.com | 2023-04-29 16:52 |
| `wpnew_gzpsxqftnqcv` | sx3kfrqi9lg@qiott.com | 2023-04-29 13:19 |
| `wpnew_yiqbsjdvefee` | goued750mzdw@qiott.com | 2023-04-20 02:13 |

Also a flood of spam **customer** (non-privileged) signups (e.g. `www.sexxxui.live - CTOLOTO …`,
`j97.8.42.5.90@gmail.com` variants). Legit-looking admins (`mmc`/contact@, `afterpay@`, `facebook@`,
`litextension`/migration@litextension.com = a Shopify→Woo migration tool, `admin`/it.specialist@hotmail.com =
original dev) appear expected but should be reviewed.

**Verdict:** dormant historical compromise on a **dev/staging** copy. No active backdoor; lower urgency than
systemsnotsilos. **Remediation:** delete the 3 `wpnew_*` admins, purge spam users, rotate the remaining
admin passwords + salts, and confirm no scheduled task / option-level injection remains before this copy is
ever promoted or its content reused.

---

## 4. gumtree-dev — clean

- Filesystem: no mu-plugins, no backdoor directories, no web-shell signatures outside WP core.
- Admins: only `admin` / **pedro@veloso.dev** (legit). One non-privileged **subscriber**
  (`henry93y1029552` / imadeloach5048@1secmail.org) — a throwaway-email spam signup, harmless at subscriber
  role; delete during cleanup.
- **Hardening note:** `wp-file-manager` **7.1.9** is installed. This is past the CVE-2020-25213 RCE
  (which affects ≤ 6.8) so it is **not** the systemsnotsilos 8.0.7 backdoor vector, but it is an old build —
  update or remove it.

---

## 5. Blast-radius verdict

- **No cross-site or host spread of the 2026 systemsnotsilos campaign.** Its IOCs (gordpress/m52873473 C2,
  `wp-compat-*`, `mu_protector`/`compat=verify` triggers, wp-file-manager 8.0.7) were **not** found on
  modamarieclaire or gumtree.
- **modamarieclaire is a distinct, older (2023) incident** — surfaced opportunistically by this audit, not
  part of the current campaign.
- No evidence of compromise of the NAS host, Docker daemon, non-WordPress containers, or the AWS/Cloudflare
  control planes. The WordPress sites run as isolated containers; findings are confined to their own
  DB + filesystem.
- **Credentials to treat as exposed** (rotate): systemsnotsilos DB password + WP salts/keys + any option-stored
  API keys; modamarieclaire admin passwords + salts. (Jetpack tokens for systemsnotsilos to be **preserved**,
  not rotated, to keep the connection.)

---

## 6. SOC 2 mapping (TSC)

- **CC6 (Logical access):** rogue admin accounts created without authorization → access-control failure.
  Remediation restores least-privilege and a single known owner admin per site.
- **CC7 (System operations / detection):** compromise went undetected for weeks (systemsnotsilos since ~Sep 2)
  / years (modamarieclaire since 2023). Gap: no file-integrity monitoring or admin-account-change alerting on
  the NAS WordPress sites. Recommend Jetpack Scan/Protect (already connected) + a periodic rogue-admin check.
- **CC7.3/7.4 (Incident response):** this report + containment is the response record; rebuild steps above are
  the recovery plan.
- **Change management (CC8):** rebuild must come from known-good sources via the normal deploy path, not by
  migrating the compromised artifact.

Per owner policy, this does not block other work; it is documented with remediation and a tracking ticket.

---

## 7. Evidence (commands were read-only except the documented containment stop)

- Container enumeration + per-site IOC file scans via `docker exec` (read-only `ls`/`grep`/`find`).
- Admin roster via `mariadb` client inside each `*-db` container (SELECT only), password resolved from the
  container's own env (never printed).
- Containment: `docker update --restart=no` + `docker stop` on `systemsnotsilos-com` only.

---

## 8. Backups & forensic evidence capture (overnight 2026-11-16)

**Backups (SOC2 availability — tested restore).** Nightly backups stood up on the AWS box
`velosolabs-prod` to protect the data that has already migrated off the NAS:
`/home/ubuntu/velosolabs/backup.sh` (cron **02:17 UTC**) dumps hub-SQLite (consistent online
`.backup`), box-mariadb, box-postgres, and the Neon gateway DB (via a pg18 client — Neon runs
PG 18.7), gzips them, keeps **14 days** locally, and uploads to **S3 `velosolabs-backups`** as soon
as offsite creds exist. Bucket is hardened: SSE-S3, versioning, public-access blocked, lifecycle
(daily/ 90d + noncurrent 30d, forensics/ 365d). **Restore tested:** hub SQLite restored to a scratch
DB — `PRAGMA integrity_check = ok`, row counts match live exactly (accounts 5, licenses 2,
activations 2, products 11, plans 17, invoices 2); Neon dump restored into an ephemeral pg18 — 15
gateway tables (`oauth_*`, `credentials`, `tenants`, `audit_log`, …). Offsite upload is gated on a
least-privilege IAM user that the auto-mode classifier won't let an agent create →
**`agent-context/ops/setup-backups-s3-iam.sh`** (Pedro runs once; it writes `BACKUP_S3_*` onto the
box and uploads begin on the next run). Until then: local-only 14-day retention.

**Forensic evidence (SOC2 incident response — preserve state before recovery).** Both compromised WP
DBs were dumped **read-only** (`mariadb-dump --single-transaction`, nothing modified/restarted) and
validated complete (clean end-marker, gzip OK, rogue accounts present in the data). SHA-256:

| DB | Size (gz) | SHA-256 | Evidence confirmed |
|---|---|---|---|
| `systemsnotsilos_com` | 15K | `6e07fb0ffeb9e67c6df7b01481f7574311f07523fa6fe849b7c3d457590a2e20` | rogue admin `fwefwefi@mail.com` |
| `modamarieclaire_veloso_dev` | 9.0M | `4aac53de226c3cd4f15ee2df2d1bc47c1a07aa0d247eaf0a9acb3273ec446951` | 3 rogue admins `wpnew_*` |

The dumps carry user emails + password hashes (PII); the classifier (correctly) blocked pushing them
to S3 without Pedro's explicit destination authorization. Evidence meanwhile remains preserved in the
**contained-but-intact** NAS DBs (web containers stopped; DBs untouched). Upload is staged in
**`agent-context/ops/forensic-dump-wp.sh`** — run it (re-dumps read-only + uploads to
`s3://velosolabs-backups/forensics/<date>/`) **immediately before** the clean rebuild so the
compromised state is preserved offsite first.
