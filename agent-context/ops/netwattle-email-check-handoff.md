# NetWattle / LDR routine — "netwattle" email check + email-dependency fix — handoff

Prepared 2026-11-19. Pedro asked: "check my emails for emails with title containing **netwattle**
(those related to routines we created) and find what's not working / failing due to misconfiguration,
missing configuration, missing actions from my side, missing setups." He is continuing from his phone,
so this is the durable, no-assumptions handoff.

## ⚠️ Rule from Pedro: LEARN THE ROUTINE IN FULL BEFORE ANY ASSUMPTION
Do NOT reason from the old prototype config. The **live** routine **directly downloads** the Leader feed —
it does **not** read Pedro's email to get the feed. (An earlier draft of this doc wrongly assumed an IMAP
"mail-harvest" of the feed; that was a stale `shopify-python-prototype` variant, not the live routine.)

**Step 0 (mandatory first action): read the actual code.** Clone/read the live repo
`s2925534/shopify-supplier-sync-platform` (private) and understand, from the code + README + config, exactly:
- how it **downloads** the Leader "stock data feed" (URL/SFTP/portal + what credential),
- what it does with the CSV (Shopify Admin API sync; OpenAI "NetWattle" enrichment),
- **whether and how it SENDS email** (the "netwattle"-titled emails in Pedro's inbox are almost certainly this
  routine's own **run-report / alert** emails) — find the mailer code + current transport,
- where it runs (NAS `/volume3` root crontab 2×/day per project memory; source was "MOVED TO WINDOWS" — confirm
  the authoritative deployment) and where its **logs/output** land.
Only after that, diagnose. Report findings against the actual code, not this doc's guesses.

## What "check my netwattle emails" really means (given the correction)
The feed is downloaded directly, so the netwattle-titled emails are the routine's **outbound run reports**.
Two ways to answer Pedro's question WITHOUT depending on reading his Google inbox (his stated preference):
1. Read the routine's **own logs/output** (on the NAS/Windows box where it runs) for the last runs — that is
   the authoritative record of success/failure, no inbox needed.
2. If the report emails themselves must be read, do it against a **dedicated** inbox, never pedro@veloso.dev.

## THE FIX (Pedro's rule: Mailjet where it fits; don't depend on reading my Google inbox)
- **Outbound reports/alerts (SEND only) → Mailjet SMTP.** Switch the routine's mailer to Mailjet
  (`in-v3.mailjet.com:587`, STARTTLS; user = Mailjet API key, pass = secret key; senders
  `no-reply@zqx.io` / `admin@zqx.io`). No Google password, no inbox dependency. This is the main fix.
- **Reading the feed:** nothing to do — it's a direct download, not email. (If the code turns out to still
  harvest *anything* from email, replace that with **Cloudflare Email Routing + an Email Worker** on a
  dedicated address, free — never Pedro's personal inbox. Confirm from the code before building this.)
- **Diagnosis source = logs, not inbox.** Pull the last-run logs/output and report every failure
  (download auth, Shopify API, OpenAI key, cron not firing, host down).

## Known broken signal (prototype only — verify relevance against live code)
The OLD prototype's Gmail IMAP app passwords (pedro@veloso.dev and contact@ldrelectronics.com) now fail
`[AUTHENTICATIONFAILED]`. If the LIVE routine does not use IMAP, this is irrelevant to the feed and only
matters if we still want to read the report emails from an inbox (we're moving away from that).

## Creds (live source of truth — DO NOT commit to git; pass to the online session file-to-file)
- `~/.config/veloso/extras.env` → PROJECT "Shopify supplier-sync / mail-harvest prototype" (Shopify shop/
  client id+secret, OpenAI "NetWattle" key, site URLs) — **may be stale**; the live `.env` wins.
- Live routine `.env`: NAS `/volume3/dockernvme/shopify-sync/.env` (OpenAI key updated here 2026-11-18).
- Mailjet: `~/.config/veloso/mailjet.env` (global).
- NAS reach: LAN `ssh -i ~/.ssh/id_ed25519_zqx_nas -o IdentitiesOnly=yes pedro@192.168.1.109`
  (fallback Tailscale pedro@100.107.233.45); docker at `/var/packages/ContainerManager/target/usr/bin/docker`.
- A remote cloud session CANNOT reach the NAS or Pedro's local files — it CAN clone the GitHub repo (needs a
  token) and reach Shopify/OpenAI/Mailjet/Cloudflare over the internet. State clearly what it cannot reach.

## Minimal ask of Pedro (from phone)
1. Confirm the authoritative deployment (NAS `/volume3` vs Windows) of `shopify-supplier-sync-platform`.
2. After the session has LEARNED the routine from the code, it will report the real failures + the exact
   secrets/actions still needed. Provide those file-to-file.

## Status
- ✅ pushed. ⚠️ No assumptions: the online session must read `s2925534/shopify-supplier-sync-platform` first.
