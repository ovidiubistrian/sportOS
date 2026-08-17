#!/usr/bin/env bash
# First-run bootstrap for the development environment. Idempotent: a second run
# detects existing state and skips. Reset with `docker compose down -v`.
set -euo pipefail

echo "▸ waiting for postgres"
until python -c "
import asyncio, asyncpg, os, sys, urllib.parse as u
url = u.urlparse(os.environ['DATABASE_URL'].replace('+asyncpg', ''))
async def main():
    conn = await asyncpg.connect(user=url.username, password=url.password,
                                 host=url.hostname, port=url.port or 5432,
                                 database=url.path.lstrip('/'))
    await conn.close()
asyncio.run(main())
" 2>/dev/null; do sleep 1; done

echo "▸ applying migrations"
alembic upgrade head

echo "▸ seeding reference data (permissions, roles)"
python -m app.platform.seeds.reference

echo "▸ seeding plans and features"
python -m app.platform.seeds.plans
python -m app.platform.seeds.competitions

if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
  echo "▸ seeding demo tenants"
  python -m app.platform.seeds.demo

  echo "▸ seeding demonstration stadium and ticketing"
  python -m app.platform.seeds.ticketing fc-example
fi

cat <<'BANNER'

  TeamSport360 — development environment ready

    Admin           http://admin.footbola.localhost
    API docs        http://api.footbola.localhost/docs
    Keycloak        http://auth.footbola.localhost   (admin / see .env)
    Mail            http://mail.footbola.localhost
    Object storage  http://files.footbola.localhost
    Traefik         http://localhost:8090

  Sign in with any of these (password: password)

    owner@fcexample.test        Tenant Owner        — everything in FC Example
    academy@fcexample.test      Academy Director    — club-wide academy access
    coach.u15@fcexample.test    Coach, U15 only     — should see 22 players
    owner@northern.test         Tenant Owner        — a different tenant
    platform@footbola.test      Platform Super Admin

BANNER
