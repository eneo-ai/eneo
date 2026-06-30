from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.completion_models.application.completion_model_usage_service import (
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method_name,entity_type",
    [
        ("_get_app_details", "app"),
        ("_get_service_details", "service"),
    ],
)
async def test_details_forward_cursor_data(method_name: str, entity_type: str):
    service = _service_with_count(3)
    cursor_data = {
        "entity_name": "older entity",
        "space_name": None,
        "owner_name": "owner",
        "entity_id": str(uuid4()),
    }
    observed: dict[str, Any] = {}

    async def fake_get_entity_details(**kwargs):
        observed.update(kwargs)
        return [], False

    service._get_entity_details = fake_get_entity_details  # type: ignore[method-assign]

    method = getattr(service, method_name)
    await method(
        model_id=uuid4(),
        tenant_id=uuid4(),
        limit=10,
        cursor_data=cursor_data,
    )

    assert observed["entity_type"] == entity_type
    assert observed["cursor_data"] == cursor_data
