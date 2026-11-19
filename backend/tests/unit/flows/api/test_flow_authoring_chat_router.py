"""The flow chat's routes: a signed-in session only, and an opening a
service key cannot make, refused in the route's one authentication."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute

from eneo.authentication.auth_models import ApiKeyOwnership
from eneo.authentication.endpoint_access import Authentication, access_for
from eneo.flows.api import flow_authoring_chat_router
from eneo.flows.api.flow_authoring_chat_router import router


def _routes() -> list[APIRoute]:
    return [route for route in router.routes if isinstance(route, APIRoute)]


def test_every_route_takes_a_signed_in_session_only():
    routes = _routes()

    assert {(next(iter(route.methods)), route.path) for route in routes} == {
        ("POST", "/{id}/authoring-chat/"),
        ("PATCH", "/{id}/authoring-chat/{session_id}/"),
        ("POST", "/{id}/authoring-chat/{session_id}/conversations/"),
        ("GET", "/{id}/authoring-chat/conversations/"),
    }
    for route in routes:
        policy = access_for(route.endpoint)
        assert policy is not None
        assert policy.authentication is Authentication.SESSION


def test_opening_the_chat_runs_the_creation_guard_on_the_routes_own_user():
    opening = next(
        route
        for route in _routes()
        if route.path == "/{id}/authoring-chat/" and route.methods == {"POST"}
    )

    calls = {dependency.call for dependency in opening.dependant.dependencies}
    guard = flow_authoring_chat_router._require_user_for_chat  # pyright: ignore[reportPrivateUsage]
    assert guard in calls
    assert "fresh_start" in {param.name for param in opening.dependant.query_params}


def _container(user: object) -> MagicMock:
    container = MagicMock()
    container.user.return_value = user
    return container


async def test_a_service_key_is_refused_an_opening_and_a_person_is_not():
    guard = flow_authoring_chat_router._require_user_for_chat  # pyright: ignore[reportPrivateUsage]
    service = SimpleNamespace(
        active_api_key=SimpleNamespace(ownership=ApiKeyOwnership.SERVICE)
    )

    with pytest.raises(HTTPException) as refused:
        await guard(_container(service))
    assert refused.value.status_code == 403
    assert refused.value.detail["code"] == "service_key_cannot_create_resources"

    await guard(_container(SimpleNamespace(active_api_key=None)))
