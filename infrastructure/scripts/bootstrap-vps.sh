#!/usr/bin/env bash
#
# Prepare a fresh Ubuntu server to run TeamSport360, and print exactly what to
# paste into GitHub afterwards.
#
# The repository is private, so the server cannot fetch this script before it
# has a deploy key — which is one of the things this script creates. Send it
# from your own machine instead:
#
#   ssh root@SERVER 'bash -s' -- teamsport360.com you@teamsport360.com ovidiubistrian/sportOS \
#     < infrastructure/scripts/bootstrap-vps.sh
#
# From a non-root account, `ssh you@SERVER 'sudo bash -s' -- …` instead.
#
# Safe to run twice. Every step checks whether it has already been done, so a
# half-finished run — the usual outcome when a deploy key is missing — is fixed
# by fixing that one thing and running it again. Nothing is regenerated on a
# second run: secrets are written once and then left alone, because rotating
# the database password out from under a running database is not a repair.
#
# It does NOT start the stack. The first boot needs decisions this script has
# no business making (the Keycloak realm, whether to seed anything), and those
# are §5 of docs/DEPLOY.md.

set -euo pipefail

PLATFORM_DOMAIN="${1:-}"
ACME_EMAIL="${2:-}"
REPO="${3:-}"

if [[ -z "$PLATFORM_DOMAIN" || -z "$ACME_EMAIL" || -z "$REPO" ]]; then
  cat >&2 <<USAGE
usage: bootstrap-vps.sh <domain> <acme-email> <github-owner/repo>
   eg: bootstrap-vps.sh teamsport360.com ops@teamsport360.com ovidiubistrian/sportOS
USAGE
  exit 64
fi

if [[ $EUID -ne 0 ]]; then
  echo "Run as root: sudo bash bootstrap-vps.sh …" >&2
  exit 77
fi

APP_DIR=/opt/teamsport360
DEPLOY_USER=deploy
CI_KEY=/root/.ssh/teamsport360_ci        # GitHub → this server
SERVER_KEY_DIR="/home/${DEPLOY_USER}/.ssh"  # this server → GitHub

step() { printf '\n\033[1;34m▸ %s\033[0m\n' "$1"; }
note() { printf '  %s\n' "$1"; }
secret() { openssl rand -hex 32; }

# --- packages ---------------------------------------------------------------

step "System packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq ca-certificates curl git ufw fail2ban openssl
note "base packages present"

step "Docker"
if ! command -v docker >/dev/null 2>&1; then
  # Docker's own repository: Ubuntu's package predates `docker compose` as a
  # plugin, and the compose files here assume the plugin.
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi
note "$(docker --version)"
note "$(docker compose version)"

# --- the machine ------------------------------------------------------------

step "Firewall"
# Only these three. PostgreSQL, Redis, Keycloak and MinIO are reachable on the
# Docker network and must never be reachable from the internet.
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
note "open: 22, 80, 443 — everything else closed"

step "Swap"
if ! swapon --show | grep -q '/swapfile'; then
  # Two gigabytes, so a memory spike during a migration degrades instead of
  # having the kernel choose between Keycloak and PostgreSQL.
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  note "2G swapfile added"
else
  note "swap already present"
fi

step "Deploy user"
if ! id "$DEPLOY_USER" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "$DEPLOY_USER" >/dev/null
fi
usermod -aG docker "$DEPLOY_USER"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$SERVER_KEY_DIR"
note "$DEPLOY_USER exists, in the docker group, no sudo"

# --- keys -------------------------------------------------------------------
#
# Two, in opposite directions, so neither can do the other's job: losing one
# does not hand over both.

step "Key: GitHub Actions → this server"
if [[ ! -f "$CI_KEY" ]]; then
  install -d -m 700 /root/.ssh
  ssh-keygen -t ed25519 -q -N "" -C "github-actions@${PLATFORM_DOMAIN}" -f "$CI_KEY"
fi
touch "${SERVER_KEY_DIR}/authorized_keys"
if ! grep -qF "$(cat "${CI_KEY}.pub")" "${SERVER_KEY_DIR}/authorized_keys"; then
  cat "${CI_KEY}.pub" >> "${SERVER_KEY_DIR}/authorized_keys"
fi
chown "$DEPLOY_USER:$DEPLOY_USER" "${SERVER_KEY_DIR}/authorized_keys"
chmod 600 "${SERVER_KEY_DIR}/authorized_keys"
note "authorised for $DEPLOY_USER"

step "Key: this server → GitHub"
if [[ ! -f "${SERVER_KEY_DIR}/id_ed25519" ]]; then
  sudo -u "$DEPLOY_USER" ssh-keygen -t ed25519 -q -N "" \
    -C "server@${PLATFORM_DOMAIN}" -f "${SERVER_KEY_DIR}/id_ed25519"
fi
sudo -u "$DEPLOY_USER" ssh-keyscan -t ed25519 github.com \
  >> "${SERVER_KEY_DIR}/known_hosts" 2>/dev/null || true
sort -u -o "${SERVER_KEY_DIR}/known_hosts" "${SERVER_KEY_DIR}/known_hosts"
chown "$DEPLOY_USER:$DEPLOY_USER" "${SERVER_KEY_DIR}/known_hosts"
note "read-only deploy key ready"

# --- application directory and secrets --------------------------------------

step "Application directory"
install -d -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR" "${APP_DIR}/backups"

ENV_FILE="${APP_DIR}/.env"
if [[ -f "$ENV_FILE" ]]; then
  note ".env already exists — left untouched"
else
  step "Generating secrets"
  PG_PASS=$(secret); PG_APP=$(secret); PG_MIG=$(secret); PG_PLAT=$(secret)
  KC_DB=$(secret); KC_ADMIN=$(secret)
  APP_SECRET=$(secret); REG_SECRET=$(secret); DOM_SECRET=$(secret)
  REVALIDATE=$(secret); S3_KEY=$(secret); S3_SECRET=$(secret)

  cat > "$ENV_FILE" <<ENV
# Written by bootstrap-vps.sh. Every value below is unique to this server.
# Losing this file means losing the database: back it up somewhere that is not
# this machine.

APP_ENV=production
LOG_LEVEL=INFO
PLATFORM_DOMAIN=${PLATFORM_DOMAIN}
ACME_EMAIL=${ACME_EMAIL}
GITHUB_REPOSITORY=${REPO}
IMAGE_TAG=latest

SECRET_KEY=${APP_SECRET}

POSTGRES_PASSWORD=${PG_PASS}
POSTGRES_APP_PASSWORD=${PG_APP}
POSTGRES_MIGRATOR_PASSWORD=${PG_MIG}
POSTGRES_PLATFORM_PASSWORD=${PG_PLAT}

DATABASE_URL=postgresql+asyncpg://app_runtime:${PG_APP}@postgres:5432/footbola
DATABASE_PLATFORM_URL=postgresql+asyncpg://app_platform:${PG_PLAT}@postgres:5432/footbola
DATABASE_MIGRATOR_URL=postgresql+psycopg://app_migrator:${PG_MIG}@postgres:5432/footbola
REDIS_URL=redis://redis:6379/0

KEYCLOAK_DB_PASSWORD=${KC_DB}
KEYCLOAK_ADMIN_USERNAME=admin
KEYCLOAK_ADMIN_PASSWORD=${KC_ADMIN}
REGISTRATION_CLIENT_SECRET=${REG_SECRET}
DOMAINS_CLIENT_SECRET=${DOM_SECRET}

OIDC_ISSUER=http://keycloak:8080/realms/football-os
OIDC_PUBLIC_ISSUER=https://auth.${PLATFORM_DOMAIN}/realms/football-os
OIDC_AUDIENCE=football-os-api

S3_ACCESS_KEY=${S3_KEY}
S3_SECRET_KEY=${S3_SECRET}
S3_BUCKET=teamsport360
S3_ENDPOINT_URL=http://minio:9000
S3_PUBLIC_URL=https://files.${PLATFORM_DOMAIN}

REVALIDATE_SECRET=${REVALIDATE}

# The club's own mailbox. Until these are set, nothing is emailed — no
# invitations, no campaigns, no password resets.
SMTP_HOST=
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USERNAME=
SMTP_PASSWORD=
EMAIL_FROM_ADDRESS=noreply@${PLATFORM_DOMAIN}
EMAIL_FROM_NAME=TeamSport360

# Keycloak emails a confirmation link before an account may sign in. Turn this
# on once SMTP above works — before that it locks every new supporter out.
KEYCLOAK_VERIFY_EMAIL=false

# Optional integrations, off until a key exists.
API_FOOTBALL_KEY=
ANTHROPIC_API_KEY=
MAILGUN_API_KEY=
MAILGUN_DOMAIN=

# The one line that matters most on a production server: left true, this comes
# up with a demo club and four logins whose password is 'password'.
SEED_DEMO_DATA=false
ENV

  chown "$DEPLOY_USER:$DEPLOY_USER" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  note "wrote $ENV_FILE (0600, owned by $DEPLOY_USER)"
fi

# --- the checkout -----------------------------------------------------------

step "Repository"
CLONE_OK=1
if [[ -d "${APP_DIR}/.git" ]]; then
  note "already cloned"
else
  if sudo -u "$DEPLOY_USER" git clone -q "git@github.com:${REPO}.git" /tmp/ts360-clone 2>/dev/null; then
    sudo -u "$DEPLOY_USER" cp -r /tmp/ts360-clone/. "$APP_DIR"/
    rm -rf /tmp/ts360-clone
    note "cloned into $APP_DIR"
  else
    CLONE_OK=0
    note "could not clone yet — the deploy key below is not on GitHub"
  fi
fi

# --- what a human still has to do -------------------------------------------

PUBLIC_IP=$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')

cat <<REPORT

$(printf '\033[1;32m═══ Server is ready ═══\033[0m')

  domain      ${PLATFORM_DOMAIN}
  address     ${PUBLIC_IP}
  app         ${APP_DIR}
  env         ${ENV_FILE}  (0600 — the only copy, back it up)

$(printf '\033[1;33m1. DNS — both records, same address\033[0m')

     A    ${PLATFORM_DOMAIN}      ${PUBLIC_IP}
     A    *.${PLATFORM_DOMAIN}    ${PUBLIC_IP}

   The wildcard is what gives every club its own site the moment it signs up.

$(printf '\033[1;33m2. GitHub → Settings → Secrets and variables → Actions\033[0m')

   VPS_HOST          ${PUBLIC_IP}
   VPS_USER          ${DEPLOY_USER}
   PLATFORM_DOMAIN   ${PLATFORM_DOMAIN}
   VPS_SSH_KEY       the private key printed below, in full

$(printf '\033[1;33m3. GitHub → Settings → Deploy keys → Add, read-only\033[0m')

$(cat "${SERVER_KEY_DIR}/id_ed25519.pub")

$(printf '\033[1;33m4. First boot\033[0m')

   See §5 of docs/DEPLOY.md — the Keycloak realm, the database roles and the
   first migration. Then every push to main deploys itself.

REPORT

if [[ $CLONE_OK -eq 0 ]]; then
  printf '\033[1;31m   Add the deploy key (3) first, then run this script again to clone.\033[0m\n\n'
fi

cat <<'WARNING'
─── VPS_SSH_KEY ──────────────────────────────────────────────────────────────
Copy everything between the BEGIN and END lines, inclusive, into the GitHub
secret. It is shown once here; it also stays in /root/.ssh/ on this server.
Anyone holding it can deploy to this machine.
──────────────────────────────────────────────────────────────────────────────
WARNING
cat "$CI_KEY"
echo

cat <<'LAST'
Last, once you have confirmed you can log in with that key:

    sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
    systemctl restart ssh

Do it in that order. Disabling passwords before the key works locks you out.
LAST
