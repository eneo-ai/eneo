from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import AsyncMock

import pytest
from dependency_injector import providers
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.responses import StreamingResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from eneo.main.container.container import Container
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot
from eneo.server.dependencies import container as container_dependency


def _record_response_start(app: ASGIApp, events: list[str]) -> ASGIApp:
    async def _recording_app(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        async def _recording_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                events.append("response_start")
            await send(message)

        await app(scope, receive, _recording_send)

    return _recording_app


class _Session:
    def __init__(self, *, in_transaction: bool = False) -> None:
        self._in_transaction = in_transaction
        self.begin_calls = 0

    def in_transaction(self) -> bool:
        return self._in_transaction

    def begin(self) -> "_Transaction":
        self.begin_calls += 1
        return _Transaction(self)


class _Transaction:
    def __init__(self, session: _Session) -> None:
        self._session = session

    async def __aenter__(self) -> None:
        self._session._in_transaction = True

    async def __aexit__(self, *_args: object) -> None:
        self._session._in_transaction = False


async def test_inactive_user_setup_uses_non_ambient_authentication_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    user = SimpleNamespace(is_active=False)
    authenticate = AsyncMock(return_value=user)
    container = SimpleNamespace(
        session=lambda: session,
        user_service=lambda: SimpleNamespace(authenticate=authenticate),
    )

    async def _setup_user(*, container: object, user: object) -> None:
        del container, user
        assert session.in_transaction()

    monkeypatch.setattr(container_dependency, "setup_user", _setup_user)
    monkeypatch.setattr(
        container_dependency,
        "override_user",
        lambda *, container, user: container,
    )

    dependency = container_dependency.get_container(
        with_user=True,
        with_transaction=False,
    )
    resolved = await dependency(
        request=SimpleNamespace(method="POST"),
        token="token",
        api_key="",
        container=container,
    )

    assert resolved is container
    assert session.begin_calls == 1
    assert not session.in_transaction()
    authenticate.assert_awaited_once()


async def test_upload_admission_finishes_before_the_route_uses_its_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session()
    user = SimpleNamespace(is_active=True)
    authenticate = AsyncMock(return_value=user)
    container = SimpleNamespace(
        session=lambda: session,
        user_service=lambda: SimpleNamespace(authenticate=authenticate),
    )

    async def _load_upload_admission(resolved_container: object) -> None:
        assert resolved_container is container
        assert session.in_transaction()

    monkeypatch.setattr(
        container_dependency,
        "load_container_upload_admission",
        _load_upload_admission,
    )
    monkeypatch.setattr(
        container_dependency,
        "override_user",
        lambda *, container, user: container,
    )

    dependency = container_dependency.get_container(
        with_user=True,
        with_transaction=False,
        with_upload_admission=True,
    )
    resolved = await dependency(
        request=SimpleNamespace(method="POST"),
        token="token",
        api_key="",
        container=container,
    )

    assert resolved is container
    assert session.begin_calls == 1
    assert not session.in_transaction()


async def test_load_container_upload_admission_binds_one_immutable_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _Session(in_transaction=True)
    snapshot = UploadAdmissionSnapshot(
        policy_revision=8,
        new_write_storage_target=StorageKind.OBJECT_STORE,
        session_file_maximum_bytes=11,
        session_image_maximum_bytes=12,
        session_audio_maximum_bytes=13,
        knowledge_file_maximum_bytes=14,
        knowledge_audio_maximum_bytes=15,
    )
    loader = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(
        container_dependency,
        "load_upload_admission_snapshot",
        loader,
    )
    monkeypatch.setattr(
        container_dependency,
        "object_content_runtime",
        SimpleNamespace(
            inline_maximum_bytes=99,
            object_store_maximum_bytes=199,
        ),
    )
    container = Container(session=providers.Object(session))

    resolved = await container_dependency.load_container_upload_admission(container)

    assert resolved is snapshot
    assert container.upload_admission() is snapshot
    loader.assert_awaited_once_with(
        session,
        inline_maximum_bytes=99,
        object_store_maximum_bytes=199,
    )


async def test_function_scoped_transaction_closes_before_response_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def _session() -> AsyncIterator[object]:
        events.append("session_open")
        try:
            yield object()
        finally:
            events.append("session_closed")

    monkeypatch.setattr(
        container_dependency,
        "get_session_with_transaction",
        _session,
    )
    dependency = container_dependency.get_container(transaction_scope="function")
    app = FastAPI()

    @app.get("/")
    async def _route(
        container: Annotated[Container, Depends(dependency)],
    ) -> dict[str, bool]:
        del container
        events.append("handler")
        return {"ok": True}

    transport = ASGITransport(app=_record_response_start(app, events))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert events == ["session_open", "handler", "session_closed", "response_start"]


async def test_default_transaction_scope_stays_open_through_streaming_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def _session() -> AsyncIterator[object]:
        events.append("session_open")
        try:
            yield object()
        finally:
            events.append("session_closed")

    monkeypatch.setattr(
        container_dependency,
        "get_session_with_transaction",
        _session,
    )
    dependency = container_dependency.get_container()
    app = FastAPI()

    async def _stream() -> AsyncIterator[bytes]:
        events.append("stream")
        yield b"ok"

    @app.get("/")
    async def _route(
        container: Annotated[Container, Depends(dependency)],
    ) -> StreamingResponse:
        del container
        events.append("handler")
        return StreamingResponse(_stream())

    transport = ASGITransport(app=_record_response_start(app, events))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.content == b"ok"
    assert events == [
        "session_open",
        "handler",
        "response_start",
        "stream",
        "session_closed",
    ]


def test_function_transaction_scope_requires_transaction() -> None:
    with pytest.raises(ValueError, match="transaction_scope requires"):
        container_dependency.get_container(
            with_transaction=False,
            transaction_scope="function",
        )
