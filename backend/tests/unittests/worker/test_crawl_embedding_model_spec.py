"""The crawl bootstrap snapshots its embedding provider, headers included."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.model_providers.infrastructure.litellm_provider import (
    ResolvedLiteLLMProvider,
)
from eneo.worker.crawl_tasks import _build_embedding_model_spec

HEADERS = [{"id": "h1", "name": "X-Org-Unit", "value": "{{user.department}}"}]


def _model(provider_id: Any = None) -> EmbeddingModels:
    return cast(
        EmbeddingModels,
        SimpleNamespace(
            id=uuid4(),
            name="embed",
            litellm_model_name="stored/embed",
            family="",
            max_input=512,
            max_batch_size=None,
            dimensions=None,
            open_source=False,
            provider_id=provider_id,
        ),
    )


async def test_an_active_provider_is_captured_with_its_headers():
    tenant_id = uuid4()
    provider_id = uuid4()
    loader = AsyncMock(
        return_value=ResolvedLiteLLMProvider(
            id=provider_id,
            tenant_id=tenant_id,
            name="Gateway",
            provider_type="hosted_vllm",
            credentials={"api_key": "enc:fernet:v1:x"},
            config={"endpoint": "https://gateway.internal/v1"},
            outbound_headers=HEADERS,
        )
    )

    spec = await _build_embedding_model_spec(
        session=AsyncMock(spec=AsyncSession),
        embedding_model=_model(provider_id),
        tenant_id=tenant_id,
        load_provider=loader,
    )

    assert spec.provider_id == provider_id
    assert spec.provider_type == "hosted_vllm"
    assert spec.litellm_model_name == "hosted_vllm/embed"
    assert spec.provider_config == {"endpoint": "https://gateway.internal/v1"}
    assert spec.provider_outbound_headers == HEADERS
    assert spec.family is None


async def test_a_missing_provider_captures_nothing():
    loader = AsyncMock()

    spec = await _build_embedding_model_spec(
        session=AsyncMock(spec=AsyncSession),
        embedding_model=_model(),
        tenant_id=uuid4(),
        load_provider=loader,
    )

    loader.assert_not_awaited()
    assert spec.provider_type is None
    assert spec.provider_outbound_headers is None
    assert spec.litellm_model_name == "stored/embed"
