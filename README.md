# Synology Site Deployer

Synology Site Deployer is a local command-line tool for creating containerized Flask applications on a Synology NAS over SSH. It is designed for generic domains and generic NAS hosts. Configuration comes from `.env`, command-line options, or validated defaults.

Version 1 focuses on Flask, Docker Compose, optional MariaDB, and optional Cloudflare Tunnel route setup.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
synology-site --help
```

## Git Workflow

Functional phases should be tested before commit:

```bash
pytest
ruff check .
git status
git add .
git commit -m "Clear meaningful commit message"
git push
```
