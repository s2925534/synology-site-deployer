# NetWattle / LDR mail-harvest email check — handoff

Prepared 2026-11-19. Pedro asked: "check my emails for emails with title containing **netwattle**
(those related to routines we created) and find what's not working / failing due to misconfiguration,
missing configuration, missing actions from my side, missing setups." He then had to close the laptop,
so this is the durable handoff for an online session to continue.

## The routine in question
- **LeaderCSV / NetWattle Shopify importer** = repo `shopify-supplier-sync-platform`
  (local source was `shopify-python-prototype`, MOVED TO WINDOWS). Runs on the **NAS `/volume3` via root
  crontab 2×/day**; the OpenAI key is named **"NetWattle"** (that's why Pedro calls it the netwattle routine).
- **What it does:** harvests the supplier stock feed email, downloads the CSV attachment, and syncs stock into
  the `ldrelectronics.com` Shopify store (`digitalnotions.myshopify.com`, "Leader Electronics").
- **Feed email it looks for:** FROM `sales@leadersystems.com.au`, SUBJECT contains `Leader Stock Data Feed`,
  attachment `*.csv` with name containing `STOCK`, last 7 days, unread-only, marks read after.

## Two inboxes are configured (Gmail / Google Workspace — MX confirmed `aspmx.l.google.com` / `smtp.google.com`)
- `pedro@veloso.dev`  (mail-harvest "2" variant → TARGET_TO pedro@veloso.dev)
- `contact@ldrelectronics.com`  (primary variant → TARGET_TO contact@ldrelectronics.com)
- Creds live in `~/.config/veloso/extras.env` under PROJECT "Shopify supplier-sync / mail-harvest prototype"
  (EMAIL_USERNAME / EMAIL_PASSWORD app-passwords) and in the live routine `.env` on the NAS
  `/volume3/dockernvme/shopify-sync/.env`. **Do NOT paste the app passwords into git or chat.**

## FINDING (the actual failure)
Attempted IMAP login (imap.gmail.com:993) to **both** inboxes with the app passwords stored in `extras.env`:

```
pedro@veloso.dev            -> [AUTHENTICATIONFAILED] Invalid credentials (Failure)
contact@ldrelectronics.com  -> [AUTHENTICATIONFAILED] Invalid credentials (Failure)
```

Both Gmail app passwords are **dead**. Most likely cause: the credential sweep / Google account security
changes during the systemsnotsilos incident invalidated them (turning 2-Step Verification off, or regenerating,
revokes all app passwords). **Consequence:** the harvest step cannot log in, so the CSV is never downloaded and
the Shopify stock sync has been running against a stale/absent feed — i.e. the routine is silently broken.

## THE FIX (Pedro's rule: use Mailjet where it fits; don't depend on reading my Google inbox)
Split every email touchpoint into two categories and treat them differently:

### A) Routines that only SEND (reports, alerts, notifications) → **Mailjet SMTP, drop Google entirely**
- The importer's own run-report / failure-alert emails must go out via **Mailjet** (creds in
  `~/.config/veloso/mailjet.env`; senders `no-reply@zqx.io` / `admin@zqx.io`), not Gmail SMTP and not an
  app password. Point SMTP at `in-v3.mailjet.com:587` (STARTTLS), user = Mailjet API key, pass = secret key.
- Nothing here needs to read an inbox, so no Google password is involved at all. This is the preferred path
  for ANY ecosystem routine that merely notifies.

### B) Routines that genuinely must READ an incoming email (the supplier **feed harvest**) → remove the
### dependency on my personal Google inbox. Mailjet is send-only and can't receive, so instead:
- **Recommended (free, Cloudflare, no Google creds): Cloudflare Email Routing + an Email Worker.**
  Point a dedicated address — e.g. `feed@ldrelectronics.com` or `leaderfeed@<subdomain>.zqx.io` — at
  Cloudflare Email Routing (set the zone's MX to Cloudflare, free). An **Email Worker** receives each message,
  pulls the `*STOCK*.csv` attachment, and either writes it to **R2** or POSTs it to the sync — no IMAP, no
  app password, no reading Pedro's mailbox. Then ask Leader Systems to send/CC the "Leader Stock Data Feed"
  to that dedicated address (or forward-rule it in). This matches the "free resources / Cloudflare only" rule.
- **Interim (works today, least change): one dedicated Gmail app password** scoped only to the harvest
  mailbox (`contact@ldrelectronics.com`, which is already a purpose-built inbox — keep it off `pedro@veloso.dev`
  so Pedro's personal inbox is never the dependency). Regenerate at https://myaccount.google.com/apppasswords
  (needs 2-Step Verification ON; confirm IMAP enabled), hand it over file-to-file, update `extras.env` + the
  live NAS `/volume3/dockernvme/shopify-sync/.env`. Use this only until (B-recommended) is in place.

### What Pedro must do (minimal)
1. Decide: Cloudflare Email Routing (preferred) **or** a dedicated `contact@ldrelectronics.com` app password
   for the interim. For the quick unblock, generate the one app password and hand it over file-to-file.
2. The online/phone session then: switches the importer's outbound mail to Mailjet (category A), applies the
   chosen read-side fix (category B), updates the live config, re-runs the IMAP search for
   `SUBJECT "netwattle"` and `SUBJECT "Leader Stock Data Feed"`, reads the matching run-report bodies, and
   reports any remaining failures (missing CSV, Shopify API errors, OpenAI errors) from those emails + the
   NAS `logs/` / `output/` dirs.

## For the online session — exact steps once new app passwords exist
- IMAP search both inboxes: `(SUBJECT "netwattle")` AND `(SUBJECT "Leader Stock Data Feed")`, last ~14 days.
- For each hit: dump Date/From/Subject + body; the routine emails a run report — look in it for
  "error/failed/0 rows/exception/quota/rate limit/invalid".
- Cross-check the live routine on the NAS (`/volume3/dockernvme/shopify-sync/`): `.env` correctness,
  `logs/` + `output/*.json` for the last run outcome, and whether the root crontab entry still fires.
  (NAS reachable via LAN `ssh -i ~/.ssh/id_ed25519_zqx_nas -o IdentitiesOnly=yes pedro@192.168.1.109`,
  docker at `/var/packages/ContainerManager/target/usr/bin/docker`.)
- Report: what the netwattle-titled emails say, what's broken, and any remaining Pedro actions.

## Status
- ⛔ BLOCKED on fresh Gmail app passwords (Pedro). Everything else (provider confirmed, inboxes identified,
  live config locations known) is ready.
