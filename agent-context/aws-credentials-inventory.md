# AWS credentials inventory (2026-11-13)

All AWS access keys found across the projects. **Identifiers only — secret keys never read/printed, no
creds used, no AWS calls made.** Account IDs for most are not yet resolved (would need an STS call —
deferred per "do nothing for now").

| # | Access key ID (masked) | Found in | Var | Account / purpose (from annotations) | Status |
|---|---|---|---|---|---|
| 1 | `AKIAWQKZ…4ZP3` | deployer `.env` | `AWS_DECOM_ACCESS_KEY_ID` | **447401840262** (user FullUser) — domains/DNS/static account, **DECOMMISSIONING** | read-only |
| 2 | `AKIAWQKZ…KT2S` | `extras.env:4634` | `AWS_ACCESS_KEY_ID` | same `AKIAWQKZ` prefix → likely also **447401840262** (2nd key, to confirm) | unknown |
| 3 | `AKIAZI2L…DFHW` | `interport-backend_old/.env:8` + extras.env | `AWS_ACCESS_KEY_ID` | **Interport** backend (region ap-southeast-2) | active? |
| 4 | `AKIAZI2L…UHE3` | `~/.aws/credentials [default]` | `aws_access_key_id` | **Interport** — default CLI profile, "lambda-programmatic" | active (default CLI) |
| 5 | `AKIA237R…WYEP` | `extras.env:204` | `AWS_ACCESS_KEY` | account TBD — "AWS credential / resource config" | unknown |
| 6 | `AKIA237R…GTUC` | `extras.env:594` | `AWS_ACCESS_KEY` | account TBD | unknown |
| 7 | `AKIA237R…QAX7` | `extras.env:810` | `AWS_LAMBDA_ACCESS_KEY` | account TBD — a **Lambda** key | unknown |
| 8 | `AKIA237R…XOMM` | `extras.env:1224` | `AWS_ACCESS_KEY` | account TBD | unknown |

## Apparent groupings (by key-ID prefix — needs STS to confirm accounts)
- **`AKIAWQKZ…`** (#1, #2) → the **decommission account 447401840262**.
- **`AKIAZI2L…`** (#3, #4) → **Interport** (the `~/.aws` default + the interport-backend `.env`, ap-southeast-2).
- **`AKIA237R…`** (#5–#8, incl. a Lambda key) → a **separate account/set** — purpose not captured in the sweep
  annotations beyond "resource config"; likely an older/another project. Several keys here may be rotations.

## Notes
- The **new MySQL/MariaDB AWS account** (for the WordPress DBs) is **not in here yet** — you were mid-creating
  its `FullUser` CLI key; paste it when ready and it gets added.
- To resolve the exact account IDs + current status of #2 and #5–#8, I'd run `aws sts get-caller-identity`
  per key (read-only) — **not done** per your instruction. Say the word and I'll resolve + tidy this table.
- Secrets live only in their source files (`.env` / `extras.env` / `~/.aws`), gitignored where applicable.
  Stale/unused keys here are good **rotation/cleanup** candidates once we map them.
