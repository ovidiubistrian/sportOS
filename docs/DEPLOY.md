# Deploying to a VPS

Everything below is done once. After that, a push to `main` that passes CI
deploys itself.

---

## 1. The server

**Minimum that actually works: 4 vCPU, 8 GB RAM, 80 GB SSD.**

Not marketing sizing — a count of what runs: PostgreSQL, Redis, Keycloak (a
JVM, ~700 MB resident), MinIO, the API with four workers, two Python workers,
the Next server and Caddy. On 4 GB, Keycloak and PostgreSQL will fight and the
loser is whichever one the kernel picks. Hetzner CPX31 or CX32, DigitalOcean
4 vCPU / 8 GB, Contabo VPS M — any of them, in Germany or Romania for latency.

Ubuntu 24.04 LTS.

### The short way

Sections 1, 3 and 4 below are what `infrastructure/scripts/bootstrap-vps.sh`
does. Run it from your own machine — the repository is private, so the server
cannot fetch it before it has the deploy key the script creates:

```bash
ssh root@YOUR_SERVER 'bash -s' -- teamsport360.com you@teamsport360.com ovidiubistrian/sportOS \
  < infrastructure/scripts/bootstrap-vps.sh
```

It is safe to run twice, never regenerates a secret it has already written, and
ends by printing the four GitHub secrets and the deploy key. The rest of this
document is what it is doing, and §2 and §5 are still yours.

### Install, by hand

```bash
ssh root@YOUR_SERVER

apt update && apt upgrade -y
apt install -y ca-certificates curl git ufw fail2ban

# Docker, from Docker's own repository. The distribution's package is old
# enough to lack `docker compose` as a plugin.
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# A user for the deploy, so nothing runs as root.
adduser --disabled-password --gecos "" deploy
usermod -aG docker deploy

# Only these three ports. Everything else — Postgres, Redis, Keycloak, MinIO —
# is reachable only on the Docker network.
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Disable password logins once your key works.
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh
```

### Swap

Two gigabytes, so a memory spike during a migration degrades instead of killing
PostgreSQL:

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

---

## 2. DNS

Both records point at the same address. The wildcard is what gives every club
its own site the moment it signs up.

| Type | Name | Value |
|---|---|---|
| A | `teamsport360.com` | your server IP |
| A | `*.teamsport360.com` | your server IP |

`api.`, `auth.` and `files.` are covered by the wildcard.

**A club with its own domain** points a `CNAME` at `teamsport360.com`. Nothing
else is needed: the certificate is issued the first time somebody visits, and
only after the API has confirmed the hostname belongs to a club — see
`/api/v1/public/tls-check`. That gate is why a stranger cannot point a DNS
record at this server and make it request certificates for their domain.

---

## 3. The checkout on the server

```bash
su - deploy
sudo mkdir -p /opt/teamsport360 && sudo chown deploy /opt/teamsport360
git clone git@github.com:ovidiubistrian/sportOS.git /opt/teamsport360
cd /opt/teamsport360
mkdir -p backups
```

The deploy key: generate one on the server (`ssh-keygen -t ed25519 -C deploy`)
and add the public half to the repository under **Settings → Deploy keys**,
read-only.

---

## 4. Secrets

On the server, `/opt/teamsport360/.env`, `chmod 600`. Generate each with
`openssl rand -hex 32` — never reuse one:

```bash
PLATFORM_DOMAIN=teamsport360.com
ACME_EMAIL=you@teamsport360.com
APP_ENV=production

SECRET_KEY=…
POSTGRES_PASSWORD=…
POSTGRES_APP_PASSWORD=…
POSTGRES_MIGRATOR_PASSWORD=…
POSTGRES_PLATFORM_PASSWORD=…
KEYCLOAK_DB_PASSWORD=…
KEYCLOAK_ADMIN_USERNAME=admin
KEYCLOAK_ADMIN_PASSWORD=…
REGISTRATION_CLIENT_SECRET=…
DOMAINS_CLIENT_SECRET=…
REVALIDATE_SECRET=…
S3_ACCESS_KEY=…
S3_SECRET_KEY=…

DATABASE_URL=postgresql+asyncpg://app_runtime:${POSTGRES_APP_PASSWORD}@postgres:5432/footbola
DATABASE_PLATFORM_URL=postgresql+asyncpg://app_platform:${POSTGRES_PLATFORM_PASSWORD}@postgres:5432/footbola
DATABASE_MIGRATOR_URL=postgresql+psycopg://app_migrator:${POSTGRES_MIGRATOR_PASSWORD}@postgres:5432/footbola
REDIS_URL=redis://redis:6379/0

OIDC_ISSUER=http://keycloak:8080/realms/football-os
OIDC_PUBLIC_ISSUER=https://auth.teamsport360.com/realms/football-os
S3_PUBLIC_URL=https://files.teamsport360.com

# The club's own mailbox, once you have one.
SMTP_HOST=…
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USERNAME=…
SMTP_PASSWORD=…
EMAIL_FROM_ADDRESS=noreply@teamsport360.com
EMAIL_FROM_NAME=TeamSport360

# Off until a club needs a real feed.
API_FOOTBALL_KEY=…
ANTHROPIC_API_KEY=…

SEED_DEMO_DATA=false
```

`SEED_DEMO_DATA=false` matters. Left true, a production server comes up with a
demo club, demo players and four logins whose password is `password`.

### In GitHub → Settings → Secrets and variables → Actions

| Secret | What |
|---|---|
| `VPS_HOST` | server IP or hostname |
| `VPS_USER` | `deploy` |
| `VPS_SSH_KEY` | private key whose public half is in `deploy`'s `authorized_keys` |
| `PLATFORM_DOMAIN` | `teamsport360.com` |

`GITHUB_TOKEN` is provided automatically and is what pushes to the registry.

---

## 5. First run

The images have to exist before the server can pull them, so push to `main`
first and let CI build. That run's deploy step will fail — there is no database
yet for it to migrate — and that is expected exactly once.

Then, on the server:

```bash
cd /opt/teamsport360

# GHCR needs a login for a private package. A classic token with read:packages.
echo YOUR_GITHUB_PAT | docker login ghcr.io -u ovidiubistrian --password-stdin

./infrastructure/scripts/first-boot.sh
```

That renders the Keycloak realm from `.env`, creates the database roles and the
Keycloak database, migrates, seeds permissions/roles/plans/competitions, starts
everything and publishes the admin bundle. It is idempotent — if it fails
halfway, fix the cause and run it again.

Two things it deliberately does not do:

- **The Keycloak admin password** in `.env` is the bootstrap admin. Sign in at
  `https://auth.teamsport360.com` once and create yourself a real account.
- **`KEYCLOAK_VERIFY_EMAIL=false`** until SMTP works. Turned on before that, it
  emails every new supporter a confirmation link that never arrives.

Optional, 124 MB, adds country and city to analytics:

```bash
docker compose -f docker-compose.prod.yml run --rm api .venv/bin/python scripts/fetch_geoip.py
```

### About the realm

`infrastructure/docker/keycloak/realm-prod.json.template` is the source. Both
client secrets and every redirect URI come from `.env`, so nothing is shared
with development and no secret is in the repository. Keycloak imports the
rendered file on its first start; after that the realm lives in its database
and the file is ignored — later changes are made in the admin console, not by
editing the template.

Club websites are the one moving part: Keycloak does not accept a wildcard in
the host part of a redirect URI, so `supporter-web` starts with only the
platform domain, and each club's hostname is added by the API when its domain
is verified. If a realm is ever rebuilt, `scripts/sync_domains.py` puts them
all back.

---

## 6. After that

Push to `main`. CI runs the suite against a real database; if it passes, images
are built and the server pulls them. The deploy takes a database dump first,
runs migrations before the new code, and fails loudly if the health check does
not answer.

### Rolling back

Two ways, and they do the same thing.

**From the server, one command:**

```bash
cd /opt/teamsport360
./infrastructure/scripts/rollback.sh                 # the deploy before this one
./infrastructure/scripts/rollback.sh <commit-sha>    # a specific one
```

It reads `deploys.log` — written by every successful deploy — to find the
image tag, the commit and the Alembic revision that were live, takes a dump of
what it is about to replace, checks the tree out to the matching commit, pulls
those images, **walks the schema back**, reseeds permissions and health-checks.
It asks you to type the tag before it does any of it.

**From GitHub:** Actions → Deploy → Run workflow → paste the SHA. Images are
tagged by SHA precisely so this is possible. The workflow now checks the tree
out to that SHA too, so the compose file and the Caddyfile match the images
rather than being whatever is newest on `main`.

**The database is not restored unless you ask.** `--with-database` replaces it
from the last pre-deploy dump and throws away everything written since — every
order, ticket and article. Occasionally the right answer, never the automatic
one:

```bash
./infrastructure/scripts/rollback.sh <sha> --with-database
```

**Why the schema goes back too.** Rolling images back on their own leaves the
old application talking to the newer schema. Migrations are additive by policy,
so it usually works — and when it does not, it fails quietly, which is the
worst way for a rollback to fail.

**Migrations must be additive.** Migrations run *before* the new code, so for
one moment the old code is talking to the new schema. Adding a column is safe;
renaming or dropping one in the same release is not. Drop in the release after.

### Backups

The pre-deploy dump is not a backup — it only exists when you deploy. Add a
nightly one, through the same script so it is verified and pruned the same way:

```bash
crontab -e
0 3 * * * cd /opt/teamsport360 && BACKUP_KEEP=14 ./infrastructure/scripts/backup.sh nightly
```

`backup.sh` dumps to a temporary name, checks the archive with `gunzip -t`,
refuses anything implausibly small, and only then moves it into place beside a
`.json` manifest recording the commit, the image tag and the Alembic revision.
Retention is per label, so a run of deploys cannot age out the nightly copies.

A truncated dump passes `gunzip -t` only if it is truncated on a block
boundary; an *empty* one passes it every time, which is why the size floor is
there and not decoration.

Copy them off the server — a backup on the same disk as the database is not a
backup. `rclone` to object storage is the usual answer.

### Restoring

```bash
gunzip -c backups/nightly-2026-08-16.sql.gz | \
  docker compose -f docker-compose.prod.yml exec -T postgres psql -U postgres footbola
```

---

## What is deliberately not here

- **No monitoring.** Uptime Kuma on a second host, or a hosted checker against
  `/health`, is thirty minutes of work and the first thing to add.
- **No object-storage backup.** MinIO holds crests, hero images and player
  photographs. Losing those is not recoverable from a database dump.
- **One server.** No redundancy: a reboot is downtime. That is the right trade
  at this stage, but it is a trade, and it should be a decision rather than a
  surprise at three in the morning.
