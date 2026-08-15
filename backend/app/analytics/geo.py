"""Where a visit came from, without keeping where it came from.

The address is looked up and discarded in the same breath: what is stored is a
country code and a city name, which describe a place rather than a person. That
is the whole reason this is done at collection time and not later — keeping
addresses so geography could be computed tomorrow would mean keeping addresses.

The database is optional and the module says so out loud. A club that never
installs it gets every other number exactly as before, and geography simply
does not appear. An analytics page that fails because a 60MB file is missing
would be a worse product than one that quietly counts less.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)

_reader: Any | None = None
_tried = False
_lock = threading.Lock()


def _load() -> Any | None:
    """Open the database once, and never try twice if it is not there."""
    global _reader, _tried

    with _lock:
        if _tried:
            return _reader
        _tried = True

        path = Path(settings.geoip_database_path)
        if not path.exists():
            log.info("geoip_absent", path=str(path))
            return None

        try:
            import geoip2.database

            _reader = geoip2.database.Reader(str(path))
            log.info("geoip_loaded", path=str(path))
        except Exception as exc:  # ImportError, invalid file, permissions
            # Never fatal. The alternative is a club's website measuring
            # nothing because a data file was corrupted.
            log.warning("geoip_unavailable", error=str(exc))
            _reader = None

        return _reader


def locate(ip: str) -> tuple[str | None, str | None]:
    """`(country_code, city)` for an address, or `(None, None)`.

    Private and unroutable addresses resolve to nothing rather than to an
    error: in development every visitor is on a Docker network, and that
    should read as "unknown", not as a broken feature.
    """
    reader = _load()
    if reader is None or not ip or ip == "unknown":
        return None, None

    try:
        found = reader.city(ip)
    except Exception:
        # `AddressNotFoundError` for private ranges, `ValueError` for anything
        # that is not an address at all. Both mean the same thing here.
        return None, None

    country = found.country.iso_code
    # English rather than the visitor's language: the dashboard is read by one
    # club, and "München" and "Munich" as separate rows would be a bug.
    city = found.city.names.get("en") if found.city else None
    return (country[:2] if country else None), (city[:80] if city else None)
