# AWS account 447401840262 — decommission discovery (2026-11-13)

Read-only discovery of the AWS account Pedro is **decommissioning**. Purpose: inventory + transfer the
domains/DNS out to a **new** AWS account (and/or Cloudflare), then close this account. **Nothing was
changed — all `list`/`describe`/`get` only.**

- **Account:** `447401840262`  **IAM user:** `FullUser` (the only user)
- **Creds:** stored in the deployer `.env` as `AWS_DECOM_ACCESS_KEY_ID` / `AWS_DECOM_SECRET_ACCESS_KEY`
  (+ `AWS_DECOM_USERNAME`, `AWS_DECOM_CONSOLE_PASSWORD`). Treat **read-only**; rotate/revoke after decommission.
- CLI: `/opt/homebrew/bin/aws` v2.19.4 (the `~/.local/bin/aws` shim is broken — use the homebrew one).

## Inventory
| Resource | Count | Details |
|---|---|---|
| Registered domains | 9 | see table below (all AutoRenew=ON) |
| Route53 hosted zones | 18 | veloso.dev(13 recs), modamarieclaire.com(21), ldrelectronics.com(11), systemsnotsilos.com, veloso.au, veloso.com.au, modamarieclaire.com.au, modamarieclaire.au, modestclassy.com.au, modestclassy.au, digitalnotions.com.au, digitalnotions.biz, quanpulse.com, quanxpert.com, theturningwave.com, risebeyondlies.com, risefortruth.com, veloso.click |
| S3 buckets | 4 | `veloso.click`, `veloso.dev`, `www.veloso.click`, `www.veloso.dev` (static-site hosting) |
| CloudFront | 1 | `EJ6UKS50DRX8H` → www.veloso.dev (Deployed) |
| ACM cert | 1 | veloso.dev (us-east-1) |
| EC2 / Lightsail / RDS / SES | 0 | none in any region checked (us-east-1, us-west-2, ap-southeast-1/2, ap-south-1, eu-west-1) |

### Registered domains (AutoRenew / Expiry)
| Domain | AutoRenew | Expiry |
|---|---|---|
| modamarieclaire.com | ON | 2026-12-31 (soonest) |
| freightracker.com | ON | 2027-02-17 |
| their.show | ON | 2027-02-17 |
| two.show | ON | 2027-02-17 |
| yard.show | ON | 2027-02-17 |
| systemsnotsilos.com | ON | 2027-04-27 |
| veloso.au | ON | 2027-05-23 |
| veloso.com.au | ON | 2027-05-23 |
| digitalnotions.biz | ON | 2027-11-03 |

## Decommission plan (all WRITES — not yet executed; need the NEW account's creds + per-step go-ahead)
1. **Transfer the 9 domains → the new AWS account** via `route53domains transfer-domain-to-another-aws-account`
   (account-to-account; near-instant, no 60-day ICANN lock). The **receiving account must accept** the
   transfer (`accept-domain-transfer-from-another-aws-account`). Do `modamarieclaire.com` first (expires Dec 2026).
2. **Move the 18 DNS zones** — recreate in the new account, OR point the domains' nameservers at **Cloudflare**
   (consistent with the live stack). Export each zone first.
3. **veloso.dev static site** (S3 `veloso.dev`/`www.veloso.dev` + CloudFront `EJ6UKS50DRX8H` + ACM veloso.dev):
   **CAUTION — veloso.dev also runs on the NAS (`p-veloso-dev`).** Confirm which is canonical before retiring this.
4. Empty/delete the 4 S3 buckets, then close the account.

Note: no servers/DBs here, so nothing to migrate compute-wise — this is purely domains + DNS + the veloso.dev
static site. The new MySQL/MariaDB AWS account (for the WordPress DBs) is a **separate** account from this one.
