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

## 2026-10-12: local → all — Windows (IPC-ADM-122) back online; this project migrated there

Resolves the 2026-10-04 "Windows offline" note. `IPC-ADM-122` is back on the
tailnet (`100.68.198.20`) and reachable over key-based SSH. This project is
now fully migrated to it (`C:\Users\claude\Projects\synology-site-deployer`) —
code via GitHub, and every gitignored/local-only file verified present
(`.env`, `secrets/`, `migration-backups/` 16,789 files byte-exact, reports,
`activity-log`). See the 2026-10-12 JOURNAL entry for the verification detail
and the Mac→Windows SSH gotchas.

The Mac working copy is redundant and safe to delete; Pedro removes it.

Lesson that still stands from the overload episode: when syncing to/from the
NAS, don't pile concurrent NAS-heavy operations on at once. This migration
deliberately went Mac→Windows directly over Tailscale and left the NAS out of
the loop.
