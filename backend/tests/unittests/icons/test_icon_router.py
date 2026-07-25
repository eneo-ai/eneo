from collections.abc import AsyncGenerator
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

from eneo.database.database import get_session
from eneo.icons.api import icon_router
from eneo.icons.icon_service import IconDownload
from eneo.object_content.content import ObjectContentUnavailableError
from eneo.server.exception_handlers import add_exception_handlers


def test_public_icon_route_uses_a_non_transactional_request_container() -> None:
    route = next(
        route
        for route in icon_router.router.routes
        if isinstance(route, APIRoute) and route.endpoint is icon_router.get_icon
    )

    assert len(route.dependant.dependencies) == 1
    container_dependency = route.dependant.dependencies[0]
    assert len(container_dependency.dependencies) == 1
    assert container_dependency.dependencies[0].call is get_session


async def test_public_icon_response_consumes_the_downstream_stream_incrementally() -> (
    None
):
    pulls: list[bytes] = []
    closed = False

    async def chunks() -> AsyncGenerator[bytes]:
        for chunk in (b"abc", b"def"):
            pulls.append(chunk)
            yield chunk

    async def close() -> None:
        nonlocal closed
        closed = True

    service = MagicMock()
    service.open_icon = AsyncMock(
        return_value=IconDownload(
            chunks=chunks(),
            content_length=6,
            media_type="image/png",
            _close=close,
        )
    )

    class Container:
        @staticmethod
        def icon_service():
            return service

    response = await icon_router.get_icon(uuid4(), Container())

    assert isinstance(response, StreamingResponse)
    iterator = cast(AsyncGenerator[bytes], response.body_iterator)
    assert await anext(iterator) == b"abc"
    assert pulls == [b"abc"]
    assert response.headers["content-length"] == "6"
    assert response.headers["cache-control"] == "public, max-age=31536000"

    await iterator.aclose()
    assert closed


def test_icon_upload_returns_and_documents_object_store_503() -> None:
    service = MagicMock()
    service.create_icon = AsyncMock(
        side_effect=ObjectContentUnavailableError("injected object-store outage")
    )
    user = MagicMock(id=uuid4(), tenant_id=uuid4())

    class Container:
        @staticmethod
        def icon_service():
            return service

        @staticmethod
        def user():
            return user

    app = FastAPI()
    add_exception_handlers(app)
    app.include_router(icon_router.router, prefix="/icons")
    route = next(
        route
        for route in icon_router.router.routes
        if isinstance(route, APIRoute) and route.endpoint is icon_router.create_icon
    )
    assert len(route.dependant.dependencies) == 1
    app.dependency_overrides[route.dependant.dependencies[0].call] = Container

    response = TestClient(app, raise_server_exceptions=False).post(
        "/icons/",
        files={"file": ("icon.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "object_content_unavailable"
    assert "503" in app.openapi()["paths"]["/icons/"]["post"]["responses"]
