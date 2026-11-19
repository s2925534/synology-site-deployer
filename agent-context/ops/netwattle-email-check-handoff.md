# NetWattle / LDR routine — "netwattle" email check — FINDINGS + fix (code-grounded)

Prepared 2026-11-19. Pedro: "check my emails titled **netwattle** (our routines) for anything failing due to
misconfiguration / missing config / missing action / missing setup." Learned from the actual code of
`s2925534/shopify-supplier-sync-platform` (no assumptions).

## The routine (what it really is)
`shopify-supplier-sync-platform` (Python, `app.py`): syncs the **Leader Systems** supplier feed into the
**NetWattle / ldrelectronics.com Shopify store** (`digitalnotions.myshopify.com`), with OpenAI enrichment,
eBay two-way sync, and social posting (Instagram/Pinterest @netwattle). Runs scheduled via
`sync_latest_supplier.sh` (NAS `/volume3` root crontab 2×/day per memory).

## Feed acquisition = DIRECT DOWNLOAD (Pedro was right — NOT an email read)
- `app.py` `leader_feed_fetch()` + `--api=leader-feed-download` / `leader-feed-connect`: downloads Leader's
  **partner datafeed** from `https://partner.leadersystems.com.au/...` (customer-code URL). The URL is stored
  once in a **Shopify metafield** `namespace="leader" key="feed_url"` (set via `--api=leader-feed-connect
  --leader-feed-url "<link>"`; the link is never printed). No inbox, no Google involved.
- LEGACY only: `sync_latest_supplier.sh` still defaults `DOWNLOAD_EMAIL=true` → `python -m
  email_attachment_downloader` (Gmail harvest). **That module is NOT in the repo** → dead/unused path. The
  scheduled run should use the direct path (`--no-download-email`) with the `leader.feed_url` metafield set.

## The actual failure (answers "check my netwattle emails")
- The **only live email in the routine is OUTBOUND**: `scripts/notify.py` sends failure/anomaly alerts
  (subject passed by the caller — these are the "netwattle" emails). It logs in via **smtp.gmail.com:587 with
  EMAIL_USERNAME / EMAIL_PASSWORD** (the harvester Gmail **app password**).
- That Gmail app password is **DEAD** (confirmed `[AUTHENTICATIONFAILED]` for both pedro@veloso.dev and
  contact@ldrelectronics.com). notify.py catches the send error, prints it, and returns without raising →
  **alerts fail silently**. That is why the netwattle alert emails stopped. (Also: if `ALERT_TO` is empty,
  notify.py is a deliberate no-op, so no alerts at all — verify `ALERT_TO` in the live root `.env`.)
- The feed sync itself is unaffected **as long as** the scheduled run uses the direct download path and the
  `leader.feed_url` metafield is set. If cron still runs with `DOWNLOAD_EMAIL=true`, the dead harvest step
  trips on every run — flip it off.

## MISSING CONFIG / SETUP (diagnosis only — NO code changes; verify each in the live root `.env`)
1. **Dead Gmail app password** — `EMAIL_USERNAME` / `EMAIL_PASSWORD` (the Gmail account `notify.py` logs into
   to SEND alerts) no longer authenticate. FIX (no code): regenerate the Gmail app password and update those
   two values in the live `.env`. (Optional later, Pedro's Mailjet rule: pointing alerts at Mailjet would need
   a tiny code tweak in notify.py — it reuses one value for both the SMTP login user and the From header, and
   Mailjet needs the API key as login but a verified From like no-reply@zqx.io — so that one is NOT pure-config.
   Flagged as a recommendation only; not done.)
2. **`ALERT_TO` may be empty** → notify.py is a deliberate no-op, so you get NO alerts at all. Set it to your
   address in the live `.env`.
3. **`DOWNLOAD_EMAIL` default is `true`** in `sync_latest_supplier.sh` → the scheduled run tries the dead
   legacy mail-harvest unless the cron passes `--no-download-email`. Confirm the cron uses the DIRECT path.
4. **`leader.feed_url` Shopify metafield must be set** (via `--api=leader-feed-connect --leader-feed-url`) for
   the direct download to work. Verify it exists.
5. **`KUMA_PUSH_URL` optional** dead-man's-switch heartbeat — if empty, no uptime alerting on missed runs.
6. Verify live **Shopify** creds + **OpenAI "NetWattle"** key are current in the live `.env`.

## Where to read real run outcomes (no inbox needed)
`logs/sync_runs/<RUN_ID>/sync.log` + `metadata.json` and `output/*.json` on the box where cron runs
(NAS `/volume3/dockernvme/shopify-sync/`).

## Online session status (honest)
- Attempts to spin a **remote** online session FAILED in this env (internal error, then a git-worktree error)
  — no session name/link exists; none was fabricated. Continuation path = this pushed handoff: open Claude on
  the repo from your phone and say "continue the netwattle fix per
  agent-context/ops/netwattle-email-check-handoff.md". The `shopify-supplier-sync-platform` repo is private
  but readable by `s2925534`.
- Creds: Mailjet in `~/.config/veloso/mailjet.env`; Shopify/OpenAI(NetWattle) in `~/.config/veloso/extras.env`
  (project "Shopify supplier-sync") and the live NAS `.env`. Never commit secrets.
