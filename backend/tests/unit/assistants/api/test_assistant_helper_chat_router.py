"""The assistant helper chat's routes: a signed-in session only, an opening
a service key cannot make, and a change request that says what it changes."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from eneo.assistants.api.assistant_helper_chat_router import (
    AssistantHelperChatUpdateRequest,
    router,
)
from eneo.authentication.auth_dependencies import require_user_for_creation
from eneo.authentication.endpoint_access import Authentication, access_for


def _routes() -> list[APIRoute]:
    return [route for route in router.routes if isinstance(route, APIRoute)]


def test_every_route_takes_a_signed_in_session_only():
    routes = _routes()

    assert {(next(iter(route.methods)), route.path) for route in routes} == {
        ("POST", "/{id}/helper-chat/"),
        ("PATCH", "/{id}/helper-chat/{session_id}/"),
        ("POST", "/{id}/helper-chat/{session_id}/conversations/"),
        ("GET", "/{id}/helper-chat/conversations/"),
        ("GET", "/{id}/helper-chat/availability"),
    }
    for route in routes:
        policy = access_for(route.endpoint)
        assert policy is not None
        assert policy.authentication is Authentication.SESSION


def test_opening_the_chat_refuses_a_service_key_as_any_creation_does():
    opening = next(
        route
        for route in _routes()
        if route.path == "/{id}/helper-chat/" and route.methods == {"POST"}
    )

    calls = {dependency.call for dependency in opening.dependant.dependencies}
    assert require_user_for_creation in calls
    assert "fresh_start" in {param.name for param in opening.dependant.query_params}


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="nothing"),
        pytest.param({"editing": False}, id="a-mode"),
        pytest.param({"expected_revision": 3}, id="a-revision"),
    ],
)
def test_a_change_request_that_says_nothing_it_may_change_is_refused(body):
    with pytest.raises(ValidationError):
        AssistantHelperChatUpdateRequest.model_validate(body)


def test_a_null_model_is_sent_and_an_omitted_one_is_not():
    returning = AssistantHelperChatUpdateRequest.model_validate(
        {"completion_model_id": None}
    )
    choosing = AssistantHelperChatUpdateRequest.model_validate(
        {"completion_model_id": str(uuid4())}
    )

    assert returning.model_fields_set == {"completion_model_id"}
    assert "reasoning_effort" not in choosing.model_fields_set
