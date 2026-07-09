# Lightsail → NAS Site Migration — MVP Plan (example.com)

Goal: pull a live site off an AWS Lightsail instance (WordPress is the assumed MVP case, since
that's what example.com runs) and stand it back up on this NAS, using the Docker
Compose + Cloudflare Tunnel pattern this repo already deploys with. The long-term goal is a
generic "migrate any Lightsail-hosted site to a given NAS" command; example.com is the first real
target used to find every actual hurdle before generalizing.

Explicitly out of scope for the MVP, called out here so scope doesn't creep during
implementation: EC2 as a source, web servers other than what example.com actually runs, databases
other than MySQL/MariaDB, CMSs other than WordPress. Each becomes its own future flag once the
WordPress/Lightsail path is proven (see Roadmap below).

## Two real targets, one source

There are two concrete things this MVP needs to produce, both pulling from the same example.com
Lightsail instance but landing very differently:

1. **example.com → its own NAS deployment.** example.com keeps being hosted, just moved off
   Lightsail — a brand-new WordPress + MariaDB Compose stack on the NAS, same domain, same
   content. This is a **new-site** target: nothing exists there yet to preserve.
2. **example.com → `newsite.example` (already running on the NAS, currently a fresh install
   with no content).** The user wants that site fully seeded with a clone of example.com's DB,
   `wp-content` (files, plugins, themes), as a starting point — which they'll then manually diverge
   into a distinct tech-focused site (stripping the personal/CV content example.com has, which is
   entirely a manual follow-up step, not something this tool needs to automate). This is an
   **existing-site-replace** target: a WordPress + MariaDB stack is already deployed and running;
   this operation overwrites its DB content and `wp-content` in place, without touching that
   target's own `wp-config.php` DB connection settings or reprovisioning its containers.

Both share the same **extraction** half (dump DB, copy `wp-content`, capture plugin/theme
inventory) — only the **landing** half differs. Parametrized as source/target domain plus a target
mode from the start, rather than hardcoding example.com twice:

```
synology-site migrate-from-lightsail --source-domain example.com --target-domain example.com --target-mode new-site --dry-run
synology-site migrate-from-lightsail --source-domain example.com --target-domain example.com --target-mode new-site --execute

synology-site migrate-from-lightsail --source-domain example.com --target-domain newsite.example --target-mode existing-site-replace --dry-run
synology-site migrate-from-lightsail --source-domain example.com --target-domain newsite.example --target-mode existing-site-replace --execute
```

- **`--dry-run`** — read-only discovery over SSH (Lightsail instance) + the AWS API + the
  Cloudflare API. No file is written, no DB is touched, no DNS record changes, nothing is
  downloaded from S3 beyond metadata/listing. Produces a migration-readiness report in the same
  style as the two `migration-validation-report*.md` files already in this repo (from the
  Volume1→Volume2 NAS migration) — current state, hurdles found, what's safe, what needs a human
  decision.
- **`--execute`** — actually moves things: DB dump + restore, `wp-content` sync (local files via
  `rsync`, S3-offloaded media via `aws s3 sync` directly from the bucket rather than re-downloading
  through the web server), a WordPress + MariaDB Compose project scaffolded on the NAS (same
  pattern already proven on this NAS for `newsite-example`), Cloudflare cutover, verification.

## Confirmed so far

- example.com's top-level domain runs **Nginx + WordPress + a SQL database (MySQL/MariaDB)** on
  the Lightsail instance. Still to confirm during discovery: exact package layout (Bitnami's Nginx
  stack vs. a hand-installed Ubuntu/Amazon Linux + Nginx setup — these differ in file paths and
  matter for the sync/restore step), PHP version, and whether the DB is colocated on the instance
  or a separate Lightsail "managed database".

## What the dry run needs to determine

- Whether this is a Bitnami-packaged Nginx/WordPress image (Lightsail's blueprints include an
  Nginx variant, not just the more common Apache one) vs. a stock Ubuntu/Amazon Linux install with
  Nginx + WordPress installed by hand — the file layout differs between the two.
- Nginx vhost/server-block config, and how TLS is currently terminated.
- PHP version, WordPress version, whether WP-CLI is installed on the instance.
- DB engine/version, whether it's colocated on the instance or a separate Lightsail "managed
  database", and its size.
- Full plugin + theme inventory with versions (`wp plugin list`/`wp theme list` if WP-CLI is
  present; otherwise parsed from `wp-content/plugins`, `wp-content/themes`).
- Whether an S3 offload plugin is active (e.g. WP Offload Media) and, if so, its bucket name,
  region, key prefix, and whether it's configured to delete local copies after upload — this
  determines whether media comes from the instance's disk or has to come from S3 directly.
- `wp-content/uploads` size if any media still lives on-instance.
- Cron: real crontab entries vs. WordPress's own pseudo-cron.
- Anything hardcoded that would break on a new host: absolute URLs in post content, SMTP/mail
  relay config, other third-party API keys defined as constants in `wp-config.php`.
- Current Cloudflare DNS record(s) for example.com, proxy (orange-cloud) status, and any existing
  Page Rules/Redirects/WAF rules that reference the Lightsail IP directly.

## Access needed for the dry run

Four things, all read-only for this phase:

### 1. SSH to the Lightsail instance

Generate a disposable, single-purpose key rather than reusing a personal one — it's trivially
revocable when the migration is done:

```
ssh-keygen -t ed25519 -f example-com-migration -C "example-com-migration-readonly"
```

Add only the **public** key to the instance's `~/.ssh/authorized_keys` (via Lightsail's
browser-based SSH, or whatever key currently has access) for the blueprint's default user
(`bitnami` for the Bitnami WordPress blueprint, `ubuntu`/`ec2-user` otherwise). Then share, through
your normal secret-handling channel (not pasted into chat, not committed):

- Host/IP and SSH port
- Username
- The private key file
- Whether sudo is needed to read `wp-config.php`/DB files, and whether it's passwordless (Bitnami
  images typically preconfigure this for the default user) or needs a password

### 2. AWS programmatic access (read-only)

Create a dedicated IAM user (programmatic access only, no console password), e.g.
`example-com-migration-readonly`, with this inline policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "LightsailReadOnly",
      "Effect": "Allow",
      "Action": [
        "lightsail:GetInstance",
        "lightsail:GetInstances",
        "lightsail:GetInstanceState",
        "lightsail:GetInstanceSnapshots",
        "lightsail:GetStaticIps",
        "lightsail:GetDomains",
        "lightsail:GetDistributions"
      ],
      "Resource": "*"
    },
    {
      "Sid": "S3MediaReadOnly",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::REPLACE_BUCKET_NAME"
    },
    {
      "Sid": "S3MediaObjectReadOnly",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::REPLACE_BUCKET_NAME/*"
    }
  ]
}
```

Fill in the real bucket name once the dry run's discovery finds it (or in advance, if already
known). This same policy covers the later `--execute` phase too — every AWS-side interaction in
this design is a read, never a write; the NAS is the only write target. Share the resulting Access
Key ID + Secret Access Key, and the AWS region. This maps to a new
`secrets/example-com/aws.env` in this repo, following the same per-workspace pattern already used
for `secrets/<workspace>/cloudflare.env` and `secrets/<workspace>/nas.env` — gitignored like the
rest of `secrets/`.

Rotate/delete this IAM user's access key once the migration is verified, same principle as the
disposable SSH key.

## Current credential status (example.com)

Tracking what's actually in `secrets/example-com/` vs. still outstanding, updated as access is
provided:

| Item | Status |
|---|---|
| Cloudflare (example.com zone) | **Already covered, confirmed twice** — the repo's default workspace (`.env`, `CF_ZONE_DOMAIN=example.com`) already holds this. Also confirmed `CF_API_TOKEN`/`CF_ACCOUNT_ID` are byte-identical to `secrets/newsite/cloudflare.env` (only `CF_ZONE_ID` differs, as expected per-zone) — same account/token already covers both domains. No separate `secrets/example-com/cloudflare.env` needed. |
| SSH to the Lightsail instance | **Working.** The original address in `~/.ssh/config` turned out to be **stale** — a different, live instance entirely. The real instance was found by asking it directly (`curl` to the AWS metadata service from a browser SSH session) and cross-checked against its own nginx vhost for example.com, now recorded in `secrets/example-com/lightsail.env`. |
| S3 usage for example.com media | **Confirmed not used**, directly (not just inferred from public HTML): `wp-content/plugins/` on the instance has no S3/offload plugin, and `wp-content/uploads/` is a plain local directory, 159M. Media migration is a plain `rsync`, no `aws s3 sync` needed. |
| AWS access | **Not needed for the MVP**, per the finding above. `secrets/example-com/aws.env` still has the `sourcesite` IAM user's Access Key ID on file in case a later phase wants Lightsail instance metadata, but there's no live blocker on it — no need to chase down its Secret Access Key right now. |
| NAS target workspace | Not yet decided — default workspace vs. a dedicated `secrets/example-com/nas.env`. |

### What SSH discovery found on the instance (read-only)

- **Shared instance.** `/etc/nginx/sites-enabled` also serves a handful of other live third-party sites, plus disabled (`sites-available` only) configs for `newsite.example` and a `example.com.bkp`. This instance cannot be decommissioned once example.com moves — every later step (file copy, DB dump, eventual cleanup) must stay scoped to example.com's own paths only.
- **Document root:** `/var/www/html/example.com/public/` — hand-rolled Nginx layout (not Bitnami), confirming the earlier guess. PHP 8.3 via `php8.3-fpm.sock`, TLS via Certbot/Let's Encrypt (`/etc/letsencrypt/live/example.com/`) — this component is retired once Cloudflare Tunnel fronts the NAS, not migrated.
- **`blog.example.com` resolved:** nginx has a *commented-out*, inactive server block that used to redirect `blog.example.com`/`example.com` → `https://www.blog.example.com`. It's legacy/dead config, not a second live install — old post content just still references that hostname in stored image URLs (explains the earlier public-HTML finding). One current WordPress install, serving under `www.example.com`.
- **The `/staging` location block in nginx is dead** — it `try_files`-routes to `/staging/index.php`, but no `staging/` directory exists on disk. Not a second environment to worry about.
- **No WP-CLI installed.** DB export/import and any URL search-replace pass will need plain `mysqldump`/`mariadb-dump` (or a temporary WP-CLI install on the NAS side after import), not `wp db export`.
- **Plugin inventory** (`wp-content/plugins`): `akismet`, `contact-form-7`, `elementor`, `flamingo`, `google-site-kit`, `gtranslate`, `jetpack`, `jetpack-boost`, `loginpress`, `nextend-facebook-connect`, `one-click-demo-import`, `pojo-accessibility`, `post-smtp`, `slim-seo`, `wp-file-manager`, plus a couple of custom-named ones (`ai`, `ai-engine`, `hashtagger`, `publisher-plugin`, `codestar-framework`, `insert-headers-and-footers`). Notable for migration:
  - `elementor` — page builder; still worth the absolute-URL `search-replace` check from the hurdles list below.
  - `post-smtp` — confirms outbound mail already goes through a dedicated SMTP relay, not Lightsail's own IP reputation; its config lives in the DB and travels with the dump.
  - `jetpack`/`jetpack-boost` — the image CDN found earlier; tied to a WordPress.com connection that may need re-verifying post-move (same domain, so should be low-risk).
  - `wp-file-manager` — has a history of serious CVEs in older versions; not a migration blocker, but worth a version check before/after the move.

### Extra hurdles specific to the `existing-site-replace` target (newsite.example)

These don't apply to the example.com `new-site` target (same domain, nothing to rewrite) but are
required for cloning onto a different domain:

- **Serialized-data-safe search-replace is mandatory, not optional.** example.com's DB dump will
  have `example.com` baked into `wp_options` (`siteurl`/`home`), post content, menus, widget
  settings, and — since Elementor is in use — into `_elementor_data` postmeta, which stores its
  page-builder layout as **serialized PHP with byte-length prefixes**. A naive text
  find-and-replace corrupts any serialized value where the replacement string is a different
  length than `example.com` (`newsite.example` is longer, so this will always trigger). Needs a
  serialization-aware tool — `wp search-replace` (temporarily installed on the NAS side, since the
  source has no WP-CLI) or an equivalent script — run against the *imported* DB on the NAS, never
  a plain SQL `REPLACE()`.
- **Don't touch the target's own `wp-config.php` DB credentials.** newsite.example's containers
  already point at their own database name/user/host; the DB dump should be imported into that
  existing schema (drop-and-reimport its tables), not used to swap in example.com's own DB
  connection details.
- **Jetpack and Google Site Kit need reconnecting after the clone.** Both tie their connection to a
  specific site identity (WordPress.com site ID / Google Search Console property), which won't
  carry over cleanly to `newsite.example`'s different domain — expect to reauthorize both
  through wp-admin once the clone lands, rather than assuming the cloned DB rows are usable as-is.
- **The "strip personal content" step is entirely manual and out of scope for this tool.** The plan
  here is just to land a faithful, working clone of example.com on `newsite.example` — removing
  the CV/personal-About content to diverge it into a tech site is something the user does
  afterward in wp-admin, not something to automate.
- **Back up newsite.example's current (empty) install before overwriting it**, even though
  it has no real content — cheap insurance, same "snapshot before touching anything live" principle
  already used for the earlier Volume1→Volume2 NAS migration in this repo.

### 3. Cloudflare

Same pattern already used for other workspaces in this repo (e.g. `secrets/newsite/`):

```
secrets/example-com/cloudflare.env
  CF_API_TOKEN=       # Zone:Read is enough for --dry-run; add Zone:DNS:Edit only for --execute
  CF_ACCOUNT_ID=
  CF_ZONE_ID=
  CF_ZONE_DOMAIN=example.com
  CF_TUNNEL_ID=        # only if reusing the tunnel already fronting this NAS
  CF_TUNNEL_NAME=
```

Scope the token to the example.com zone only (Cloudflare API tokens support per-zone scoping —
avoid the old-style global API key).

### 4. NAS target

Confirm whether example.com deploys to the NAS's existing default workspace or gets its own
`secrets/example-com/nas.env`, and confirm available disk headroom for the WordPress DB + uploads
(checkable over SSH once NAS access is available, which the default workspace already provides).

### What I do not need

- Your AWS root/console password.
- Your Lightsail account email or 2FA codes.
- Any WordPress admin password — SSH + WP-CLI covers every discovery/migration step without ever
  needing `/wp-admin`, which also sidesteps any security plugin (Wordfence, etc.) that might block
  an unfamiliar IP from logging in.

## Known hurdles to expect

- **Bitnami file layout, if applicable.** Bitnami's images put WordPress at
  `/opt/bitnami/wordpress` with its own Nginx config layout under `/opt/bitnami/nginx`, not the
  more common `/var/www/html` + `/etc/nginx/sites-enabled` — discovery needs to check for Bitnami
  first before assuming stock paths.
- **TLS termination changes hands.** Bitnami's default TLS is a self-managed `bncert-tool`
  (Let's Encrypt wrapper) tied to serving the domain directly from the instance; a hand-rolled
  Nginx setup more likely uses Certbot directly. Either way, once Cloudflare Tunnel fronts the NAS,
  TLS terminates at Cloudflare — this component is retired, not migrated.
- **Nginx → Traefik rewrite rules.** The target stack on this NAS fronts containers with Traefik,
  not Nginx directly. Any WordPress-specific Nginx rules beyond the standard `try_files`
  permalink block (redirects, security headers, caching rules) need to be identified during
  discovery and ported to Traefik labels/middlewares, not assumed to carry over automatically.
- **S3-offloaded media.** If the offload plugin deletes local copies after upload,
  `wp-content/uploads` may already be mostly empty on the instance; media must be pulled from the
  bucket via `aws s3 sync`, not assumed present on disk.
- **Hardcoded absolute URLs.** Page builders in particular sometimes bake absolute URLs into post
  content. Domain stays the same here, so this should be a no-op, but worth a
  `wp search-replace --dry-run` check for any `http://` (non-proxied) URLs given Cloudflare's proxy
  changes the effective front door.
- **Outbound mail.** `wp_mail` may rely on Lightsail's IP reputation or an SMTP plugin — confirm
  which, since NAS-originated mail can be treated differently by receiving providers.
- **DNS cutover window.** Lower the existing DNS record's TTL ahead of cutover, and keep the
  Lightsail instance stopped (not deleted) for a rollback window after cutover.

## Roadmap (mirrors this repo's phase-based TODO structure)

- **MVP (this doc):** `migrate-from-lightsail`, WordPress + MySQL/MariaDB only, `--dry-run` +
  `--execute`, source = Lightsail instance, target = this NAS.
- **Future flag:** `--source-type ec2` — plain EC2 instance, no Lightsail-specific API calls, same
  SSH+package-manager discovery approach generalized.
- **Future flag:** additional web servers (Apache/Nginx/Caddy vhost parsing) and CMSs/frameworks
  beyond WordPress.
- **Future flag:** additional source databases (Postgres, or MySQL not colocated on the source
  host).

---

Once SSH access, the AWS IAM access key, a Cloudflare Zone-Read token for example.com, and the NAS
target are ready, the dry run can run and produce a report in the same format as this repo's
existing `migration-validation-report.md`/`migration-validation-report-followup.md`.
