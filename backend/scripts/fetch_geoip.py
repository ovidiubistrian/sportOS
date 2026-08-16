"""Fetch the GeoIP city database.

DB-IP's City Lite is used because it needs no account and no licence key — a
club deploying this should not have to register with MaxMind before its
analytics can say "Romania". The data is CC-BY 4.0, refreshed monthly, and the
attribution belongs in the club's own privacy page if it publishes one.

Run it whenever: the module reads the file at startup and does without it
cleanly, so downloading is never a deployment step that can fail the deploy.

    docker compose exec api .venv/bin/python scripts/fetch_geoip.py
"""

from __future__ import annotations

import gzip
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

# See the note in sync_domains.py: `app` is importable only from the project
# root, and running a file in `scripts/` does not put the root on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings


def main() -> int:
    target = Path(settings.geoip_database_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    # This month's file, falling back to last month's — the new one appears a
    # day or two into the month, and a first-of-the-month deploy should not
    # come back empty-handed.
    now = datetime.now(UTC)
    months = [now.strftime("%Y-%m")]
    previous = now.replace(day=1) - __import__("datetime").timedelta(days=1)
    months.append(previous.strftime("%Y-%m"))

    for month in months:
        url = settings.geoip_download_url.format(month=month)
        print(f"trying {url}")
        try:
            with httpx.stream("GET", url, timeout=120, follow_redirects=True) as response:
                if response.status_code != 200:
                    print(f"  {response.status_code}, next")
                    continue

                with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as raw:
                    for chunk in response.iter_bytes(1 << 20):
                        raw.write(chunk)
                    downloaded = Path(raw.name)
        except httpx.HTTPError as exc:
            print(f"  failed: {exc}")
            continue

        # Unpacked beside the target and moved into place, so a half-written
        # file is never what the application opens.
        staged = target.with_suffix(".staging")
        with gzip.open(downloaded, "rb") as source, staged.open("wb") as out:
            shutil.copyfileobj(source, out)
        downloaded.unlink(missing_ok=True)
        staged.replace(target)

        size = target.stat().st_size / (1024 * 1024)
        print(f"wrote {target} ({size:.0f} MB)")
        return 0

    print("no database could be downloaded; analytics will simply omit geography")
    return 1


if __name__ == "__main__":
    sys.exit(main())
