from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from intric.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModel,
    Context,
    ResponseType,
)
from intric.completion_models.infrastructure.completion_service import CompletionService


class _DummyContextBuilder:
    def build_context(self, **kwargs):
        return Context(input=kwargs.get("input_str", ""), token_count=0)


class _DummyAdapter:
    def __init__(self, model: CompletionModel):
        self.model = model
        self.litellm_model = "dummy/model"

    def get_token_limit_of_model(self) -> int:
        return self.model.token_limit

    async def prepare_streaming(self, **kwargs):
        return SimpleNamespace(_eneo_context={"has_tools": False})

    async def iterate_stream(self, **kwargs):
        pending_approval_ids = kwargs.get("pending_approval_ids")
        assert pending_approval_ids is not None
        pending_approval_ids.add("approval-123")
        yield Completion(response_type=ResponseType.TEXT, text="hello")


def _make_completion_model() -> CompletionModel:
    now = datetime.now(timezone.utc)
    return CompletionModel(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="dummy-model",
        nickname="dummy",
        family="openai",
        token_limit=8000,
        is_deprecated=False,
        stability="stable",
        hosting="eu",
        vision=False,
        reasoning=False,
        supports_tool_calling=True,
        is_org_enabled=True,
        is_org_default=False,
        tenant_id=uuid4(),
        provider_id=uuid4(),
    )


@pytest.mark.asyncio
async def test_streaming_wrapper_cancels_pending_approval_ids():
    completion_model = _make_completion_model()
    adapter = _DummyAdapter(model=completion_model)

    service = CompletionService(
        context_builder=_DummyContextBuilder(),
        tenant=SimpleNamespace(id=uuid4()),
        session=AsyncMock(),
        redis_client=AsyncMock(),
    )
    service._get_adapter = AsyncMock(return_value=adapter)

    conversation_session = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        assistant=SimpleNamespace(id=uuid4()),
    )

    approval_manager = AsyncMock()
    approval_manager.cancel_approval = AsyncMock(return_value=True)

    with patch(
        "intric.completion_models.infrastructure.completion_service.get_approval_manager",
        return_value=approval_manager,
    ):
        response = await service.get_response(
            model=completion_model,
            text_input="hi",
            session=conversation_session,
            stream=True,
            require_tool_approval=True,
        )
        chunks = [chunk async for chunk in response.completion]

    assert chunks
    assert chunks[0].response_type == ResponseType.TEXT
    assert chunks[0].text == "hello"
    approval_manager.cancel_approval.assert_awaited_once_with("approval-123")
