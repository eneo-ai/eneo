from collections.abc import Iterator
from inspect import getsource
from typing import cast

import pytest
from fastapi.dependencies.models import Dependant

from eneo.database.database import get_session, get_session_with_transaction
from tests.unit.api_key_test_utils import runtime_router_routes

DIRECT_API_KEY_MUTATION_ROUTES = [
    ("POST", "/api-keys"),
    ("PATCH", "/api-keys/{id}"),
    ("DELETE", "/api-keys/{id}"),
    ("POST", "/api-keys/{id}/revoke"),
    ("POST", "/api-keys/{id}/rotate"),
    ("POST", "/api-keys/{id}/extend"),
    ("POST", "/api-keys/{id}/purge"),
    ("POST", "/api-keys/{id}/suspend"),
    ("POST", "/api-keys/{id}/reactivate"),
    ("PATCH", "/admin/api-keys/{id}"),
    ("DELETE", "/admin/api-keys/{id}"),
    ("POST", "/admin/api-keys/{id}/revoke"),
    ("POST", "/admin/api-keys/{id}/rotate"),
    ("POST", "/admin/api-keys/{id}/extend"),
    ("POST", "/admin/api-keys/{id}/purge"),
    ("POST", "/admin/api-keys/{id}/suspend"),
    ("POST", "/admin/api-keys/{id}/reactivate"),
]

INDIRECT_API_KEY_REVOCATION_ROUTES = [
    ("DELETE", "/admin/users/{username}"),
    ("POST", "/admin/users/{username}/deactivate"),
    ("DELETE", "/apps/{id}/"),
    ("DELETE", "/assistants/{id}/"),
    ("DELETE", "/spaces/{id}/"),
    ("DELETE", "/spaces/{id}/members/{user_id}/"),
    ("DELETE", "/admin/help-assistants/roles/{kind}/"),
]

API_KEY_MUTATION_ROUTES = [
    *DIRECT_API_KEY_MUTATION_ROUTES,
    *INDIRECT_API_KEY_REVOCATION_ROUTES,
]


def _walk_dependencies(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for child in dependant.dependencies:
        yield from _walk_dependencies(child)


@pytest.mark.parametrize(("method", "path"), API_KEY_MUTATION_ROUTES)
def test_api_key_mutations_commit_before_response(method: str, path: str) -> None:
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

    function_transaction_dependencies = [
        dependency
        for dependency in _walk_dependencies(container_dependencies[0])
        if dependency.call is get_session_with_transaction
    ]
    if function_transaction_dependencies:
        assert len(function_transaction_dependencies) == 1
        assert function_transaction_dependencies[0].scope == "function"
        return

    explicit_session_dependencies = [
        dependency
        for dependency in _walk_dependencies(container_dependencies[0])
        if dependency.call is get_session
    ]
    assert len(explicit_session_dependencies) == 1
    assert "async with cast(AsyncSession, container.session()).begin():" in getsource(
        matches[0].endpoint
    )
