# Activity Log

Local, append-only record of every `create`/`deploy`/`update` run through this CLI. Written by
`synology_site.activity_log.record_activity`.

**This README is the only file in this directory tracked by git.** The actual log
(`history.jsonl`, or whatever `--log-filename`/`log_filename` you configure) is gitignored --
history accumulates locally and never bloats the repo or leaks per-deployment details (domains,
ports, workspace names) into git history. If you want to keep history somewhere durable, back up
this directory yourself (it's plain JSON Lines, safe to `cat`, `grep`, or ship to a log
aggregator).

## Format

One JSON object per line (JSON Lines / `.jsonl`), UTF-8, always at least `timestamp` and
`action`; everything else depends on the action. Example:

```json
{"action": "create", "db_enabled": false, "domain": "demo.example.com", "framework": "flask", "port": 5051, "project_path": "/volume1/docker/demo-example-com", "slug": "demo-example-com", "timestamp": "2026-08-05T16:20:00.123456+00:00", "workspace": null}
{"action": "deploy", "container_name": "demo-example-com", "domain": "demo.example.com", "port": 5051, "project_path": "/volume1/docker/demo-example-com", "slug": "demo-example-com", "timestamp": "2026-08-05T16:25:00.123456+00:00", "workspace": null}
{"action": "update", "built": true, "compose_uploaded": true, "domain": "demo.example.com", "project_path": "/volume1/docker/demo-example-com", "pulled": false, "slug": "demo-example-com", "timestamp": "2026-08-05T16:30:00.123456+00:00"}
```

## Reading it

```bash
# most recent 20 actions
tail -20 activity-log/history.jsonl | jq .

# everything for one domain
jq 'select(.domain == "demo.example.com")' activity-log/history.jsonl

# count actions by type
jq -r '.action' activity-log/history.jsonl | sort | uniq -c
```

## Notes

- Logging is best-effort: a failure to write here (e.g. read-only filesystem) is silently
  swallowed and never turns a successful `create`/`deploy`/`update` into a reported failure.
- Dry runs (`--dry-run`) are not logged, since nothing was actually done to the NAS.
- Failed runs (the command raised an error) are not logged here either -- see
  `NOTIFY_WEBHOOK_URL`/`NOTIFY_WEBHOOK_EVENTS` in `.env` for real-time failure notifications,
  which is a separate, already-existing mechanism (`synology_site/notifications.py`).
