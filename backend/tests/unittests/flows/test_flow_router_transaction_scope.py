"""Flow mutations commit before their response is sent.

A client that creates a flow or a flow assistant and immediately addresses it
must find it. With FastAPI's default request scope the transaction closes
after the response body has gone out, so the follow-up request can race the
commit (3 of 42 harness seedings on 2026-09-15 got 404/403 within 20 ms of a
201). This pins that every mutating route of the two flow authoring routers
either takes the function-scoped transaction of the container dependency or
opens its own with `authoring_transaction`, which commits inside the route.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from pytest import mark

from eneo.database.database import get_session_with_transaction
from eneo.flows.api import flow_assistant_router, flow_authoring_router

_MUTATING_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


def _walk(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for child in dependant.dependencies:
        yield from _walk(child)


def _transaction_scopes(route: APIRoute) -> list[str | None]:
    return [
        dependant.scope
        for dependant in _walk(route.dependant)
        if dependant.call is get_session_with_transaction
    ]


@mark.parametrize("router_module", [flow_authoring_router, flow_assistant_router])
def test_every_flow_mutation_commits_before_its_response(router_module) -> None:
    mutating = [
        route
        for route in router_module.router.routes
        if isinstance(route, APIRoute) and route.methods & _MUTATING_METHODS
    ]
    assert mutating, "the router has no mutating routes to pin"
    for route in mutating:
        scopes = _transaction_scopes(route)
        if not scopes:
            assert "authoring_transaction(container)" in inspect.getsource(
                route.endpoint
            ), f"{route.name} has no transaction that commits before its response"
            continue
        assert scopes == ["function"] * len(scopes), (
            f"{route.name} commits after its response (scopes {scopes})"
        )
