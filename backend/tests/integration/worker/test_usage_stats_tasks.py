"""The nightly usage statistics are an organisation's own: they are
recalculated whoever is, or is not, left in the organisation."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import (
    CompletionModels,
    CompletionModelUsageStats,
)
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users
from eneo.main.container.container import Container
from eneo.worker.usage_stats_tasks import recalculate_all_tenants_usage_stats


async def _organisation_with_a_model(session, *, people: str) -> tuple[UUID, UUID]:
    tenant = Tenants(
        name=f"usage-stats-{uuid4()}", quota_limit=1_000_000, state="active"
    )
    session.add(tenant)
    await session.flush()
    if people == "removed":
        session.add(
            Users(
                username=f"usage-stats-{uuid4()}",
                email=f"usage-stats-{uuid4()}@example.com",
                state="deleted",
                deleted_at=datetime.now(timezone.utc),
                used_tokens=0,
                tenant_id=tenant.id,
            )
        )
    provider = ModelProviders(
        tenant_id=tenant.id,
        name=f"usage-stats-{uuid4()}",
        provider_type="openai",
        credentials={"api_key": "x"},
        config={},
        is_active=True,
    )
    session.add(provider)
    await session.flush()
    model = CompletionModels(
        tenant_id=tenant.id,
        provider_id=provider.id,
        name="usage-stats-model",
        nickname="Usage stats model",
        family="openai",
        max_input_tokens=8000,
        max_output_tokens=4096,
        is_deprecated=False,
        stability="stable",
        hosting="usa",
        open_source=False,
        org="OpenAI",
        vision=False,
        reasoning=False,
        base_url="https://api.openai.com/v1",
        litellm_model_name="gpt-4",
        is_enabled=True,
        is_default=False,
    )
    session.add(model)
    await session.flush()
    return tenant.id, model.id


@pytest.mark.parametrize("people", ["none", "removed"])
async def test_the_nightly_recalculation_needs_nobody_in_the_organisation(
    db_session, people
) -> None:
    async with db_session() as session:
        tenant_id, model_id = await _organisation_with_a_model(session, people=people)

    assert await recalculate_all_tenants_usage_stats(Container()) is True

    async with db_session() as session:
        recalculated = await session.scalar(
            sa.select(CompletionModelUsageStats.total_usage).where(
                CompletionModelUsageStats.tenant_id == tenant_id,
                CompletionModelUsageStats.model_id == model_id,
            )
        )
    assert recalculated == 0
