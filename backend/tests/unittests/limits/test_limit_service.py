from unittest.mock import AsyncMock

import pytest

from eneo.flows.ai_builder.ai_builder_settings import AIBuilderBudgetPolicy
from eneo.limits.limit_service import LimitService


@pytest.mark.anyio
async def test_limits_publish_effective_ai_builder_attachment_policy() -> None:
    settings_service = AsyncMock()
    settings_service.get_ai_builder_budget_policy.return_value = AIBuilderBudgetPolicy(
        conversation_safety_buffer_tokens=2_000,
        minimum_conversation_budget_tokens=4_000,
        max_attachments=37,
        max_message_chars=12_000,
    )

    limits = await LimitService(settings_service=settings_service).get_limits()

    assert limits.attachments.ai_builder_max_count == 37
    assert limits.attachments.ai_builder_max_message_chars == 12_000
    settings_service.get_ai_builder_budget_policy.assert_awaited_once_with()
