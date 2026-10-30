"""Request gates run inside the route's one user authentication: after the user
is known and set up, before upload admission, in the same transaction."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from starlette.requests import Request

from eneo.main.exceptions import NotFoundException
from eneo.server.dependencies import container as container_module
from eneo.server.dependencies.container import add_request_gate, get_container


@pytest.fixture
def events(monkeypatch) -> list[str]:
    events: list[str] = []

    async def setup_user(*, container, user):
        events.append("setup_user")

    async def load_container_upload_admission(container):
        events.append("upload_admission")

    async def refresh_object_store_configuration():
        pass

    monkeypatch.setattr(container_module, "setup_user", setup_user)
    monkeypatch.setattr(
        container_module,
        "load_container_upload_admission",
        load_container_upload_admission,
    )
    monkeypatch.setattr(
        container_module.object_content_runtime,
        "refresh_object_store_configuration",
        refresh_object_store_configuration,
    )
    monkeypatch.setattr(
        container_module,
        "override_user",
        lambda *, container, user: events.append("override_user"),
    )
    return events


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


def _container(events: list[str], user):
    @asynccontextmanager
    async def begin():
        events.append("begin")
        yield
        events.append("commit")

    async def authenticate(**_):
        events.append("authenticate")
        return user

    session = SimpleNamespace(in_transaction=lambda: False, begin=begin)
    user_service = SimpleNamespace(authenticate=AsyncMock(side_effect=authenticate))
    return SimpleNamespace(session=lambda: session, user_service=lambda: user_service)


async def _authenticate(request: Request, container) -> object:
    dependency = get_container(
        with_user=True, with_transaction=False, with_upload_admission=True
    )
    return await dependency(
        request=request, token="token", api_key=None, container=container
    )


def _user(*, is_active: bool = False):
    return SimpleNamespace(id=uuid4(), tenant_id=uuid4(), is_active=is_active)


async def test_a_gate_runs_after_setup_and_before_upload_admission(events):
    user = _user()
    container = _container(events, user)
    request = _request()
    seen = []

    async def gate(gate_container, gate_user):
        events.append("gate")
        seen.append((gate_container, gate_user))

    add_request_gate(request, gate)
    assert await _authenticate(request, container) is container

    assert events == [
        "begin",
        "authenticate",
        "setup_user",
        "gate",
        "upload_admission",
        "commit",
        "override_user",
    ]
    assert seen == [(container, user)]
    container.user_service().authenticate.assert_awaited_once()


async def test_a_refusing_gate_ends_the_authentication(events):
    container = _container(events, _user(is_active=True))
    request = _request()

    async def gate(_container, _user):
        raise NotFoundException()

    add_request_gate(request, gate)
    with pytest.raises(NotFoundException):
        await _authenticate(request, container)

    assert "upload_admission" not in events
    assert "override_user" not in events
    assert request.state._post_auth_gates == ()


async def test_no_gate_leaves_the_authentication_unchanged(events):
    container = _container(events, _user(is_active=True))

    assert await _authenticate(_request(), container) is container

    assert events == [
        "begin",
        "authenticate",
        "upload_admission",
        "commit",
        "override_user",
    ]


async def test_a_gate_added_twice_runs_once_and_is_drained(events):
    container = _container(events, _user(is_active=True))
    request = _request()

    async def gate(_container, _user):
        events.append("gate")

    add_request_gate(request, gate)
    add_request_gate(request, gate)
    await _authenticate(request, container)
    await _authenticate(request, container)

    assert events.count("gate") == 1
    assert request.state._post_auth_gates == ()
