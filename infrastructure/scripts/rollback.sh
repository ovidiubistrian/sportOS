#!/usr/bin/env bash
# Put production back the way it was, in one command.
#
#   ./infrastructure/scripts/rollback.sh                 # the deploy before this one
#   ./infrastructure/scripts/rollback.sh <commit-sha>    # a specific one
#   ./infrastructure/scripts/rollback.sh <sha> --with-database
#
# **Code and schema roll back together.** Rolling the images back on their own
# leaves the old application talking to the newer schema, which usually works
# — migrations are additive by policy — and occasionally does not, in the
# quietest possible way. So this walks Alembic back to the revision that was
# live at the target deploy, taken from the record written at the time.
#
# The checkout matters as much as the images. The compose file, the Caddyfile
# and the migration history all live in the working tree, and a rollback that
# pulls old images while leaving the tree on the newest commit is running a
# combination that was never tested.
#
# **The database is not restored unless you ask.** `--with-database` throws
# away everything written since the backup was taken — every order, ticket and
# article. It is occasionally the right answer and never the automatic one.
set -euo pipefail

cd "$(dirname "$0")/../.."

COMPOSE="docker compose -f docker-compose.prod.yml"
LOG="deploys.log"
RESTORE_DB=false
TARGET=""

for arg in "$@"; do
  case "$arg" in
    --with-database) RESTORE_DB=true ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) TARGET="$arg" ;;
  esac
done

if [ ! -f "$LOG" ]; then
  echo "no ${LOG} on this server — nothing has recorded a deploy yet." >&2
  echo "Roll back by hand: Actions -> Deploy -> Run workflow with an image tag." >&2
  exit 1
fi

# Each line: <iso8601> <image_tag> <alembic_revision> <commit>
if [ -z "$TARGET" ]; then
  # The one before the deploy currently live.
  LINE="$(tail -n 2 "$LOG" | head -n 1)"
else
  LINE="$(grep -F " ${TARGET} " "$LOG" | tail -n 1 || true)"
  if [ -z "$LINE" ]; then
    echo "no recorded deploy for ${TARGET}." >&2
    echo "Recent deploys:" >&2
    tail -n 10 "$LOG" >&2
    exit 1
  fi
fi

read -r WHEN TAG REVISION COMMIT <<< "$LINE"
CURRENT="$(tail -n 1 "$LOG" | awk '{print $2}')"

if [ "$TAG" = "$CURRENT" ]; then
  echo "${TAG} is already what is running." >&2
  exit 1
fi

echo "rolling back"
echo "   from : ${CURRENT}"
echo "     to : ${TAG}  (deployed ${WHEN}, migration ${REVISION})"
$RESTORE_DB && echo "  database : WILL BE RESTORED — everything since is lost"
echo

read -r -p "type the tag to confirm: " TYPED
[ "$TYPED" = "$TAG" ] || { echo "not confirmed"; exit 1; }

# A dump of the state we are leaving, so a rollback is itself reversible.
IMAGE_TAG="$CURRENT" ./infrastructure/scripts/backup.sh pre-rollback

export IMAGE_TAG="$TAG"
export GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-ovidiubistrian/sportos}"

git fetch --quiet origin
git checkout --quiet --detach "${COMMIT:-$TAG}"

$COMPOSE pull --quiet

# Down before up, and in this order: the schema has to be something the old
# code recognises before the old code starts serving requests against it.
if [ -n "${REVISION}" ] && [ "${REVISION}" != "unknown" ]; then
  echo "walking the schema back to ${REVISION}"
  $COMPOSE run --rm api .venv/bin/alembic downgrade "$REVISION"
fi

if $RESTORE_DB; then
  DUMP="$(ls -1t backups/pre-deploy-*.sql.gz 2>/dev/null | head -n 1 || true)"
  if [ -z "$DUMP" ]; then
    echo "no pre-deploy dump to restore from" >&2
    exit 1
  fi
  echo "restoring ${DUMP}"
  gunzip -c "$DUMP" | $COMPOSE exec -T postgres psql -U postgres -q footbola
fi

$COMPOSE up -d --remove-orphans
$COMPOSE run --rm admin-dist

# Permissions follow the code back: the older application knows an older set
# of keys, and leaving the newer ones granted is a role holding permissions
# for routes that no longer exist.
$COMPOSE run --rm api .venv/bin/python -m app.platform.seeds.reference

sleep 8
DOMAIN="$(grep -E '^PLATFORM_DOMAIN=' .env | cut -d= -f2)"
curl -fsS --max-time 10 "https://api.${DOMAIN}/health" >/dev/null
curl -fsS --max-time 10 "https://${DOMAIN}/" >/dev/null

printf '%s %s %s %s\n' "$(date -Is)" "$TAG" "$REVISION" "${COMMIT:-unknown}" >> "$LOG"
echo
echo "rolled back to ${TAG}. The tree is detached at ${COMMIT:-$TAG};"
echo "the next deploy from main will move it forward again."
