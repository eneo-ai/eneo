"""An assistant update is refused or applied, and audited with the calling
user as actor, the same way for every caller."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from eneo.assistants.api.assistant_models import AssistantUpdatePublic
from eneo.assistants.application.assistant_update_operation import (
    apply_assistant_update,
)
from eneo.assistants.assistant import AssistantOrigin
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.main.exceptions import NotFoundException


def _assistant(
    assistant_id: UUID,
    space_id: UUID,
    *,
    name: str,
    origin: AssistantOrigin = AssistantOrigin.USER,
    managing_flow_id: UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=assistant_id,
        name=name,
        space_id=space_id,
        origin=origin,
        managing_flow_id=managing_flow_id,
        type=None,
        enabled_capabilities=[],
        document_template=None,
        prompt=None,
        completion_model=None,
        completion_model_kwargs=None,
        description=None,
        insight_enabled=None,
        data_retention_days=None,
        collections=[],
        websites=[],
        attachments=[],
        attachment_inline_text={},
        integration_knowledge_list=[],
        mcp_servers=[],
    )


def _context(
    *,
    origin: AssistantOrigin = AssistantOrigin.USER,
    managing_flow_id: UUID | None = None,
    helper_chat_owner_id: UUID | None = None,
) -> SimpleNamespace:
    assistant_id = uuid4()
    space_id = uuid4()
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        active_api_key=None,
        username="editor",
        email="editor@example.com",
    )
    service = SimpleNamespace(
        helper_chat_owner_id=AsyncMock(return_value=helper_chat_owner_id),
        get_assistant=AsyncMock(
            return_value=(
                _assistant(
                    assistant_id,
                    space_id,
                    name="Before",
                    origin=origin,
                    managing_flow_id=managing_flow_id,
                ),
                [],
            )
        ),
        update_assistant=AsyncMock(
            return_value=(_assistant(assistant_id, space_id, name="After"), [])
        ),
    )
    audit_service = SimpleNamespace(log_async=AsyncMock())
    container: Any = SimpleNamespace(
        assistant_service=lambda: service,
        user=lambda: user,
        space_service=lambda: SimpleNamespace(
            get_space=AsyncMock(return_value=SimpleNamespace(id=space_id, name="Space"))
        ),
        audit_service=lambda: audit_service,
    )
    return SimpleNamespace(
        assistant_id=assistant_id,
        user=user,
        service=service,
        audit_service=audit_service,
        container=container,
    )


async def test_the_entry_names_the_calling_user_as_actor():
    ctx = _context()

    applied = await apply_assistant_update(
        ctx.container,
        assistant_id=ctx.assistant_id,
        update=AssistantUpdatePublic(name="After"),
    )

    ctx.audit_service.log_async.assert_awaited_once()
    entry = ctx.audit_service.log_async.await_args.kwargs
    assert entry["action"] == ActionType.ASSISTANT_UPDATED
    assert entry["entity_type"] == EntityType.ASSISTANT
    assert entry["entity_id"] == ctx.assistant_id
    assert entry["tenant_id"] == ctx.user.tenant_id
    assert entry["user"] is ctx.user
    assert entry["metadata"]["actor"]["id"] == str(ctx.user.id)
    assert entry["metadata"]["changes"] == {"name": {"old": "Before", "new": "After"}}
    assert applied.changes == entry["metadata"]["changes"]
    assert applied.assistant.name == "After"


@pytest.mark.parametrize(
    "audit_context",
    [None, {"origin": "helper_chat", "session_id": "a-session"}],
)
async def test_the_entry_extra_carries_exactly_the_audit_context_given(
    audit_context: dict[str, str] | None,
):
    ctx = _context()

    await apply_assistant_update(
        ctx.container,
        assistant_id=ctx.assistant_id,
        update=AssistantUpdatePublic(name="After"),
        audit_context=audit_context,
    )

    extra = ctx.audit_service.log_async.await_args.kwargs["metadata"]["extra"]
    assert extra == {
        "type": "standard",
        "summary": "Modified name",
        **(audit_context or {}),
    }


async def test_a_flow_managed_assistant_is_refused_before_anything_is_written():
    flow_id = uuid4()
    ctx = _context(origin=AssistantOrigin.FLOW_MANAGED, managing_flow_id=flow_id)

    with pytest.raises(HTTPException) as refused:
        await apply_assistant_update(
            ctx.container,
            assistant_id=ctx.assistant_id,
            update=AssistantUpdatePublic(name="After"),
        )

    assert refused.value.status_code == 400
    assert refused.value.detail["code"] == "flow_managed_assistant"
    assert str(flow_id) in refused.value.detail["message"]
    ctx.service.update_assistant.assert_not_awaited()
    ctx.audit_service.log_async.assert_not_awaited()


async def test_another_persons_helper_chat_assistant_is_refused_before_anything_is_written():
    ctx = _context(helper_chat_owner_id=uuid4())

    with pytest.raises(NotFoundException):
        await apply_assistant_update(
            ctx.container,
            assistant_id=ctx.assistant_id,
            update=AssistantUpdatePublic(name="After"),
        )

    ctx.service.get_assistant.assert_not_awaited()
    ctx.service.update_assistant.assert_not_awaited()
    ctx.audit_service.log_async.assert_not_awaited()
