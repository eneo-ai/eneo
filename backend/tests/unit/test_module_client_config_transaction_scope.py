from collections.abc import Iterator
from typing import cast

import pytest
from fastapi.dependencies.models import Dependant

from eneo.database.database import get_session_with_transaction
from tests.unit.api_key_test_utils import runtime_router_routes


def _walk_dependencies(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for child in dependant.dependencies:
        yield from _walk_dependencies(child)


MODULE_AUTH_TRANSACTION_ROUTES = [
    ("POST", "/modules/"),
    ("POST", "/modules/{tenant_id}/"),
    ("PUT", "/modules/{tenant_id}/{module_id}/"),
    ("DELETE", "/modules/{tenant_id}/{module_id}/"),
    ("PATCH", "/modules/{tenant_id}/{module_id}/client-config/"),
    ("POST", "/module-auth/tickets/"),
    ("POST", "/module-auth/token/"),
]


@pytest.mark.parametrize(("method", "path"), MODULE_AUTH_TRANSACTION_ROUTES)
def test_module_auth_transactions_commit_before_response(
    method: str, path: str
) -> None:
    """Auth handoff responses must not precede transaction teardown."""
    matches = [
        route
        for route in runtime_router_routes()
        if route.path == path and method in (route.methods or set())
    ]
    assert len(matches) == 1, f"Expected one {method} {path} route, got {len(matches)}"

    route_dependant = cast(Dependant, matches[0].dependant)
    container_dependencies = [
        dependency
        for dependency in route_dependant.dependencies
        if dependency.name == "container"
    ]
    assert len(container_dependencies) == 1

    transaction_dependencies = [
        dependency
        for dependency in _walk_dependencies(container_dependencies[0])
        if dependency.call is get_session_with_transaction
    ]

    assert len(transaction_dependencies) == 1
    assert transaction_dependencies[0].scope == "function"
