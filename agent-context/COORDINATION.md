# Agent coordination — local ⇄ remote

How the Claude on Pedro's computer ("local") and the Claude in cloud
sessions ("remote", working from GitHub) talk to each other.

Rules for both:
- Read this file before starting work; pull/fetch first.
- Leave notes here (newest first: date, from → to, what changed, what you
  need). Delete a note once it's acted on and acknowledged.
- Never force-push or rewrite history others may have; fetch and check the
  remote before every push and merge.
- Remote has no access to Pedro's computer: anything that only exists
  locally must be pushed before remote can see it.
- Secrets never go in this file or in chat.

---

## 2026-10-04: local → next session — Windows machine (IPC-ADM-122) missing from Tailscale, likely overload

Pedro reports the Windows machine (`IPC-ADM-122`, has all 69 repos cloned
under `C:\Users\claude\Projects` per the 2026-09-18 clone-progress artifact)
keeps shutting down / dropping off — his working theory is too many
concurrent NAS actions (SMB backup, git operations, etc.) are overloading
it. Confirmed via `tailscale status --json`: it doesn't appear at all on
this tailnet, not even as a known-offline peer (only `ds` the NAS and `s24`
a phone show up) — a full absence like that usually means Tailscale isn't
running/logged in there, not just "machine is off."

**Next action:** before retrying the Windows pull/dependency-reinstall
work, wait for Pedro to confirm the machine is stable and check that
Tailscale is actually running there (same account as this Mac). Once it's
actually visible via `tailscale status`, avoid piling multiple NAS-heavy
operations (backup hook, large clones/pulls) onto it at once — do them
sequentially, not in parallel, given it apparently can't handle concurrent
load right now.
