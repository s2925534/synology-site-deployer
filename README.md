# Synology Site Deployer

Synology Site Deployer is a local Python CLI for deploying containerized Flask sites to a Synology NAS over SSH. It creates a project folder, uploads a generated Flask application, writes Docker Compose files, optionally adds a MariaDB container, starts the project, checks health endpoints, and helps configure Cloudflare Tunnel routes.

The tool is generic. Domains, NAS hosts, Docker paths, Cloudflare zones, tunnel names, and ports come from `.env`, CLI options, or validated defaults.

## Developer

Developed by Pedro Veloso.

Contact: `pedro@veloso.dev`

## What It Does

- Deploys Flask apps to a Synology NAS using Docker Compose.
- Optionally creates a MariaDB 11 container with a private Docker network and persistent volume.
- Generates a non-secret project README on the NAS.
- Generates `docs/DATABASE.md` on the NAS when DB mode is enabled.
- Finds a free local NAS port.
- Checks `/health` and `/db-health`.
- Prints manual Cloudflare Tunnel setup instructions if API credentials are missing.
- Optionally creates or updates a Cloudflare tunnel route and proxied DNS record when API credentials are complete.

## What It Does Not Do

- It does not expose Synology DSM, SSH, or MariaDB to the public internet.
- It does not require the Synology DSM database package.
- It does not deploy frameworks other than Flask in version 1.
- It does not commit `.env`, tokens, generated passwords, or database credentials.

## Requirements

- Python 3.11 or newer
- SSH access to the NAS
- Synology Container Manager
- Docker and Docker Compose on the NAS
- A Docker root path such as `/volume1/docker`
- Optional: Cloudflare domain and Cloudflare Tunnel running on the NAS

On Synology, Docker may be available at `/usr/local/bin/docker` instead of the default shell `PATH`. The tool detects this path automatically. If the SSH user can only access Docker through `sudo`, the tool can use `sudo -S` with the configured SSH password.

## Install For Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
synology-site --help
```

On some Python 3.13 environments, editable installs may be affected by hidden `.pth` handling. A normal local install also works:

```bash
pip install ".[dev]"
```

## Configure

Copy `.env.example` to `.env` and edit it:

```bash
cp .env.example .env
```

Important settings:

```env
NAS_HOST=192.168.1.100
NAS_PORT=22
NAS_USER=your_synology_username
NAS_DOCKER_ROOT=/volume1/docker
LOCAL_BASE_URL_HOST=192.168.1.100
DEFAULT_START_PORT=5050
DEFAULT_END_PORT=5999
CF_ZONE_DOMAIN=example.com
CF_TUNNEL_NAME=my-nas-tunnel
DB_MODE=none
```

Use `NAS_SSH_KEY_PATH` when possible. If no key or password is set, the CLI prompts securely.

For Synology systems where Docker requires elevated access, the SSH user should be allowed to run Docker through DSM permissions or `sudo`. The tool does not print the configured SSH password.

## Cloudflare Setup

Cloudflare is optional for local deployment. For public access through Cloudflare Tunnel:

- The domain must be managed in Cloudflare.
- A tunnel must already exist.
- The tunnel connector should be running on the NAS.
- `CF_ZONE_DOMAIN` must match the Cloudflare zone, including domains such as `company.com.au`.
- API credentials are optional.

If these values are complete, API automation is attempted:

```env
CF_API_TOKEN=
CF_ACCOUNT_ID=
CF_ZONE_ID=
CF_ZONE_DOMAIN=example.com
CF_TUNNEL_ID=
```

If they are missing, the CLI prints manual instructions.

## Deploy Flask

```bash
synology-site create demo.example.com
```

This creates a generated Flask app, Dockerfile, Compose file, marker file, and docs under:

```text
/volume1/docker/demo-example-com
```

The public page shows only:

```text
It works
demo.example.com is running successfully.
```

## Deploy Flask With MariaDB

```bash
synology-site create demo.example.com --with-db
```

This adds:

- MariaDB image `mariadb:11`
- Private Docker network
- Persistent Docker volume
- App `.env` on the NAS with permission `600`
- `docs/DATABASE.md` on the NAS with permission `600`
- `/db-health`

MariaDB port `3306` is not published by default. Do not expose MariaDB to the public internet.

## Manual Cloudflare Route

```bash
synology-site cloudflare-instructions demo.example.com --port 5051
```

For nested domains, the subdomain is calculated from `CF_ZONE_DOMAIN`. For example:

```text
app.client.example.com + example.com -> app.client
tools.company.com.au + company.com.au -> tools
```

## Error 1033

If Cloudflare Error 1033 appears, the tunnel DNS record exists but Cloudflare cannot resolve the tunnel connection.

Check the NAS:

```bash
sudo docker ps
sudo docker ps -a
```

If the tunnel container is stopped:

```bash
sudo docker start cloudflared
```

If the container has a random name:

```bash
sudo docker stop clever_carver
sudo docker rename clever_carver cloudflared
sudo docker start cloudflared
sudo docker update --restart unless-stopped cloudflared
```

Or run:

```bash
synology-site tunnel-fix-autostart
```

## Operations

```bash
synology-site check-nas
synology-site list
synology-site start demo.example.com
synology-site stop demo.example.com
synology-site set-autostart demo.example.com
synology-site remove demo.example.com
```

Remove keeps project files and volumes by default. Use explicit flags for destructive cleanup:

```bash
synology-site remove demo.example.com --delete-files
synology-site remove demo.example.com --delete-volumes
```

## Docker Commands On The NAS

```bash
docker ps
docker logs demo-example-com
cd /volume1/docker/demo-example-com
docker compose restart
docker compose down
docker compose up -d
```

If Docker is only available through Synology's full path or `sudo`, use:

```bash
/usr/local/bin/docker ps
sudo /usr/local/bin/docker ps
```

## Database Access And Backup

Read database credentials on the NAS:

```bash
cat /volume1/docker/demo-example-com/docs/DATABASE.md
```

Back up MariaDB:

```bash
docker exec demo-example-com-db mariadb-dump -uroot -p demo_example_com > demo_example_com_backup.sql
```

## Rebooting The NAS

Containers use `restart: unless-stopped`. Before rebooting, confirm important containers are running:

```bash
docker ps
```

After reboot, check:

```bash
docker ps
curl http://LOCAL_BASE_URL_HOST:PORT/health
```

## Future Framework Roadmap

The scaffold registry currently contains Flask only:

```python
FRAMEWORKS = {
    "flask": FlaskScaffold(),
}
```

Future versions can add Laravel, Lumen, Slim, Symfony, Node.js, React, Vue, or other generators.

## Testing

```bash
pytest
ruff check .
synology-site --help
```

Tests mock SSH, Docker commands, Cloudflare API calls, and HTTP health checks. They do not require real Synology access.

## Commit And Push Workflow

For functional changes:

```bash
pytest
ruff check .
git status
git add .
git commit -m "Clear meaningful commit message"
git push
```

## License

Synology Site Deployer is released under the MIT License.

It is free to use, copy, modify, merge, publish, distribute, sublicense, and sell copies, subject to the license terms. The software is provided without warranties of any kind. See [LICENSE](LICENSE).
