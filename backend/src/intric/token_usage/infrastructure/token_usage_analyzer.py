from typing import TYPE_CHECKING

from sqlalchemy import func, select, union_all

from intric.database.tables.ai_models_table import CompletionModels
from intric.database.tables.app_table import AppRuns
from intric.database.tables.model_providers_table import ModelProviders
from intric.database.tables.questions_table import Questions
from intric.token_usage.domain.token_usage_models import (
    ModelTokenUsage,
    TokenUsageSummary,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


class TokenUsageAnalyzer:
    """
    Analyzer for token usage statistics across different models.
    This class handles querying and aggregating token usage data without using a traditional
    repository.
    """

    def __init__(self, session: "AsyncSession"):
        self.session = session

    async def get_model_token_usage(
        self, tenant_id: "UUID", start_date: "datetime", end_date: "datetime"
    ) -> TokenUsageSummary:
        """
        Get token usage statistics aggregated by model.

        Args:
            tenant_id: The tenant ID to filter by
            start_date: The start date for the analysis period
            end_date: The end date for the analysis period

        Returns:
            A TokenUsageSummary with token usage per model
        """

        # Get token usage from questions (chat messages)
        questions_query = (
            select(
                Questions.completion_model_id.label("model_id"),
                CompletionModels.name.label("model_name"),
                CompletionModels.nickname.label("model_nickname"),
                CompletionModels.org.label("model_org"),
                ModelProviders.name.label("model_provider"),
                func.sum(Questions.num_tokens_question).label("input_tokens"),
                func.sum(Questions.num_tokens_answer).label("output_tokens"),
                func.count(Questions.id).label("request_count"),
            )
            .join(
                CompletionModels,
                Questions.completion_model_id == CompletionModels.id,
            )
            .outerjoin(
                ModelProviders,
                CompletionModels.provider_id == ModelProviders.id,
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

        # Get token usage from app runs
        app_runs_query = (
            select(
                AppRuns.completion_model_id.label("model_id"),
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
            )
            .join(
                CompletionModels,
                AppRuns.completion_model_id == CompletionModels.id,
            )
            .outerjoin(
                ModelProviders,
                CompletionModels.provider_id == ModelProviders.id,
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

        # Combine the results from both queries using union_all
        combined_usage_query = union_all(questions_query, app_runs_query).alias(
            "combined_usage"
        )

        # Sum up the input/output tokens and request counts for each model
        final_query = select(
            combined_usage_query.c.model_id,
            combined_usage_query.c.model_name,
            combined_usage_query.c.model_nickname,
            combined_usage_query.c.model_org,
            combined_usage_query.c.model_provider,
            func.sum(combined_usage_query.c.input_tokens).label("input_tokens"),
            func.sum(combined_usage_query.c.output_tokens).label("output_tokens"),
            func.sum(combined_usage_query.c.request_count).label("request_count"),
        ).group_by(
            combined_usage_query.c.model_id,
            combined_usage_query.c.model_name,
            combined_usage_query.c.model_nickname,
            combined_usage_query.c.model_org,
            combined_usage_query.c.model_provider,
        )

        # Execute the query
        result = await self.session.execute(final_query)
        rows = result.all()

        # Transform the result into ModelTokenUsage objects
        token_usage_by_model = []
        for row in rows:
            if row.model_id is not None:
                token_usage_by_model.append(
                    ModelTokenUsage(
                        model_id=row.model_id,
                        model_name=row.model_name,
                        model_nickname=row.model_nickname,
                        model_org=row.model_org,
                        model_provider=row.model_provider,
                        input_token_usage=row.input_tokens or 0,
                        output_token_usage=row.output_tokens or 0,
                        request_count=row.request_count or 0,
                    )
                )

        return TokenUsageSummary.from_model_usages(
            model_usages=token_usage_by_model, start_date=start_date, end_date=end_date
        )
