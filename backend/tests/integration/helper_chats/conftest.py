"""What the helper chat's integration tests share: an assistant to open a chat
on, a person of another organisation, the chat's opening, the context a tool
call arrives with, and the audit entries a test queues."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import psycopg2
import pytest
import sqlalchemy as sa

from eneo.audit.application.audit_service import AuditService
from eneo.database.tables.ai_models_table import CompletionModels
from init_db import add_tenant_user


@dataclass(frozen=True)
class Setup:
    headers: dict[str, str]
    space_id: str
    assistant_id: str
    url: str


@pytest.fixture
async def setup(client, db_container, admin_user, patch_auth_service_jwt) -> Setup:
    async with db_container() as container:
        # The chat's instructions need a model that calls tools and has room.
        await container.session().execute(
            sa.update(CompletionModels)
            .where(CompletionModels.tenant_id == admin_user.tenant_id)
            .values(supports_tool_calling=True, max_input_tokens=128_000)
        )
        token = container.auth_service().create_access_token_for_user(admin_user)
    headers = {"Authorization": f"Bearer {token}"}
    space = await client.post(
        "/api/v1/spaces/",
        headers=headers,
        json={"name": f"helper-chat-{uuid4().hex[:8]}"},
    )
    assert space.status_code == 201, space.text
    assistant = await client.post(
        "/api/v1/assistants/",
        headers=headers,
        json={"name": "Ärendehjälpen", "space_id": space.json()["id"]},
    )
    assert assistant.status_code == 200, assistant.text
    assistant_id = assistant.json()["id"]
    return Setup(
        headers=headers,
        space_id=space.json()["id"],
        assistant_id=assistant_id,
        url=f"/api/v1/assistants/{assistant_id}/helper-chat/",
    )


@pytest.fixture
async def other_tenant_headers(db_container, test_settings) -> dict[str, str]:
    """An administrator of another organisation."""
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    add_tenant_user(
        conn,
        tenant_name="helper_chat_tenant_2",
        quota_limit=1000000,
        user_name="helper_chat_user_2",
        user_email="helper-chat-2@example.com",
        user_password="TenantFixturePass123!",
    )
    conn.close()
    async with db_container() as container:
        user = await container.user_repo().get_user_by_email(
            "helper-chat-2@example.com"
        )
        token = container.auth_service().create_access_token_for_user(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """The audit entries queued for the worker, each as the keyword arguments
    it was queued with."""
    entries: list[dict] = []
    log_async = AuditService.log_async

    async def record(self, **kwargs):
        entries.append(kwargs)
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)
    return entries


async def open_chat(client, setup: Setup) -> dict:
    opened = await client.post(setup.url, headers=setup.headers)
    assert opened.status_code == 200, opened.text
    return opened.json()


def loopback_ctx(token: str) -> SimpleNamespace:
    """The slice of a FastMCP ``Context`` the loopback foundation reads."""
    request = SimpleNamespace(headers={"authorization": f"Bearer {token}"})
    return SimpleNamespace(request_context=SimpleNamespace(request=request))
