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
