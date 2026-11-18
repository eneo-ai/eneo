"""The assistant helper chat's routes: a signed-in session only, and a
change request that says what it changes."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from eneo.assistants.api.assistant_helper_chat_router import (
    AssistantHelperChatUpdateRequest,
    router,
)
from eneo.authentication.endpoint_access import Authentication, access_for


def test_every_route_takes_a_signed_in_session_only():
    routes = [route for route in router.routes if isinstance(route, APIRoute)]

    assert {(next(iter(route.methods)), route.path) for route in routes} == {
        ("POST", "/{id}/helper-chat/"),
        ("PATCH", "/{id}/helper-chat/{session_id}/"),
        ("POST", "/{id}/helper-chat/{session_id}/conversations/"),
        ("GET", "/{id}/helper-chat/availability"),
    }
    for route in routes:
        policy = access_for(route.endpoint)
        assert policy is not None
        assert policy.authentication is Authentication.SESSION


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="nothing"),
        pytest.param({"editing": None}, id="editing-null"),
        pytest.param({"expected_revision": 3, "editing": True}, id="a-revision"),
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
        {"completion_model_id": str(uuid4()), "editing": True}
    )

    assert returning.model_fields_set == {"completion_model_id"}
    assert "reasoning_effort" not in choosing.model_fields_set
    assert choosing.editing is True
