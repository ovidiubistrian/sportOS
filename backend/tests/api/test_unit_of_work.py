"""When the request's work is committed, relative to the client seeing the reply.

This pins the invariant behind a bug that hid for a long time because it only
showed on a slow machine. A dependency with `yield` runs its exit code *after*
Starlette has handed the response to the client, so committing there let a
caller read back its own write and not find it — a `POST` returned 201, and a
read arriving a millisecond later saw nothing. The suite caught it as one
intermittent failure in CI and never once locally.

Over a real socket, deliberately. The whole bug is that a client can be reading
the response while the server still has work to do, and an in-process transport
cannot express that: it returns only once the application is completely
finished, so the ordering would hold there whether or not the fix exists.

The session is a stub rather than a database: what is asserted is ordering, and
a real commit is too fast to order reliably against anything.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
import uvicorn
from fastapi import Depends, FastAPI
from starlette.requests import Request

from app.api.middleware import UnitOfWorkMiddleware, enlist

pytestmark = pytest.mark.concurrency

# Long enough to order against a network round trip on a loaded CI runner, short
# enough that three tests do not slow the suite down.
COMMIT_COST = 0.25


class SlowSession:
    """Stands in for `AsyncSession`, with a commit slow enough to observe."""

    def __init__(self, log: list[str]) -> None:
        self.log = log

    async def commit(self) -> None:
        await asyncio.sleep(COMMIT_COST)
        self.log.append("committed")


async def drive(app: FastAPI, log: list[str], method: str = "post") -> httpx.Response:
    """Serve `app` on a real port, make one request, note when it landed."""
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]

        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
            response = await client.request(method, "/work")
        log.append("client_got_response")
        return response
    finally:
        server.should_exit = True
        await task


def build(log: list[str], status_code: int) -> FastAPI:
    app = FastAPI()
    app.add_middleware(UnitOfWorkMiddleware)

    @app.post("/work", status_code=status_code)
    async def write(request: Request) -> dict[str, str]:
        enlist(request, SlowSession(log))  # type: ignore[arg-type]
        return {"ok": "yes"}

    return app


async def test_the_work_is_committed_before_the_client_can_see_the_reply() -> None:
    """The whole point: a caller cannot outrun its own write.

    If this reverses, every read-after-write in the API becomes a race — and an
    intermittent one, which is the expensive kind.
    """
    log: list[str] = []
    response = await drive(build(log, 201), log)

    assert response.status_code == 201
    assert log == ["committed", "client_got_response"]


async def test_committing_in_a_dependency_exit_would_not_be_enough() -> None:
    """Why the middleware exists at all, rather than a tidier `yield`.

    This is the shape the code had when the bug was live. It is asserted here
    so that the day FastAPI closes the window itself, this test fails and says
    the middleware has become redundant — rather than it sitting there forever
    because nobody could remember what it was for.
    """
    log: list[str] = []
    app = FastAPI()

    async def unit_of_work() -> AsyncIterator[SlowSession]:
        session = SlowSession(log)
        yield session
        await session.commit()

    @app.post("/work", status_code=201)
    async def write(_: SlowSession = Depends(unit_of_work)) -> dict[str, str]:
        return {"ok": "yes"}

    await drive(app, log)

    assert log[0] == "client_got_response", (
        "FastAPI now runs dependency exit code before the response is sent; "
        "UnitOfWorkMiddleware may no longer be needed"
    )


async def test_a_refused_request_is_not_committed_here() -> None:
    """A 4xx is left to the session's own exit code, exactly as before.

    Not the same as discarding it: a route that deliberately returns a 4xx
    after writing something still keeps that write. This middleware only moves
    the successful commit earlier; it never decides what persists.
    """
    log: list[str] = []
    response = await drive(build(log, 422), log)

    assert response.status_code == 422
    assert log == ["client_got_response"]


async def test_a_request_that_touched_no_session_is_left_alone() -> None:
    """Reads, health checks and 404s enlist nothing and must cost nothing."""
    app = FastAPI()
    app.add_middleware(UnitOfWorkMiddleware)

    @app.get("/work")
    async def read() -> dict[str, str]:
        return {"ok": "yes"}

    log: list[str] = []
    assert (await drive(app, log, method="get")).status_code == 200
    assert log == ["client_got_response"]
