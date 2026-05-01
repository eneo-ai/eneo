from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.completion_models.application.completion_model_usage_service import (
    CompletionModelUsageService,
)


def _service_with_count(count: int = 3) -> CompletionModelUsageService:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one.return_value = count
    session.execute.return_value = result
    return CompletionModelUsageService(
        session=session, completion_model_repo=AsyncMock()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entity_type",
    [
        "assistant",
        "assistants",
        "app",
        "apps",
        "assistant_template",
        "assistant_templates",
    ],
)
async def test_count_entities_accepts_api_and_canonical_entity_names(entity_type: str):
    service = _service_with_count(3)

    count = await service._count_entities_for_type(entity_type, uuid4(), uuid4())

    assert count == 3
    service.session.execute.assert_awaited_once()
