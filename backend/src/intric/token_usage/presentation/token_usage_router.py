import logging
from datetime import datetime
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from intric.main.container.container import Container
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.token_usage.presentation.token_usage_models import (
    TokenUsageSummary,
    UserSortBy,
    UserTokenUsageSummary,
    UserTokenUsageSummaryDetail,
)

logger = logging.getLogger(__name__)

router = APIRouter()

ContainerDep = Annotated[Container, Depends(get_container(with_user=True))]
StartDateQuery = Annotated[
    Optional[datetime],
    Query(
        description="Start date for token usage data (defaults to 30 days ago)."
        "Time defaults to 00:00:00.",
    ),
]
EndDateQuery = Annotated[
    Optional[datetime],
    Query(
        description="End date for token usage data (defaults to current time)."
        "Time defaults to 00:00:00.",
    ),
]


@router.get(
    "/",
    response_model=TokenUsageSummary,
    description=(
        "Get aggregate token usage statistics for the specified date range. "
        "If no dates are provided, the last 30 days are used."
    ),
    responses=responses.get_responses([]),
)
async def get_token_usage(
    container: ContainerDep,
    start_date: StartDateQuery = None,
    end_date: EndDateQuery = None,
):
    """
    Get token usage statistics for the specified date range.
    If no dates are provided, returns token usage for the last 30 days.
    Note: If no time is provided in datetime parameters, time components default to 00:00:00.
    """
    token_usage_service = container.token_usage_service()

    usage_summary = await token_usage_service.get_token_usage(
        start_date=start_date, end_date=end_date
    )

    return TokenUsageSummary.from_domain(usage_summary)


@router.get(
    "/users",
    response_model=UserTokenUsageSummary,
    description=(
        "Get token usage statistics aggregated by user for the specified date "
        "range. If no dates are provided, the last 30 days are used."
    ),
    responses=responses.get_responses([]),
)
async def get_user_token_usage(
    container: ContainerDep,
    start_date: StartDateQuery = None,
    end_date: EndDateQuery = None,
    page: Annotated[int, Query(description="Page number for pagination.")] = 1,
    per_page: Annotated[int, Query(description="Number of items per page.")] = 15,
    sort_by: Annotated[
        UserSortBy, Query(description="Field to sort by.")
    ] = UserSortBy.total_tokens,
    sort_order: Annotated[str, Query(description="Sort order (asc or desc).")] = "desc",
):
    """
    Get token usage statistics aggregated by user for the specified date range.
    If no dates are provided, returns token usage for the last 30 days.
    Note: If no time is provided in datetime parameters, time components default to 00:00:00.
    """
    token_usage_service = container.token_usage_service()

    user_usage_summary = await token_usage_service.get_user_token_usage(
        start_date=start_date,
        end_date=end_date,
        page=page,
        per_page=per_page,
        sort_by=sort_by.value,
        sort_order=sort_order,
    )

    return UserTokenUsageSummary.from_domain(user_usage_summary)


@router.get(
    "/users/{user_id}/summary",
    response_model=UserTokenUsageSummaryDetail,
    description=(
        "Get token usage summary for a specific user without fetching all users. "
        "If no dates are provided, the last 30 days are used."
    ),
    responses=responses.get_responses([404]),
)
async def get_user_summary(
    user_id: UUID,
    container: ContainerDep,
    start_date: StartDateQuery = None,
    end_date: EndDateQuery = None,
):
    """
    Get summary for a specific user without fetching all users.
    If no dates are provided, returns summary for the last 30 days.
    Note: If no time is provided in datetime parameters, time components default to 00:00:00.
    """
    try:
        token_usage_service = container.token_usage_service()

        user_summary = await token_usage_service.get_single_user_summary(
            user_id=user_id, start_date=start_date, end_date=end_date
        )

        return UserTokenUsageSummaryDetail.from_domain(user_summary)
    except Exception as e:
        logger.error(
            f"Error getting user summary for {user_id}: {str(e)}", exc_info=True
        )
        raise


@router.get(
    "/users/{user_id}",
    response_model=TokenUsageSummary,
    description=(
        "Get model breakdown for a specific user within the specified date range. "
        "If no dates are provided, the last 30 days are used."
    ),
    responses=responses.get_responses([404]),
)
async def get_user_model_breakdown(
    user_id: UUID,
    container: ContainerDep,
    start_date: StartDateQuery = None,
    end_date: EndDateQuery = None,
):
    """
    Get model breakdown for a specific user within the specified date range.
    If no dates are provided, returns model breakdown for the last 30 days.
    Note: If no time is provided in datetime parameters, time components default to 00:00:00.
    """
    token_usage_service = container.token_usage_service()

    model_breakdown = await token_usage_service.get_user_model_breakdown(
        user_id=user_id, start_date=start_date, end_date=end_date
    )

    return TokenUsageSummary.from_domain(model_breakdown)
