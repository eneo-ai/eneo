from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    String,
    case,
    cast,
    column,
    func,
    literal,
    select,
    true,
    union_all,
)
from sqlalchemy.dialects.postgresql import JSONB

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.app_table import AppRuns
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.questions_table import Questions
from eneo.token_usage.domain.token_usage_models import (
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

    def __init__(self, session: "AsyncSession") -> None:
        super().__init__()
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
                literal(0).label("reader_input_tokens"),
                literal(0).label("reader_output_tokens"),
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
                literal(0).label("reader_input_tokens"),
                literal(0).label("reader_output_tokens"),
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

        reader_query = self._reader_usage_query(tenant_id, start_date, end_date)

        # Combine the results from the three queries using union_all
        combined_usage_query = union_all(
            questions_query, app_runs_query, reader_query
        ).alias("combined_usage")

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
            func.sum(combined_usage_query.c.reader_input_tokens).label(
                "reader_input_tokens"
            ),
            func.sum(combined_usage_query.c.reader_output_tokens).label(
                "reader_output_tokens"
            ),
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
        token_usage_by_model: list[ModelTokenUsage] = []
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
                        reader_input_token_usage=row.reader_input_tokens or 0,
                        reader_output_token_usage=row.reader_output_tokens or 0,
                    )
                )

        return TokenUsageSummary.from_model_usages(
            model_usages=token_usage_by_model, start_date=start_date, end_date=end_date
        )

    @staticmethod
    def _reader_usage_query(
        tenant_id: "UUID", start_date: "datetime", end_date: "datetime"
    ):
        """Tokens the reader model spent inside digest tool calls.

        A digest reads its material with the reader model and answers with
        the turn's model. The turn's share is folded into the question row;
        the reader's share lives only in the call's ``_meta`` (under
        ``eneo.reader.*``), so it is summed from there, per reader model.
        Only calls the proxy marked internal count: an external server
        controls its own ``_meta`` and must not inflate the statistics.
        """
        # Only an array can be unnested; anything else counts as no calls.
        tool_calls = case(
            (func.jsonb_typeof(Questions.tool_calls) == "array", Questions.tool_calls),
            else_=cast(literal("[]"), JSONB),
        )
        calls = func.jsonb_array_elements(tool_calls).table_valued(
            column("value", JSONB)
        )
        call = calls.c.value
        meta = call.op("->")("meta")
        reader_model_id = meta.op("->>")("eneo.reader_model_id")
        input_text = meta.op("->>")("eneo.reader.input_tokens")
        output_text = meta.op("->>")("eneo.reader.output_tokens")
        digits = "^[0-9]{1,12}$"
        return (
            select(
                CompletionModels.id.label("model_id"),
                CompletionModels.name.label("model_name"),
                CompletionModels.nickname.label("model_nickname"),
                CompletionModels.org.label("model_org"),
                ModelProviders.name.label("model_provider"),
                func.sum(cast(input_text, BigInteger)).label("input_tokens"),
                func.sum(cast(output_text, BigInteger)).label("output_tokens"),
                func.count().label("request_count"),
                func.sum(cast(input_text, BigInteger)).label("reader_input_tokens"),
                func.sum(cast(output_text, BigInteger)).label("reader_output_tokens"),
            )
            .select_from(Questions)
            .join(calls, true())
            .join(
                CompletionModels,
                cast(CompletionModels.id, String) == reader_model_id,
            )
            .outerjoin(
                ModelProviders,
                CompletionModels.provider_id == ModelProviders.id,
            )
            .where(Questions.tenant_id == tenant_id)
            .where(Questions.created_at >= start_date)
            .where(Questions.created_at <= end_date)
            .where(call.op("->>")("is_internal") == "true")
            .where(input_text.op("~")(digits))
            .where(output_text.op("~")(digits))
            .group_by(
                CompletionModels.id,
                CompletionModels.name,
                CompletionModels.nickname,
                CompletionModels.org,
                ModelProviders.name,
            )
        )
