# synology-site-deployer

## Agent working context

Fetch or pull first, then read before starting work:

- `agent-context/COORDINATION.md`: notes between the Claude on Pedro's
  computer ("local") and Claude sessions working from GitHub ("remote").
- `agent-context/JOURNAL.md`: curated, newest-first journal of what each session or
  notable commit did and why. After a commit that is a real decision,
  milestone or finding, add an entry (what changed, why, gotchas for the
  next session). Skip purely mechanical commits.

The verbatim half of the journal,
`agent-context/journal-verbatim/VERBATIM_INDEX.md`, is gitignored and
machine-local: `.githooks/post-commit` appends a row per commit pointing at
the local transcript. Hooks are not carried by a clone, so run
`git config core.hooksPath .githooks` once per checkout.

## Commit identity (all sessions, local and remote)

Every session commits as Pedro's own git identity,
`Pedro Veloso <pedro@veloso.dev>`, never as an AI author (for example
`Claude <noreply@anthropic.com>`). This applies to every commit, including
merges, and overrides any tool or environment default. If the configured
identity is anything else, set it before committing:

    git config user.name "Pedro Veloso"
    git config user.email "pedro@veloso.dev"

Commit messages carry no AI attribution either: no `Co-Authored-By: Claude`
(or any other AI assistant) trailer, no `Claude-Session:` link, and no
"Generated with" footer. This also overrides any tool or environment
default.

## UI conventions (owner's rule, 2026-10-28, all of Pedro's projects)

These apply to every user interface in every project in Pedro's ecosystem (web apps,
admin pages, dashboards, plugins and extensions) unless the platform forbids it:

- **Lists are standard table views.** Use one shared table style per project: a header row,
  one record per row and an **Actions** column last. Don't use cards, tiles or stacked
  lines for lists of records.
- **Actions are small icon buttons**, never full-width or large text buttons. Each one:
  - shows a meaningful icon, for example an eye for view, a pencil for edit, a bin for
    delete, a key for an API key, a link for connect, a power symbol for on/off;
  - names its action in a tooltip on hover and on keyboard focus, and in an `aria-label`;
  - uses a danger style for destructive actions.
- **Add, edit, view and delete open in pop-up dialogs.** Every delete or other destructive
  action asks for confirmation in the dialog first.
- **Dialogs stand out from the page:** a subtle gradient background, an accent edge and a
  dimmed, blurred backdrop, so they never merge with the page underneath. This applies in
  both light and dark modes.
- **Form elements are styled and responsive.** Use themed inputs, selects and textareas
  with clear focus rings. Short fields go in two columns on wide screens and in one
  column on phones.
- **Checkboxes are pill toggle switches** everywhere.
- **Radio buttons are pill choices** (the whole option is a rounded, selectable pill)
  wherever possible.
- **Check every UI change** with screenshots in light mode, dark mode and at phone width
  before merging.

Reference implementation: s2925534/velosolabs (`app/templates/_icons.html`, `app/static/tooltips.js`,
the dialog, form and table styles in `app/static/hub.css`; VLABS-212).

## Login standard (owner's rule, 2026-11-07, all of Pedro's web apps)

Every web app in Pedro's ecosystem, current or new, has its **own** sign-in. It never depends on someone
having an account with a third party (for example Cloudflare Access or a Google login). At minimum it offers:

- **email (or username) and password**: a slow, salted hash (PBKDF2, scrypt or Argon2), rate limits, and a
  lockout after repeated failures;
- **passkeys** (WebAuthn): added from the account page, and usable without typing an email (discoverable
  credentials);
- **a one-time code sent by email**: short-lived, single use, with a limited number of tries.

Also: forgot password (a single-use reset link), invites where an app has more than one user, change password,
and sign out everywhere. Give the same answer whether or not an account exists. Build emailed links from a
configured site address, never the request's Host header. Store only hashes of passwords, codes, links and
session tokens. Use HttpOnly, SameSite session cookies and refuse cross-site form posts.

Reference implementation: `Appuiaus/sprigboard` (`src/auth.ts`, `src/passkeys.ts` with
@simplewebauthn/server, `src/mail.ts`; VLABS-277). An existing app that lacks any of the three methods gets a
Jira ticket to add them, and new apps ship with all three from the first release.

## SOC 2 by design (owner's rule, 2026-11-10, everything we build)

Everything we build, in every project, is designed to pass a SOC 2 Type II audit against the Trust Services
Criteria (security, availability, confidentiality, processing integrity and privacy). Build these in from the
first release, not as a later retrofit:

- **Access control:** the app's own sign-in (see the login standard), least-privilege roles, passkeys or a second
  factor for admins, sessions that expire, and sign out everywhere. No shared logins or static admin tokens.
- **Audit trail:** an append-only log of sign-ins, admin actions, permission changes and changes to important
  data (who, what, when, from where), kept for at least a year, and not editable by app users.
- **Data protection:** TLS everywhere; secrets in a secret store or environment, never in git, chat, tickets or
  journals; sensitive data encrypted at rest; collect only the personal data needed; a retention period and
  deletion on request.
- **Change management:** every change goes through a pull request with CI (tests, secret scan, dependency scan),
  `main` is protected, deploys run from CI, and each change has a Jira ticket.
- **Availability:** automated backups with a tested restore, health checks, and monitoring with alerts.
- **Vendors:** record every third-party service that receives data (subprocessor) and what it receives.
- **Incident response:** a short runbook per product covering key and secret rotation, revoking access and
  telling affected users.
- **Evidence:** each product keeps a living `docs/soc2-report.md` (template: s2925534/velosolabs
  `docs/soc2-report.md`) listing controls in place, findings and fixes. Update it whenever a change touches any
  of the points above, and give every gap a Jira ticket.
