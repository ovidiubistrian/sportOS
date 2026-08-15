"""Route enumeration for the generated test suites.

Derived from the OpenAPI schema rather than by walking `app.routes`: recent
FastAPI resolves included routers lazily, so the route objects are wrappers
without a path until the schema is built. The schema is also the better source
of truth — it is exactly the surface we publish, so a route that is reachable
but undocumented is a bug the suite should surface anyway.
"""

from __future__ import annotations

from functools import cache

from app.main import app

_IGNORED_METHODS = {"head", "options"}


@cache
def api_routes() -> tuple[tuple[str, str], ...]:
    """Every documented (METHOD, path) pair under the versioned API."""
    schema = app.openapi()
    found: list[tuple[str, str]] = []
    for path, operations in schema.get("paths", {}).items():
        if not path.startswith("/api/v1/"):
            continue
        for method in operations:
            if method.lower() in _IGNORED_METHODS:
                continue
            found.append((method.upper(), path))
    return tuple(sorted(found))


@cache
def detail_routes() -> tuple[tuple[str, str], ...]:
    """GET routes addressing a single object by one path parameter."""
    return tuple(
        (method, path)
        for method, path in api_routes()
        if method == "GET" and path.count("{") == 1
    )
