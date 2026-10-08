from __future__ import annotations

from collections.abc import Callable
from functools import partial
from uuid import uuid4

import httpx
import pytest

from eneo.transcription_services import service as service_module
from eneo.transcription_services.client import TranscriptionServiceClient
from eneo.users.user import UserAdd, UserState

BASE = "/api/v1/admin/transcription-services/"


@pytest.fixture
async def admin_headers(db_container, patch_auth_service_jwt) -> dict[str, str]:
    async with db_container() as container:
        admin = await container.user_repo().get_user_by_email("test@example.com")
        token = container.auth_service().create_access_token_for_user(admin)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def member_headers(db_container, patch_auth_service_jwt) -> dict[str, str]:
    async with db_container() as container:
        admin = await container.user_repo().get_user_by_email("test@example.com")
        member = await container.user_repo().add(
            UserAdd(
                email=f"service-member-{uuid4().hex[:8]}@example.com",
                username=f"service_member_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin.tenant_id,
            )
        )
        token = container.auth_service().create_access_token_for_user(member)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def create_connection(client, admin_headers) -> Callable[..., object]:
    async def create(**overrides: object) -> dict:
        body = {
            "name": f"vemsa-{uuid4().hex[:8]}",
            "endpoint_url": "https://vemsa.example.se/v1/",
            "api_key": "first-secret",
            "operations": ["diarize", "transcribe"],
            **overrides,
        }
        response = await client.post(BASE, json=body, headers=admin_headers)
        assert response.status_code == 201, response.text
        return response.json()

    return create


class NativeService:
    """A native service's readiness endpoint, scripted per test."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.answer: httpx.Response | Exception = httpx.Response(
            200, json={"queue_accepting_jobs": True}
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@pytest.fixture
def native_service(monkeypatch) -> NativeService:
    service = NativeService()
    monkeypatch.setattr(
        service_module,
        "TranscriptionServiceClient",
        partial(
            TranscriptionServiceClient, transport=httpx.MockTransport(service.handle)
        ),
    )
    return service
