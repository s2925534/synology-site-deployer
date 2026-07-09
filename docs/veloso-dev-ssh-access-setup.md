# Fixing SSH Access to the veloso.dev Lightsail Instance

## The blocker

The key at `secrets/veloso-dev/lightsail-ssh-key.pem` connects to the instance
(see `secrets/veloso-dev/lightsail.env` for the address) and the *host key* now matches (you
confirmed the instance was rebuilt/restored), but the server rejects the key itself:

```
ubuntu@<lightsail-instance-ip>: Permission denied (publickey).
```

This means this key's **public** half simply isn't in that instance's
`~/.ssh/authorized_keys` for the `ubuntu` user — expected after a rebuild/restore, since that
doesn't carry old keys forward. Fixing this needs the AWS/Lightsail console, not SSH itself
(that's the chicken-and-egg part — you need *some* access to add SSH access).

Pick **one** of the three options below. Option 1 is the fastest since it reuses what's already
set up; Option 3 is the cleanest long-term if you want a dedicated, easily-revocable credential
just for this migration.

---

## Option 1 (fastest): authorize the key I already have

1. Sign in to the [AWS Lightsail console](https://lightsail.aws.amazon.com/).
2. Open the instance serving veloso.dev (region `ap-southeast-2` / Sydney, per the existing SSH
   config).
3. Click **Connect using SSH** — this opens a browser-based terminal, already logged in as the
   instance's default user (no key needed for this step, the console handles it).
4. In that browser terminal, run:
   ```
   mkdir -p ~/.ssh && chmod 700 ~/.ssh
   echo 'ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQCrRXEZRyoXE7iLhUsVypf4GHMj4pW0dtFg7Xh78NGeeeZhReRL9V+YM/O2f3V2Ng1CaIpUKKNOd68wa5Bd1l3MdT+cAqxhpyVVup99+npS+TJsy4OUW+sf7CSpXV73CCJ/BAI0/mqypH+XwY9yPgCniKSERfnmA7tXBFc1ywGW36v+WGhAARzPSuMehqHGG85tZSp/67LPa2Oypa/HMZ77VenoKUjYvEkn8JmhMG/pIIm6Pd8yf8xwsUyNfVmS6187RQX7K1OcqH95rDZp04FdEJhNjFePKzIO7RKUBMCOrizbtyoeZ3tIgG8LiB8GOWCj/o3A/D6cqglNUQE8r4oh migration-readonly' >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   ```
5. Confirm the user this landed under matches `ubuntu` (run `whoami` in that same terminal — if
   it says something else, e.g. `bitnami`, tell me and I'll update `secrets/veloso-dev/lightsail.env`'s
   `LIGHTSAIL_USER` accordingly instead of assuming `ubuntu`).
6. Tell me it's done — I'll retry the connection with the key already in the repo, no further
   changes needed on your end.

## Option 2: give me whatever key currently works

If you already have a *different* key you use to reach this instance day-to-day (e.g. one
downloaded when the instance was rebuilt), that's simpler than editing `authorized_keys` by hand:

1. Locate that private key file on your machine.
2. Tell me its path (or copy it into `secrets/veloso-dev/lightsail-ssh-key.pem` yourself, replacing
   the current one) and the username it connects as.
3. I'll use it directly — no console step needed.

## Option 3 (cleanest): generate a fresh, dedicated, disposable key

Best if you'd rather not add my key to your everyday access and want something you can revoke in
one step when the migration is done.

1. On your machine:
   ```
   ssh-keygen -t ed25519 -f /tmp/veloso-dev-migration -N "" -C "veloso-dev-migration-readonly"
   ```
   This creates `/tmp/veloso-dev-migration` (private) and `/tmp/veloso-dev-migration.pub` (public).
2. Print the public key so you can paste it in the next step:
   ```
   cat /tmp/veloso-dev-migration.pub
   ```
3. Open the instance's browser SSH the same way as Option 1, step 3, then:
   ```
   mkdir -p ~/.ssh && chmod 700 ~/.ssh
   echo '<paste the public key from step 2 here>' >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   ```
4. Move the private key into this project's workspace and clean up the temp copy:
   ```
   mv /tmp/veloso-dev-migration /Users/pedro/Documents/_Projects/synology-site-deployer/secrets/veloso-dev/lightsail-ssh-key.pem
   rm /tmp/veloso-dev-migration.pub
   ```
5. Tell me it's done and I'll retry the connection.
6. **When the migration is finished**, revoke it in one step: open the browser SSH again and
   remove that one line from `~/.ssh/authorized_keys` (or delete the whole file's contents and
   re-add only what you actually use day-to-day).

---

## After any option: what I'll do next

Once the connection works, I'll re-run the same read-only discovery I attempted before —
`hostname`, OS/nginx config, and a search for `wp-config.php` — nothing is written or changed on
the instance. That resolves the two open questions from `docs/lightsail-migration-mvp.md`
("Current credential status" table): whether `blog.veloso.dev` is a second WordPress install or
the same one, and whether anything on the instance actually uses S3 (which decides whether the
AWS access key is worth chasing down at all).
