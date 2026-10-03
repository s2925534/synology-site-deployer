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
