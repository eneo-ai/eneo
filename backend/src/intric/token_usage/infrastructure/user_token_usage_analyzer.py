from typing import TYPE_CHECKING
import logging

from sqlalchemy import func, select, union_all, desc, asc

from intric.database.tables.ai_models_table import CompletionModels
from intric.database.tables.app_table import AppRuns
from intric.database.tables.model_providers_table import ModelProviders
from intric.database.tables.questions_table import Questions
from intric.database.tables.sessions_table import Sessions
from intric.database.tables.users_table import Users
from intric.token_usage.domain.token_usage_models import (
    ModelTokenUsage,
    TokenUsageSummary,
)
from intric.token_usage.domain.user_token_usage_models import (
    UserTokenUsage,
    UserTokenUsageSummary,
)

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

class UserTokenUsageAnalyzer:
    """
    Analyzer for user-level token usage statistics.
    This class handles querying and aggregating token usage data by user without
    using a traditional repository.
    """

    def __init__(self, session: "AsyncSession"):
        self.session = session

    def _build_questions_query(self, tenant_id: "UUID", start_date: "datetime", end_date: "datetime", user_id: "UUID" = None):
        """
        Build the questions query for token usage calculation.

        Args:
            tenant_id: The tenant ID to filter by
            start_date: The start date for the analysis period
            end_date: The end date for the analysis period
            user_id: Optional user ID to filter by (for single user queries)

        Returns:
            A SQLAlchemy select query for questions token usage
        """
        query = (
            select(
                Users.id.label("user_id"),
                Users.username.label("username"),
                Users.email.label("email"),
                func.sum(Questions.num_tokens_question).label("input_tokens"),
                func.sum(Questions.num_tokens_answer).label("output_tokens"),
                func.count(Questions.id).label("request_count"),
            )
            .join(Sessions, Users.id == Sessions.user_id)
            .join(Questions,
                (Questions.session_id == Sessions.id) &
                (Questions.tenant_id == tenant_id) &
                (Questions.created_at >= start_date) &
                (Questions.created_at <= end_date)
            )
            .where(Users.tenant_id == tenant_id)
        )

        if user_id:
            query = query.where(Users.id == user_id)

        return query.group_by(Users.id, Users.username, Users.email)

    def _build_app_runs_query(self, tenant_id: "UUID", start_date: "datetime", end_date: "datetime", user_id: "UUID" = None):
        """
        Build the app runs query for token usage calculation.

        Args:
            tenant_id: The tenant ID to filter by
            start_date: The start date for the analysis period
            end_date: The end date for the analysis period
            user_id: Optional user ID to filter by (for single user queries)

        Returns:
            A SQLAlchemy select query for app runs token usage
        """
        query = (
            select(
                Users.id.label("user_id"),
                Users.username.label("username"),
                Users.email.label("email"),
                func.sum(AppRuns.num_tokens_input).label("input_tokens"),
                func.sum(AppRuns.num_tokens_output).label("output_tokens"),
                func.count(AppRuns.id).label("request_count"),
            )
            .join(AppRuns,
                (AppRuns.user_id == Users.id) &
                (AppRuns.tenant_id == tenant_id) &
                (AppRuns.created_at >= start_date) &
                (AppRuns.created_at <= end_date)
            )
            .where(Users.tenant_id == tenant_id)
        )

        if user_id:
            query = query.where(Users.id == user_id)

        return query.group_by(Users.id, Users.username, Users.email)

    def _build_combined_usage_query(self, tenant_id: "UUID", start_date: "datetime", end_date: "datetime", user_id: "UUID" = None):
        """
        Build the combined usage query that merges questions and app runs data.

        Args:
            tenant_id: The tenant ID to filter by
            start_date: The start date for the analysis period
            end_date: The end date for the analysis period
            user_id: Optional user ID to filter by (for single user queries)

        Returns:
            A SQLAlchemy select query for combined token usage
        """
        questions_query = self._build_questions_query(tenant_id, start_date, end_date, user_id)
        app_runs_query = self._build_app_runs_query(tenant_id, start_date, end_date, user_id)

        # Combine the results from both queries using union_all
        combined_usage_query = union_all(questions_query, app_runs_query).alias("combined_usage")

        # Sum up the input/output tokens and request counts
        base_query = select(
            combined_usage_query.c.user_id,
            combined_usage_query.c.username,
            combined_usage_query.c.email,
            func.sum(combined_usage_query.c.input_tokens).label("input_tokens"),
            func.sum(combined_usage_query.c.output_tokens).label("output_tokens"),
            func.sum(combined_usage_query.c.request_count).label("request_count"),
            (func.sum(combined_usage_query.c.input_tokens) +
             func.sum(combined_usage_query.c.output_tokens)).label("total_tokens"),
        ).group_by(
            combined_usage_query.c.user_id,
            combined_usage_query.c.username,
            combined_usage_query.c.email,
        )

        if not user_id:
            # Only add HAVING clause for multi-user queries to filter out users with no usage
            base_query = base_query.having(
                (func.sum(combined_usage_query.c.input_tokens) +
                 func.sum(combined_usage_query.c.output_tokens)) > 0
            )

        return base_query

    async def get_user_token_usage(
        self, tenant_id: "UUID", start_date: "datetime", end_date: "datetime", page: int = 1, per_page: int = 15, sort_by: str = "total_tokens", sort_order: str = "desc"
    ) -> UserTokenUsageSummary:
        """
        Get token usage statistics aggregated by user.

        Args:
            tenant_id: The tenant ID to filter by
            start_date: The start date for the analysis period
            end_date: The end date for the analysis period
            page: The page number for pagination
            per_page: The number of items per page
            sort_by: The field to sort by
            sort_order: The sort order (asc or desc)

        Returns:
            A UserTokenUsageSummary with token usage per user
        """
        logger.info(f"Getting user token usage for tenant {tenant_id} with sort_by={sort_by} and sort_order={sort_order}")

        # Build the base query using the helper method
        base_query = self._build_combined_usage_query(tenant_id, start_date, end_date)

        # Get the total count of users
        count_query = select(func.count()).select_from(base_query.alias("count_query"))
        total_users_result = await self.session.execute(count_query)
        total_users = total_users_result.scalar_one()

        # Add sorting to the query
        sort_column = self._get_sort_column(sort_by)
        logger.info(f"Sorting by column: {sort_column}")
        if sort_order == "desc":
            sorted_query = base_query.order_by(desc(sort_column))
        else:
            sorted_query = base_query.order_by(asc(sort_column))

        # Add pagination to the query
        paginated_query = sorted_query.limit(per_page).offset((page - 1) * per_page)

        logger.info(f"Executing query: {paginated_query}")
        # Execute the paginated query
        result = await self.session.execute(paginated_query)
        rows = result.all()

        # Transform the result into UserTokenUsage objects
        user_token_usages = []
        for row in rows:
            if row.user_id is not None:
                user_token_usages.append(
                    UserTokenUsage(
                        user_id=row.user_id,
                        username=row.username,
                        email=row.email,
                        total_input_tokens=row.input_tokens or 0,
                        total_output_tokens=row.output_tokens or 0,
                        total_requests=row.request_count or 0,
                        models_used=[],  # Load only when needed for detail view
                    )
                )

        # Calculate total tokens and requests for the current page
        total_input_tokens = sum(user.total_input_tokens for user in user_token_usages)
        total_output_tokens = sum(user.total_output_tokens for user in user_token_usages)
        total_requests = sum(user.total_requests for user in user_token_usages)

        return UserTokenUsageSummary(
            users=user_token_usages,
            start_date=start_date,
            end_date=end_date,
            total_users=total_users,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            total_requests=total_requests,
        )

    def _get_sort_column(self, sort_by: str):
        if sort_by == "username":
            return "username"
        elif sort_by == "input_tokens":
            return "input_tokens"
        elif sort_by == "output_tokens":
            return "output_tokens"
        elif sort_by == "requests":
            return "request_count"
        else:
            return "total_tokens"

    async def get_user_model_breakdown(
        self, tenant_id: "UUID", user_id: "UUID", start_date: "datetime", end_date: "datetime"
    ) -> TokenUsageSummary:
        """
        Get model breakdown for a specific user.

        Args:
            tenant_id: The tenant ID to filter by
            user_id: The user ID to get breakdown for
            start_date: The start date for the analysis period
            end_date: The end date for the analysis period

        Returns:
            A TokenUsageSummary with model breakdown for the user
        """
        return await self._get_user_model_breakdown(tenant_id, user_id, start_date, end_date)

    async def get_single_user_summary(
        self, tenant_id: "UUID", user_id: "UUID", start_date: "datetime", end_date: "datetime"
    ) -> UserTokenUsage:
        """
        Get token usage summary for a single user efficiently.

        Args:
            tenant_id: The tenant ID to filter by
            user_id: The user ID to get summary for
            start_date: The start date for the analysis period
            end_date: The end date for the analysis period

        Returns:
            A UserTokenUsage object for the specific user
        """
        logger.info(f"Getting single user summary for user {user_id} in tenant {tenant_id}")

        # Build the base query using the helper method
        query = self._build_combined_usage_query(tenant_id, start_date, end_date, user_id)

        result = await self.session.execute(query)
        row = result.first()

        if not row:
            raise ValueError(f"User with ID {user_id} not found in tenant {tenant_id}")

        # Get model breakdown for this user
        model_breakdown = await self._get_user_model_breakdown(tenant_id, user_id, start_date, end_date)

        return UserTokenUsage(
            user_id=row.user_id,
            username=row.username,
            email=row.email,
            total_input_tokens=row.input_tokens or 0,
            total_output_tokens=row.output_tokens or 0,
            total_requests=row.request_count or 0,
            models_used=[
                ModelTokenUsage(
                    model_id=model.model_id,
                    model_name=model.model_name,
                    model_nickname=model.model_nickname,
                    model_org=model.model_org,
                    model_provider=model.model_provider,
                    input_token_usage=model.input_token_usage,
                    output_token_usage=model.output_token_usage,
                    request_count=model.request_count,
                )
                for model in model_breakdown.models
            ],
        )

    async def _get_user_model_breakdown(
        self, tenant_id: "UUID", user_id: "UUID", start_date: "datetime", end_date: "datetime"
    ) -> TokenUsageSummary:
        """
        Internal method to get model breakdown for a specific user.
        This reuses the existing TokenUsageAnalyzer pattern but filters by user_id.
        """

        # Get token usage from questions (chat messages) for this user - join through sessions
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
            .join(Sessions, Questions.session_id == Sessions.id)
            .join(
                CompletionModels,
                Questions.completion_model_id == CompletionModels.id,
            )
            .outerjoin(
                ModelProviders,
                CompletionModels.provider_id == ModelProviders.id,
            )
            .where(Questions.tenant_id == tenant_id)
            .where(Sessions.user_id == user_id)
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

        # Get token usage from app runs for this user
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
            .where(AppRuns.user_id == user_id)
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
