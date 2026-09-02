from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from eneo.authentication.api_key_capacity_router import (
    ApiKeyCapacityPublic,
    get_api_key_capacity,
)
from eneo.authentication.api_key_rate_limiter import ApiKeyRateCapacity
from eneo.authentication.api_key_resolver import ApiKeyValidationError
from eneo.authentication.auth_models import ApiKeyPermission


def _container(*, user: object, snapshot: object) -> MagicMock:
    limiter = MagicMock()
    limiter.snapshot = AsyncMock()
    if isinstance(snapshot, Exception):
        limiter.snapshot.side_effect = snapshot
    else:
        limiter.snapshot.return_value = snapshot
    container = MagicMock()
    container.user.return_value = user
    container.api_key_rate_limiter.return_value = limiter
    return container


@pytest.mark.asyncio
async def test_capacity_describes_the_calling_key() -> None:
    key = SimpleNamespace(id=uuid4(), permission=ApiKeyPermission.ADMIN)
    space_id = uuid4()
    snapshot = ApiKeyRateCapacity(
        key_id=key.id,
        scope_type="space",
        scope_id=space_id,
        limit_source="explicit",
        window_seconds=3600,
        fail_open=False,
        limit=20000,
        current_count=412,
        remaining=19588,
    )
    container = _container(user=SimpleNamespace(active_api_key=key), snapshot=snapshot)

    response = await get_api_key_capacity(container=container)

    assert response.key_id == key.id
    assert response.scope_id == space_id
    assert response.permission == ApiKeyPermission.ADMIN
    assert (response.limit, response.current_count, response.remaining) == (
        20000,
        412,
        19588,
    )
    container.api_key_rate_limiter.return_value.snapshot.assert_awaited_once_with(key)


@pytest.mark.asyncio
async def test_capacity_rejects_a_caller_without_an_api_key() -> None:
    # A session-authenticated user has no key, so there is no budget to describe.
    container = _container(user=SimpleNamespace(active_api_key=None), snapshot=None)

    with pytest.raises(HTTPException) as exc:
        await get_api_key_capacity(container=container)

    assert exc.value.status_code == 403
    container.api_key_rate_limiter.return_value.snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_capacity_surfaces_an_unavailable_rate_limit_store() -> None:
    container = _container(
        user=SimpleNamespace(active_api_key=SimpleNamespace(id=uuid4())),
        snapshot=ApiKeyValidationError(
            status_code=503,
            code="rate_limit_unavailable",
            message="Rate limiting is temporarily unavailable.",
        ),
    )

    with pytest.raises(HTTPException) as exc:
        await get_api_key_capacity(container=container)

    assert exc.value.status_code == 503


def test_unlimited_capacity_carries_no_counter_fields() -> None:
    payload = ApiKeyCapacityPublic(
        key_id=uuid4(),
        scope_type="space",
        scope_id=uuid4(),
        permission=ApiKeyPermission.WRITE,
        limit_source="unlimited",
        window_seconds=3600,
        fail_open=False,
        limit=None,
        current_count=None,
        remaining=None,
    )

    assert (payload.limit, payload.current_count, payload.remaining) == (
        None,
        None,
        None,
    )


def test_unlimited_capacity_rejects_a_counter() -> None:
    # `limit_source` is the discriminator; a limit alongside "unlimited" would
    # let a client believe a budget applies when none is enforced.
    with pytest.raises(ValueError):
        ApiKeyCapacityPublic(
            key_id=uuid4(),
            scope_type="space",
            scope_id=uuid4(),
            permission=ApiKeyPermission.WRITE,
            limit_source="unlimited",
            window_seconds=3600,
            fail_open=False,
            limit=5000,
            current_count=None,
            remaining=None,
        )


def test_limited_capacity_requires_every_counter_field() -> None:
    with pytest.raises(ValueError):
        ApiKeyCapacityPublic(
            key_id=uuid4(),
            scope_type="space",
            scope_id=uuid4(),
            permission=ApiKeyPermission.WRITE,
            limit_source="scope_default",
            window_seconds=3600,
            fail_open=False,
            limit=5000,
            current_count=None,
            remaining=None,
        )


def test_the_capacity_route_is_not_behind_the_admin_scoped_api_key_router() -> None:
    """The first design put this route inside `api_key_router`, where the whole
    router carries an admin scope check and a space-scoped measurement key can
    never reach it. This is that regression's guard: the route must resolve at
    its own path with no inherited scope guard, while its admin-router
    neighbours keep theirs.
    """
    from fastapi.routing import APIRoute
    from starlette.routing import compile_path

    from eneo.server.main import get_application
    from tests.unit.api_key_test_utils import flatten_routes

    routes = [
        route
        for route in flatten_routes(list(get_application().routes))
        if isinstance(route.route, APIRoute)
    ]
    by_path = {route.path: route for route in routes}

    capacity = by_path["/api/v1/api-key-capacity/"]
    assert list(capacity.dependencies or []) == []
    assert by_path["/api/v1/api-keys/policy-constraints"].dependencies

    requested = "/api/v1/api-key-capacity/"
    selected = [
        route.route.operation_id
        for route in routes
        if "GET" in (route.route.methods or set())
        and compile_path(route.path)[0].match(requested)
    ]
    assert selected and selected[0] == "get_api_key_capacity"
