from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.websites_table import CrawlRuns, Websites
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import UpdateInterval


async def _embedding_model_id(session) -> UUID:
    embedding_model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
    assert embedding_model_id is not None
    return embedding_model_id


async def _create_website(
    session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    embedding_model_id: UUID,
) -> Websites:
    website = Websites(
        id=uuid4(),
        name="Token usage crawler website",
        url=f"https://crawler-token-usage-{uuid4()}.example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=UpdateInterval.NEVER,
        size=0,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
    )
    session.add(website)
    await session.flush()
    return website


async def _create_crawl_run(
    session,
    *,
    tenant_id: UUID,
    website_id: UUID,
    created_at: datetime,
    embedding_model_id: UUID,
    embedding_input_tokens: int | None,
    embedding_total_cost_usd: Decimal | None,
    embedding_usage_source: str | None,
) -> None:
    session.add(
        CrawlRuns(
            id=uuid4(),
            tenant_id=tenant_id,
            website_id=website_id,
            created_at=created_at,
            updated_at=created_at,
            embedding_model_id=embedding_model_id,
            embedding_model_name_snapshot="text-embedding-3-small",
            embedding_model_litellm_name_snapshot="openai/text-embedding-3-small",
            embedding_model_provider_snapshot="openai",
            embedding_input_tokens=embedding_input_tokens,
            embedding_total_cost_usd=embedding_total_cost_usd,
            embedding_usage_source=embedding_usage_source,
            pages_crawled=1,
            files_downloaded=0,
            pages_failed=0,
            files_failed=0,
        )
    )
    await session.flush()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_token_usage_summary_includes_crawler_embedding_source(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
):
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=1)
    end_date = now + timedelta(minutes=1)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            created_at=now - timedelta(hours=2),
            embedding_model_id=embedding_model_id,
            embedding_input_tokens=12_408,
            embedding_total_cost_usd=Decimal("0.000012408000"),
            embedding_usage_source="provider_reported",
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            created_at=now - timedelta(hours=1),
            embedding_model_id=embedding_model_id,
            embedding_input_tokens=100,
            embedding_total_cost_usd=None,
            embedding_usage_source="provider_reported",
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            created_at=now - timedelta(days=3),
            embedding_model_id=embedding_model_id,
            embedding_input_tokens=999_999,
            embedding_total_cost_usd=Decimal("9.000000000000"),
            embedding_usage_source="provider_reported",
        )
        await _create_crawl_run(
            session,
            tenant_id=admin_user.tenant_id,
            website_id=website.id,
            created_at=now - timedelta(minutes=30),
            embedding_model_id=embedding_model_id,
            embedding_input_tokens=None,
            embedding_total_cost_usd=None,
            embedding_usage_source="missing",
        )
        await session.commit()

    response = await client.get(
        "/api/v1/token-usage/",
        params={
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "source_type": "crawler_embedding",
        },
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_input_token_usage"] == 12_508
    assert data["total_output_token_usage"] == 0
    assert data["total_token_usage"] == 12_508
    assert data["total_cost_usd"] == "0.000012408000"
    assert data["cost_trackable_token_usage"] == 12_508
    assert data["cost_covered_token_usage"] == 12_408
    assert data["cost_coverage_ratio"] == pytest.approx(12_408 / 12_508)

    assert len(data["source_breakdown"]) == 1
    source = data["source_breakdown"][0]
    assert source["source_type"] == "crawler_embedding"
    assert source["model_kind"] == "embedding"
    assert source["input_token_usage"] == 12_508
    assert source["request_count"] == 2

    assert len(data["models"]) == 1
    model = data["models"][0]
    assert model["model_kind"] == "embedding"
    assert model["source_types"] == ["crawler_embedding"]
    assert model["input_token_usage"] == 12_508

    chat_response = await client.get(
        "/api/v1/token-usage/",
        params={
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "source_type": "chat",
        },
        headers={"X-API-Key": admin_user_api_key.key},
    )
    assert chat_response.status_code == 200, chat_response.text
    chat_data = chat_response.json()
    assert chat_data["total_token_usage"] == 0
    assert chat_data["source_breakdown"] == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_token_usage_summary_rejects_unknown_source_type(
    client,
    admin_user_api_key,
):
    response = await client.get(
        "/api/v1/token-usage/",
        params={"source_type": "crawler_embedding,unknown"},
        headers={"X-API-Key": admin_user_api_key.key},
    )

    assert response.status_code == 422
