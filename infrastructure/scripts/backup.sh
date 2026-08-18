#!/usr/bin/env bash
# A database dump you can actually restore from.
#
# The difference between this and `pg_dump > file.gz` is that this one is
# verified before it is trusted and comes with a note saying what the system
# looked like when it was taken. A backup discovered to be truncated at the
# moment you need it is not a backup, and a dump with no record of which image
# tag and which migration it belongs to leaves you guessing during the one
# hour you cannot afford to guess.
#
#   ./infrastructure/scripts/backup.sh [label]
#
# `label` defaults to `manual`; the deploy passes `pre-deploy`, cron passes
# `nightly`. Retention is per label, so a run of deploys cannot age out the
# nightly copies.
set -euo pipefail

cd "$(dirname "$0")/../.."

COMPOSE="docker compose -f docker-compose.prod.yml"
LABEL="${1:-manual}"
KEEP="${BACKUP_KEEP:-10}"
STAMP="$(date +%F-%H%M%S)"
DIR="backups"
TARGET="${DIR}/${LABEL}-${STAMP}.sql.gz"

mkdir -p "$DIR"

if ! $COMPOSE exec -T postgres pg_isready -U postgres -d footbola >/dev/null 2>&1; then
  echo "postgres is not running — nothing to back up"
  exit 0
fi

# Written to a temporary name and only moved into place once it has been
# checked. A half-written file that carries the real name is worse than no
# file: the next run's retention will happily keep it and delete a good one.
TMP="${TARGET}.partial"
trap 'rm -f "$TMP"' EXIT

# `pipefail` is what makes a pg_dump failure a script failure rather than a
# zero-byte archive that gzip reports as a success.
$COMPOSE exec -T postgres pg_dump -U postgres --clean --if-exists footbola \
  | gzip > "$TMP"

gunzip -t "$TMP"

SIZE="$(wc -c < "$TMP" | tr -d ' ')"
if [ "$SIZE" -lt 20000 ]; then
  echo "dump is only ${SIZE} bytes — refusing to keep it" >&2
  exit 1
fi

# What this dump belongs to. Read *before* the move so a failure here does not
# leave an unlabelled archive behind.
REVISION="$($COMPOSE run --rm -T api .venv/bin/alembic current 2>/dev/null \
  | grep -oE '^[0-9a-f]{12}' | head -1 || true)"
COMMIT="$(git rev-parse HEAD 2>/dev/null || echo unknown)"

mv "$TMP" "$TARGET"
trap - EXIT

cat > "${TARGET%.sql.gz}.json" <<JSON
{
  "label": "${LABEL}",
  "taken_at": "$(date -Is)",
  "commit": "${COMMIT}",
  "image_tag": "${IMAGE_TAG:-unknown}",
  "alembic_revision": "${REVISION:-unknown}",
  "bytes": ${SIZE}
}
JSON

# Per label, newest first, drop everything past the keep count — and take the
# manifest with it, so the directory never accumulates orphaned notes.
ls -1t "${DIR}/${LABEL}-"*.sql.gz 2>/dev/null | tail -n "+$((KEEP + 1))" | while read -r old; do
  rm -f "$old" "${old%.sql.gz}.json"
  echo "pruned $(basename "$old")"
done

echo "backed up to ${TARGET} (${SIZE} bytes, revision ${REVISION:-unknown})"
