"""The knowledge trace of the passages put in the prompt reaches the response.

Flow run evidence marks a reference ``inserted_into_prompt`` only from the
trace on ``get_response``'s result (``step_execution_runtime``), so the
response must carry the trace the context builder made for the retrieved
passages, streamed or not.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModel,
    ResponseType,
)
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.completion_models.infrastructure.context_builder import ContextBuilder
from eneo.info_blobs.info_blob import InfoBlobChunkInDBWithScore


class _DummyAdapter:
    def __init__(self, model: CompletionModel):
        self.model = model

    def get_token_limit_of_model(self) -> int:
        return self.model.token_limit

    def get_model_route(self) -> str:
        return "openai/gpt-4o-mini"

    async def get_response(self, **kwargs):
        return Completion(text="answer")

    async def prepare_streaming(self, **kwargs):
        return SimpleNamespace(_eneo_context={"has_tools": False})

    async def iterate_stream(self, **kwargs):
        yield Completion(response_type=ResponseType.TEXT, text="answer")


def _model() -> CompletionModel:
    now = datetime.now(timezone.utc)
    return CompletionModel(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="gpt-4o-mini",
        nickname="test",
        family="openai",
        max_input_tokens=32768,
        max_output_tokens=4000,
        is_deprecated=False,
        stability="stable",
        hosting="eu",
        vision=False,
        reasoning=False,
        supports_tool_calling=False,
        is_org_enabled=True,
        is_org_default=False,
        tenant_id=uuid4(),
        provider_id=uuid4(),
    )


def _passage() -> InfoBlobChunkInDBWithScore:
    now = datetime.now(timezone.utc)
    return InfoBlobChunkInDBWithScore(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        text="Brasilianskt kaffe har låg syra.",
        chunk_no=0,
        info_blob_id=uuid4(),
        tenant_id=uuid4(),
        info_blob_title="Kaffeguide",
        score=0.9,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_response_carries_the_trace_of_the_passages_in_the_prompt(stream):
    model = _model()
    service = CompletionService(context_builder=ContextBuilder())
    service._get_adapter = AsyncMock(return_value=_DummyAdapter(model))  # type: ignore[method-assign]
    passage = _passage()

    response = await service.get_response(
        model=model,
        text_input="Vad vet vi om brasilianskt kaffe?",
        prompt="Svara kort.",
        info_blob_chunks=[passage],
        version=2,
        stream=stream,
    )
    if stream:
        _ = [chunk async for chunk in response.completion]

    assert response.knowledge_trace is not None
    assert response.knowledge_trace.included_source_ids == [str(passage.info_blob_id)]
