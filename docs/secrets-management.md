# Secrets Management Options

Today, `synology-site` reads plaintext `.env` files:

- Root `.env` for the default workspace
- `secrets/<workspace>/cloudflare.env`
- `secrets/<workspace>/nas.env`
- `secrets/<workspace>/lightsail.env`
- `secrets/<workspace>/godaddy.env`
- Generated recovery files such as `secrets/<project>.env`

This is acceptable for a single-user machine with disk encryption and a private repo, but it is
not ideal on shared machines or team workflows. Keep `secrets/` out of Git; it is already
gitignored.

## Recommended Paths

### `sops` + `age`

Best fit for this project if encrypted files need to live beside the repo.

Pros:

- Works with ordinary files and Git
- No hosted secrets service required
- Good fit for `secrets/<workspace>/*.env`

Tradeoffs:

- Every machine that runs deploys needs the `age` private key
- The CLI would need a decrypt-before-load step or wrapper command

Practical pattern:

```text
secrets/
  acmeco/
    cloudflare.env.sops
    nas.env.sops
```

Decrypt locally before running:

```bash
sops -d secrets/acmeco/cloudflare.env.sops > secrets/acmeco/cloudflare.env
sops -d secrets/acmeco/nas.env.sops > secrets/acmeco/nas.env
```

### 1Password CLI

Best fit when secrets already live in 1Password and the deployer runs interactively.

Pros:

- Strong UI and access control
- Good auditability
- No secrets at rest in the repo

Tradeoffs:

- Requires `op` login/session on the machine
- More friction for unattended jobs unless service accounts are configured

Practical pattern:

```bash
op inject -i .env.tpl -o .env
```

### Doppler

Best fit for teams that already use Doppler for app environments.

Pros:

- Centralized environment management
- Good CI support
- Can run commands with injected env vars

Tradeoffs:

- Hosted service dependency
- Workspace file discovery would need either generated files or direct Doppler integration

Practical pattern:

```bash
doppler run -- synology-site deploy app.example.com --compose-file docker-compose.yml
```

## What Would Need To Change In This CLI

The least disruptive future implementation is a secret-source abstraction before `load_config()`:

1. Plain files keep working as the default.
2. Optional decrypt/inject adapters materialize the same key/value map currently read from
   `.env`, `cloudflare.env`, and `nas.env`.
3. Generated recovery secrets remain local files unless the chosen backend supports writes.

Avoid making a hosted secrets service mandatory. The current plaintext file behavior should
remain the simple default for personal NAS users.

## Current Recommendation

For solo use: keep the current `.env`/`secrets/` layout, use full-disk encryption, and never commit
secret files.

For shared or team use: use `sops` + `age` first. It fits the existing file-based workspace model
with the smallest future code change.
