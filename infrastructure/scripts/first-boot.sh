#!/usr/bin/env bash
#
# The one-time start. Run on the server, from /opt/teamsport360, after
# bootstrap-vps.sh and after the first CI build has pushed images:
#
#   ./infrastructure/scripts/first-boot.sh
#
# Idempotent — every step checks first, so re-running after a failure resumes
# rather than restarts. What it does, in the order the dependencies demand:
#
#   1. renders the Keycloak realm from .env (secrets and the real hostnames)
#   2. brings up PostgreSQL and Redis
#   3. creates the database roles and the Keycloak database
#   4. runs the migrations, then seeds permissions, roles, plans, competitions
#   5. starts everything else and publishes the admin bundle
#
# After this, deploys are automatic: push to main.

set -euo pipefail

cd "$(dirname "$0")/../.."
COMPOSE="docker compose -f docker-compose.prod.yml"
KC_DIR=infrastructure/docker/keycloak

if [[ ! -f .env ]]; then
  echo "No .env here. Run infrastructure/scripts/bootstrap-vps.sh first." >&2
  exit 78
fi
set -a; . ./.env; set +a

# A registry path must be lowercase, and the repository is `sportOS`; compose
# interpolates this straight into the image name. Rewritten in the file rather
# than only in this shell: any `docker compose` command typed by hand reads
# .env directly, and would fail on the uppercase value long after this script
# had appeared to fix it.
lowered="$(printf '%s' "${GITHUB_REPOSITORY:-}" | tr '[:upper:]' '[:lower:]')"
if [[ "$lowered" != "${GITHUB_REPOSITORY:-}" ]]; then
  sed -i "s#^GITHUB_REPOSITORY=.*#GITHUB_REPOSITORY=${lowered}#" .env
  export GITHUB_REPOSITORY="$lowered"
  printf '  .env: lowercased GITHUB_REPOSITORY to %s\n' "$lowered"
fi

step() { printf '\n\033[1;34m▸ %s\033[0m\n' "$1"; }

# --- 1. the realm -----------------------------------------------------------

step "Keycloak realm"
mkdir -p "${KC_DIR}/generated"
if [[ -f "${KC_DIR}/generated/realm-prod.json" ]]; then
  echo "  already rendered"
else
  # Rendered with Python rather than sed: an SMTP password is allowed to
  # contain any character at all, and a sed delimiter is not.
  SMTP_AUTH=$([[ -n "${SMTP_USERNAME:-}" ]] && echo true || echo false) \
  KEYCLOAK_VERIFY_EMAIL="${KEYCLOAK_VERIFY_EMAIL:-false}" \
  python3 - "$KC_DIR" <<'PY'
import json, os, string, sys

kc = sys.argv[1]
template = open(f"{kc}/realm-prod.json.template").read()


class Env(dict):
    def __missing__(self, key):
        return ""


# Two passes: substitute, then parse. JSON that does not parse is a Keycloak
# that starts with no realm at all, and the failure surfaces an hour later as
# "invalid client" on the login page.
rendered = string.Template(template).substitute(Env(os.environ))
realm = json.loads(rendered)
realm.pop("_comment", None)

missing = [k for k in ("REGISTRATION_CLIENT_SECRET", "DOMAINS_CLIENT_SECRET",
                       "PLATFORM_DOMAIN") if not os.environ.get(k)]
if missing:
    sys.exit(f"missing in .env: {', '.join(missing)}")

with open(f"{kc}/generated/realm-prod.json", "w") as fh:
    json.dump(realm, fh, indent=2)
print(f"  rendered for {os.environ['PLATFORM_DOMAIN']}")
PY
  # Readable by the container, and by nobody else. Keycloak runs as uid 1000
  # inside the image; 0600 owned by root — which is what this script usually
  # runs as — means the import fails with nothing but "Failed to run import"
  # and the server restarts for ever.
  chown 1000:0 "${KC_DIR}/generated/realm-prod.json"
  chmod 640 "${KC_DIR}/generated/realm-prod.json"
fi

# --- 2. the databases -------------------------------------------------------

step "PostgreSQL and Redis"
$COMPOSE up -d postgres redis
# A real query, not `pg_isready`. The postgres image runs a temporary server on
# a local socket while it initialises, then restarts it: `pg_isready` answers
# during that window and the next command finds no server at all.
until $COMPOSE exec -T postgres psql -U postgres -d footbola -tAc "SELECT 1" \
    >/dev/null 2>&1; do
  sleep 1
done
echo "  up"

step "Roles and the Keycloak database"
# The init directory only runs on a *virgin* data directory, which is exactly
# once. Applying it a second time would fail on CREATE ROLE, so ask first.
if $COMPOSE exec -T postgres psql -U postgres -tAc \
     "SELECT 1 FROM pg_roles WHERE rolname='app_runtime'" | grep -q 1; then
  echo "  already provisioned"
else
  $COMPOSE exec -T \
    -e APP_PASSWORD="$POSTGRES_APP_PASSWORD" \
    -e MIGRATOR_PASSWORD="$POSTGRES_MIGRATOR_PASSWORD" \
    -e PLATFORM_PASSWORD="$POSTGRES_PLATFORM_PASSWORD" \
    -e KEYCLOAK_DB_PASSWORD="$KEYCLOAK_DB_PASSWORD" \
    postgres psql -v ON_ERROR_STOP=1 -U postgres -d postgres \
    < infrastructure/docker/postgres/init/01-roles-and-databases.sql
  echo "  app_migrator, app_runtime, app_platform, keycloak"
fi

# --- 3. schema and reference data -------------------------------------------

step "Migrations"
$COMPOSE run --rm api .venv/bin/alembic upgrade head

step "Reference data"
# Permissions, role templates, plans, competitions. Each seeder reconciles by
# difference, so running them again is a no-op.
$COMPOSE run --rm api .venv/bin/python -m app.platform.seeds.reference
$COMPOSE run --rm api .venv/bin/python -m app.platform.seeds.plans
$COMPOSE run --rm api .venv/bin/python -m app.platform.seeds.competitions

# --- 4. everything else -----------------------------------------------------

step "The rest of the stack"
$COMPOSE up -d --remove-orphans
$COMPOSE run --rm admin-dist

step "Waiting for the API"
for _ in $(seq 1 60); do
  if $COMPOSE exec -T api python -c \
      "import urllib.request;urllib.request.urlopen('http://localhost:8000/health')" \
      >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

step "Registering club domains with Keycloak"
# A no-op on a fresh install; matters when this is a rebuild and clubs exist.
$COMPOSE run --rm api .venv/bin/python scripts/sync_domains.py || \
  echo "  skipped — no clubs yet, or Keycloak is still starting"

cat <<DONE

$(printf '\033[1;32m═══ Up ═══\033[0m')

  Admin       https://${PLATFORM_DOMAIN}
  API         https://api.${PLATFORM_DOMAIN}/docs
  Keycloak    https://auth.${PLATFORM_DOMAIN}   (${KEYCLOAK_ADMIN_USERNAME})
  Files       https://files.${PLATFORM_DOMAIN}

  Certificates are issued on the first visit, so the first page load is slow
  and the one after it is not.

  There are no accounts yet — no demo club, no demo users. Create the first
  tenant by signing up at https://${PLATFORM_DOMAIN}, or from the super-admin
  area once you have promoted yourself.

  Optional, 124 MB, adds country and city to analytics:
    $COMPOSE run --rm api .venv/bin/python scripts/fetch_geoip.py

DONE
