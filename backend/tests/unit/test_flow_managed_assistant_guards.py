from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from intric.assistants.api.assistant_models import AssistantUpdatePublic
from intric.assistants.api.assistant_router import delete_assistant, update_assistant
from intric.assistants.assistant import AssistantOrigin


@pytest.mark.asyncio
async def test_update_assistant_rejects_flow_managed_mutation():
    assistant_id = uuid4()
    flow_id = uuid4()
    service = AsyncMock()
    service.get_assistant.return_value = (
        SimpleNamespace(origin=AssistantOrigin.FLOW_MANAGED, managing_flow_id=flow_id),
        [],
    )
    container = MagicMock()
    container.assistant_service.return_value = service
    container.assistant_assembler.return_value = MagicMock()
    container.user.return_value = SimpleNamespace(id=uuid4(), tenant_id=uuid4())

    with pytest.raises(HTTPException) as exc:
        await update_assistant(
            id=assistant_id,
            assistant=AssistantUpdatePublic(),
            container=container,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "flow_managed_assistant"
    assert str(flow_id) in exc.value.detail["message"]


@pytest.mark.asyncio
async def test_delete_assistant_rejects_flow_managed_mutation():
    assistant_id = uuid4()
    flow_id = uuid4()
    service = AsyncMock()
    service.get_assistant.return_value = (
        SimpleNamespace(origin=AssistantOrigin.FLOW_MANAGED, managing_flow_id=flow_id),
        [],
    )
    container = MagicMock()
    container.assistant_service.return_value = service
    container.user.return_value = SimpleNamespace(id=uuid4(), tenant_id=uuid4())

    with pytest.raises(HTTPException) as exc:
        await delete_assistant(id=assistant_id, container=container)

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "flow_managed_assistant"
    service.delete_assistant.assert_not_awaited()
