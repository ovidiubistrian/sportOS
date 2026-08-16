"""Register every existing club domain with Keycloak.

The repair for the case the docstring in `domain_service` warns about: a domain
that was created while the identity provider was unreachable, or one that
predates this code entirely. Idempotent, so running it twice costs one wasted
request per domain.

    docker compose exec api .venv/bin/python scripts/sync_domains.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# `python scripts/sync_domains.py` puts `scripts/` on the path, not the project
# root, and the project is deliberately not installed as a package — so `app`
# is importable only from the working directory. Fixed here rather than by
# demanding a PYTHONPATH from every caller, of which there are now three.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.db import platform_session
from app.core.model_registry import *  # noqa: F403
from app.identity.keycloak import get_admin
from app.tenants.models import ClubDomain


async def main() -> int:
    async with platform_session(reason="register club domains with Keycloak") as session:
        hostnames = sorted(
            {
                str(row)
                for row in await session.scalars(
                    select(ClubDomain.hostname).where(
                        ClubDomain.verification_status == "VERIFIED"
                    )
                )
            }
        )

    admin = get_admin()
    failures = 0
    for hostname in hostnames:
        ok = await admin.allow_redirect(hostname)
        print(f"{'ok  ' if ok else 'FAIL'} {hostname}")
        failures += 0 if ok else 1

    print(f"\n{len(hostnames) - failures}/{len(hostnames)} registered")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
