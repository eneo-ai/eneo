"""The space PATCH commits before its response is sent.

A change of the space's time writes a required audit row in the same
transaction. With FastAPI's default request scope that transaction closes
after the 200 has gone out, so a failed commit would follow a success. This
pins the function-scoped transaction on the route.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from eneo.database.database import get_session_with_transaction
from eneo.spaces.api import space_router


def _walk(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for child in dependant.dependencies:
        yield from _walk(child)


def test_space_patch_commits_before_its_response() -> None:
    (route,) = [
        route
        for route in space_router.router.routes
        if isinstance(route, APIRoute)
        and route.path == "/{id}/"
        and "PATCH" in route.methods
    ]
    scopes = [
        dependant.scope
        for dependant in _walk(route.dependant)
        if dependant.call is get_session_with_transaction
    ]
    assert scopes == ["function"]
