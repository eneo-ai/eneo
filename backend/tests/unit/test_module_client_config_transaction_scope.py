from collections.abc import Iterator
from typing import cast

from fastapi.dependencies.models import Dependant

from eneo.database.database import get_session_with_transaction
from tests.unit.api_key_test_utils import runtime_router_routes


def _walk_dependencies(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for child in dependant.dependencies:
        yield from _walk_dependencies(child)


def test_module_client_config_patch_commits_before_response() -> None:
    """The sysadmin PATCH mutates tenants_modules; its transaction must close
    before the response is sent so a 200 can never precede a failed commit."""
    path = "/modules/{tenant_id}/{module_id}/client-config/"
    matches = [
        route
        for route in runtime_router_routes()
        if route.path == path and "PATCH" in (route.methods or set())
    ]
    assert len(matches) == 1, f"Expected one PATCH {path} route, got {len(matches)}"

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
