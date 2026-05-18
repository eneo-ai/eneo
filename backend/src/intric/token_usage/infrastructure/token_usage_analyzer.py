from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import func, literal, select, union_all
from sqlalchemy.sql.selectable import Select

from intric.database.tables.ai_models_table import CompletionModels, EmbeddingModels
from intric.database.tables.app_table import AppRuns
from intric.database.tables.model_providers_table import ModelProviders
from intric.database.tables.questions_table import Questions
from intric.database.tables.websites_table import CrawlRuns
from intric.token_usage.domain.token_usage_models import (
    ModelTokenUsage,
    TokenUsageModelKind,
    TokenUsageSourceBreakdown,
    TokenUsageSourceType,
    TokenUsageSummary,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

UsageBranch = Select[tuple[object, ...]]


@dataclass
class _ModelUsageAccumulator:
    model_id: "UUID | None"
    model_kind: TokenUsageModelKind
    model_name: str
    model_nickname: str
    model_org: str | None
    model_provider: str | None
    source_breakdown: list[TokenUsageSourceBreakdown]


class TokenUsageAnalyzer:
    def __init__(self, session: "AsyncSession") -> None:
        super().__init__()
        self.session = session

    async def get_model_token_usage(
        self,
        tenant_id: "UUID",
        start_date: "datetime",
        end_date: "datetime",
        source_types: frozenset[TokenUsageSourceType] | None = None,
    ) -> TokenUsageSummary:
        requested_sources = source_types or frozenset(TokenUsageSourceType)
        branches: list[UsageBranch] = []
        if TokenUsageSourceType.CHAT in requested_sources:
            branches.append(
                self._questions_usage_query(
                    tenant_id=tenant_id,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        if TokenUsageSourceType.APP_RUN in requested_sources:
            branches.append(
                self._app_runs_usage_query(
                    tenant_id=tenant_id,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
        if TokenUsageSourceType.CRAWLER_EMBEDDING in requested_sources:
            branches.append(
                self._crawler_embedding_usage_query(
                    tenant_id=tenant_id,
                    start_date=start_date,
                    end_date=end_date,
                )
            )

        if not branches:
            return TokenUsageSummary.from_model_usages(
                model_usages=[],
                start_date=start_date,
                end_date=end_date,
            )

        combined_usage_query = union_all(*branches).alias("combined_usage")
        final_query = select(
            combined_usage_query.c.model_id,
            combined_usage_query.c.model_kind,
            combined_usage_query.c.source_type,
            combined_usage_query.c.model_name,
            combined_usage_query.c.model_nickname,
            combined_usage_query.c.model_org,
            combined_usage_query.c.model_provider,
            func.sum(combined_usage_query.c.input_tokens).label("input_tokens"),
            func.sum(combined_usage_query.c.output_tokens).label("output_tokens"),
            func.sum(combined_usage_query.c.request_count).label("request_count"),
            func.sum(combined_usage_query.c.total_cost_usd).label("total_cost_usd"),
            func.sum(combined_usage_query.c.cost_covered_tokens).label(
                "cost_covered_tokens"
            ),
            func.sum(combined_usage_query.c.cost_trackable_tokens).label(
                "cost_trackable_tokens"
            ),
        ).group_by(
            combined_usage_query.c.model_id,
            combined_usage_query.c.model_kind,
            combined_usage_query.c.source_type,
            combined_usage_query.c.model_name,
            combined_usage_query.c.model_nickname,
            combined_usage_query.c.model_org,
            combined_usage_query.c.model_provider,
        )
        result = await self.session.execute(final_query)
        model_groups: dict[
            tuple[TokenUsageModelKind, "UUID | None", str, str | None],
            _ModelUsageAccumulator,
        ] = {}
        for row in result:
            model_kind = TokenUsageModelKind(row.model_kind)
            source_type = TokenUsageSourceType(row.source_type)
            model_name = str(row.model_name)
            model_provider = row.model_provider
            key = (model_kind, row.model_id, model_name, model_provider)
            group = model_groups.setdefault(
                key,
                _ModelUsageAccumulator(
                    model_id=row.model_id,
                    model_kind=model_kind,
                    model_name=model_name,
                    model_nickname=str(row.model_nickname),
                    model_org=row.model_org,
                    model_provider=model_provider,
                    source_breakdown=[],
                ),
            )
            source = TokenUsageSourceBreakdown(
                source_type=source_type,
                model_kind=model_kind,
                input_token_usage=row.input_tokens or 0,
                output_token_usage=row.output_tokens or 0,
                request_count=row.request_count or 0,
                total_cost_usd=row.total_cost_usd,
                cost_covered_token_usage=row.cost_covered_tokens or 0,
                cost_trackable_token_usage=row.cost_trackable_tokens or 0,
            )
            group.source_breakdown.append(source)

        token_usage_by_model: list[ModelTokenUsage] = []
        for group in model_groups.values():
            sources = group.source_breakdown
            total_costs = [source.total_cost_usd for source in sources]
            total_cost_usd = (
                None
                if all(cost is None for cost in total_costs)
                else sum((cost or Decimal("0") for cost in total_costs), Decimal("0"))
            )
            token_usage_by_model.append(
                ModelTokenUsage(
                    model_id=group.model_id,
                    model_kind=group.model_kind,
                    model_name=group.model_name,
                    model_nickname=group.model_nickname,
                    model_org=group.model_org,
                    model_provider=group.model_provider,
                    input_token_usage=sum(
                        source.input_token_usage for source in sources
                    ),
                    output_token_usage=sum(
                        source.output_token_usage for source in sources
                    ),
                    request_count=sum(source.request_count for source in sources),
                    source_breakdown=sources,
                    total_cost_usd=total_cost_usd,
                    cost_covered_token_usage=sum(
                        source.cost_covered_token_usage for source in sources
                    ),
                    cost_trackable_token_usage=sum(
                        source.cost_trackable_token_usage for source in sources
                    ),
                )
            )

        token_usage_by_model.sort(
            key=lambda usage: (
                -usage.total_token_usage,
                usage.model_kind.value,
                usage.model_name,
            )
        )

        return TokenUsageSummary.from_model_usages(
            model_usages=token_usage_by_model,
            start_date=start_date,
            end_date=end_date,
        )

    def _questions_usage_query(
        self, tenant_id: "UUID", start_date: "datetime", end_date: "datetime"
    ) -> UsageBranch:
        return (
            select(
                Questions.completion_model_id.label("model_id"),
                literal(TokenUsageModelKind.COMPLETION.value).label("model_kind"),
                literal(TokenUsageSourceType.CHAT.value).label("source_type"),
                CompletionModels.name.label("model_name"),
                CompletionModels.nickname.label("model_nickname"),
                CompletionModels.org.label("model_org"),
                ModelProviders.name.label("model_provider"),
                func.sum(func.coalesce(Questions.num_tokens_question, 0)).label(
                    "input_tokens"
                ),
                func.sum(func.coalesce(Questions.num_tokens_answer, 0)).label(
                    "output_tokens"
                ),
                func.count(Questions.id).label("request_count"),
                sa.cast(literal(None), sa.Numeric(20, 12)).label("total_cost_usd"),
                literal(0).label("cost_covered_tokens"),
                literal(0).label("cost_trackable_tokens"),
            )
            .join(
                CompletionModels, Questions.completion_model_id == CompletionModels.id
            )
            .outerjoin(
                ModelProviders, CompletionModels.provider_id == ModelProviders.id
            )
            .where(Questions.tenant_id == tenant_id)
            .where(Questions.created_at >= start_date)
            .where(Questions.created_at <= end_date)
            .group_by(
                Questions.completion_model_id,
                CompletionModels.name,
                CompletionModels.nickname,
                CompletionModels.org,
                ModelProviders.name,
            )
        )

    def _app_runs_usage_query(
        self, tenant_id: "UUID", start_date: "datetime", end_date: "datetime"
    ) -> UsageBranch:
        return (
            select(
                AppRuns.completion_model_id.label("model_id"),
                literal(TokenUsageModelKind.COMPLETION.value).label("model_kind"),
                literal(TokenUsageSourceType.APP_RUN.value).label("source_type"),
                CompletionModels.name.label("model_name"),
                CompletionModels.nickname.label("model_nickname"),
                CompletionModels.org.label("model_org"),
                ModelProviders.name.label("model_provider"),
                func.sum(func.coalesce(AppRuns.num_tokens_input, 0)).label(
                    "input_tokens"
                ),
                func.sum(func.coalesce(AppRuns.num_tokens_output, 0)).label(
                    "output_tokens"
                ),
                func.count(AppRuns.id).label("request_count"),
                sa.cast(literal(None), sa.Numeric(20, 12)).label("total_cost_usd"),
                literal(0).label("cost_covered_tokens"),
                literal(0).label("cost_trackable_tokens"),
            )
            .join(CompletionModels, AppRuns.completion_model_id == CompletionModels.id)
            .outerjoin(
                ModelProviders, CompletionModels.provider_id == ModelProviders.id
            )
            .where(AppRuns.tenant_id == tenant_id)
            .where(AppRuns.created_at >= start_date)
            .where(AppRuns.created_at <= end_date)
            .group_by(
                AppRuns.completion_model_id,
                CompletionModels.name,
                CompletionModels.nickname,
                CompletionModels.org,
                ModelProviders.name,
            )
        )

    def _crawler_embedding_usage_query(
        self, tenant_id: "UUID", start_date: "datetime", end_date: "datetime"
    ) -> UsageBranch:
        reported_usage_tokens = func.coalesce(CrawlRuns.embedding_input_tokens, 0)
        embedding_model_name = func.coalesce(
            EmbeddingModels.name,
            CrawlRuns.embedding_model_name_snapshot,
            CrawlRuns.embedding_model_litellm_name_snapshot,
            "Deleted embedding model",
        )
        embedding_model_nickname = func.coalesce(
            EmbeddingModels.nickname,
            EmbeddingModels.name,
            CrawlRuns.embedding_model_name_snapshot,
            CrawlRuns.embedding_model_litellm_name_snapshot,
            "Deleted embedding model",
        )
        embedding_model_provider = func.coalesce(
            ModelProviders.name,
            CrawlRuns.embedding_model_provider_snapshot,
        )
        cost_covered_tokens = func.coalesce(
            func.sum(
                sa.case(
                    (
                        CrawlRuns.embedding_total_cost_usd.is_not(None),
                        reported_usage_tokens,
                    ),
                    else_=0,
                )
            ),
            0,
        )

        return (
            select(
                CrawlRuns.embedding_model_id.label("model_id"),
                literal(TokenUsageModelKind.EMBEDDING.value).label("model_kind"),
                literal(TokenUsageSourceType.CRAWLER_EMBEDDING.value).label(
                    "source_type"
                ),
                embedding_model_name.label("model_name"),
                embedding_model_nickname.label("model_nickname"),
                EmbeddingModels.org.label("model_org"),
                embedding_model_provider.label("model_provider"),
                func.sum(reported_usage_tokens).label("input_tokens"),
                literal(0).label("output_tokens"),
                func.count(CrawlRuns.id).label("request_count"),
                func.sum(CrawlRuns.embedding_total_cost_usd).label("total_cost_usd"),
                cost_covered_tokens.label("cost_covered_tokens"),
                func.sum(
                    sa.case(
                        (
                            CrawlRuns.embedding_usage_source == "provider_reported",
                            reported_usage_tokens,
                        ),
                        else_=0,
                    )
                ).label("cost_trackable_tokens"),
            )
            .outerjoin(
                EmbeddingModels, CrawlRuns.embedding_model_id == EmbeddingModels.id
            )
            .outerjoin(ModelProviders, EmbeddingModels.provider_id == ModelProviders.id)
            .where(CrawlRuns.tenant_id == tenant_id)
            .where(CrawlRuns.created_at >= start_date)
            .where(CrawlRuns.created_at <= end_date)
            .where(CrawlRuns.embedding_input_tokens.is_not(None))
            .group_by(
                CrawlRuns.embedding_model_id,
                embedding_model_name,
                embedding_model_nickname,
                EmbeddingModels.org,
                embedding_model_provider,
            )
        )
