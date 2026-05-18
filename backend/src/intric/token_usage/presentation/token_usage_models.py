from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, List
from uuid import UUID

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from intric.token_usage.domain.token_usage_models import (
        ModelTokenUsage as DomainModelTokenUsage,
    )
    from intric.token_usage.domain.token_usage_models import (
        TokenUsageSourceBreakdown as DomainTokenUsageSourceBreakdown,
    )
    from intric.token_usage.domain.token_usage_models import (
        TokenUsageSummary as DomainTokenUsageSummary,
    )
    from intric.token_usage.domain.user_token_usage_models import (
        UserTokenUsage as DomainUserTokenUsage,
    )
    from intric.token_usage.domain.user_token_usage_models import (
        UserTokenUsageSummary as DomainUserTokenUsageSummary,
    )


class SourceUsage(BaseModel):
    source_type: str
    model_kind: str
    input_token_usage: int = Field(
        ..., description="Number of tokens used for input prompts"
    )
    output_token_usage: int = Field(
        ..., description="Number of tokens used for model outputs"
    )
    total_token_usage: int = Field(..., description="Total tokens (input + output)")
    request_count: int = Field(
        ..., description="Number of requests recorded for this source"
    )
    total_cost_usd: Decimal | None = Field(
        default=None,
        description="Provider-reported USD cost when the source records it",
    )
    cost_covered_token_usage: int = Field(
        ..., description="Tokens with a persisted provider cost"
    )
    cost_trackable_token_usage: int = Field(
        ...,
        description="Provider-reported tokens that can be costed when a rate exists",
    )
    cost_coverage_ratio: float | None = Field(
        default=None,
        description="Share of trackable tokens that have a persisted provider cost",
    )

    @classmethod
    def from_domain(cls, source: "DomainTokenUsageSourceBreakdown") -> "SourceUsage":
        return cls(
            source_type=source.source_type.value,
            model_kind=source.model_kind.value,
            input_token_usage=source.input_token_usage,
            output_token_usage=source.output_token_usage,
            total_token_usage=source.total_token_usage,
            request_count=source.request_count,
            total_cost_usd=source.total_cost_usd,
            cost_covered_token_usage=source.cost_covered_token_usage,
            cost_trackable_token_usage=source.cost_trackable_token_usage,
            cost_coverage_ratio=source.cost_coverage_ratio,
        )


class ModelUsage(BaseModel):
    model_id: UUID | None
    model_kind: str
    model_name: str
    model_nickname: str = Field(..., description="User-friendly name of the model")
    model_org: str | None = Field(
        default=None, description="Organization providing the model"
    )
    model_provider: str | None = Field(
        default=None, description="Provider name for the model"
    )
    input_token_usage: int = Field(
        ..., description="Number of tokens used for input prompts"
    )
    output_token_usage: int = Field(
        ..., description="Number of tokens used for model outputs"
    )
    total_token_usage: int = Field(..., description="Total tokens (input + output)")
    request_count: int = Field(
        ..., description="Number of requests made with this model"
    )
    source_types: List[str] = Field(
        ..., description="Usage source types included in this model aggregate"
    )
    source_breakdown: List[SourceUsage] = Field(
        ..., description="Token usage split by source for this model"
    )
    total_cost_usd: Decimal | None = Field(
        default=None,
        description="Provider-reported USD cost when sources record it",
    )
    cost_covered_token_usage: int = Field(
        ..., description="Tokens with a persisted provider cost"
    )
    cost_trackable_token_usage: int = Field(
        ...,
        description="Provider-reported tokens that can be costed when a rate exists",
    )
    cost_coverage_ratio: float | None = Field(
        default=None,
        description="Share of trackable tokens that have a persisted provider cost",
    )

    @classmethod
    def from_domain(cls, domain_model: "DomainModelTokenUsage") -> "ModelUsage":
        return cls(
            model_id=domain_model.model_id,
            model_kind=domain_model.model_kind.value,
            model_name=domain_model.model_name,
            model_nickname=domain_model.model_nickname,
            model_org=domain_model.model_org,
            model_provider=domain_model.model_provider,
            input_token_usage=domain_model.input_token_usage,
            output_token_usage=domain_model.output_token_usage,
            total_token_usage=domain_model.total_token_usage,
            request_count=domain_model.request_count,
            source_types=[source.value for source in domain_model.source_types],
            source_breakdown=[
                SourceUsage.from_domain(source)
                for source in domain_model.source_breakdown
            ],
            total_cost_usd=domain_model.total_cost_usd,
            cost_covered_token_usage=domain_model.cost_covered_token_usage,
            cost_trackable_token_usage=domain_model.cost_trackable_token_usage,
            cost_coverage_ratio=domain_model.cost_coverage_ratio,
        )


class TokenUsageSummary(BaseModel):
    start_date: datetime
    end_date: datetime
    models: List[ModelUsage]
    source_breakdown: List[SourceUsage] = Field(
        ..., description="Token usage split by source across all models"
    )
    total_input_token_usage: int = Field(
        ..., description="Total input token usage across all models"
    )
    total_output_token_usage: int = Field(
        ..., description="Total output token usage across all models"
    )
    total_token_usage: int = Field(
        ..., description="Total combined token usage across all models"
    )
    total_cost_usd: Decimal | None = Field(
        default=None,
        description="Provider-reported USD cost when sources record it",
    )
    cost_covered_token_usage: int = Field(
        ..., description="Tokens with a persisted provider cost"
    )
    cost_trackable_token_usage: int = Field(
        ...,
        description="Provider-reported tokens that can be costed when a rate exists",
    )
    cost_coverage_ratio: float | None = Field(
        default=None,
        description="Share of trackable tokens that have a persisted provider cost",
    )

    @classmethod
    def from_domain(cls, domain: "DomainTokenUsageSummary") -> "TokenUsageSummary":
        return cls(
            start_date=domain.start_date,
            end_date=domain.end_date,
            models=[ModelUsage.from_domain(model) for model in domain.models],
            source_breakdown=[
                SourceUsage.from_domain(source) for source in domain.source_breakdown
            ],
            total_input_token_usage=domain.total_input_token_usage,
            total_output_token_usage=domain.total_output_token_usage,
            total_token_usage=domain.total_token_usage,
            total_cost_usd=domain.total_cost_usd,
            cost_covered_token_usage=domain.cost_covered_token_usage,
            cost_trackable_token_usage=domain.cost_trackable_token_usage,
            cost_coverage_ratio=domain.cost_coverage_ratio,
        )


class UserTokenUsage(BaseModel):
    user_id: UUID
    username: str
    email: str
    total_input_tokens: int = Field(
        ..., description="Total input tokens used by this user"
    )
    total_output_tokens: int = Field(
        ..., description="Total output tokens used by this user"
    )
    total_tokens: int = Field(..., description="Total tokens (input + output)")
    total_requests: int = Field(
        ..., description="Total number of requests made by this user"
    )
    models_used: List[ModelUsage] = Field(
        ..., description="Models used by this user with their usage"
    )

    @classmethod
    def from_domain(cls, domain_user: "DomainUserTokenUsage") -> "UserTokenUsage":
        return cls(
            user_id=domain_user.user_id,
            username=domain_user.username,
            email=domain_user.email,
            total_input_tokens=domain_user.total_input_tokens,
            total_output_tokens=domain_user.total_output_tokens,
            total_tokens=domain_user.total_tokens,
            total_requests=domain_user.total_requests,
            models_used=[
                ModelUsage.from_domain(model) for model in domain_user.models_used
            ],
        )


class UserSortBy(str, Enum):
    """Enum for user token usage sorting options"""

    total_tokens = "total_tokens"
    username = "username"
    input_tokens = "input_tokens"
    output_tokens = "output_tokens"
    requests = "requests"


class UserTokenUsageSummaryDetail(BaseModel):
    """Response model for single user detail endpoint"""

    user: UserTokenUsage

    @classmethod
    def from_domain(
        cls, domain_user: "DomainUserTokenUsage"
    ) -> "UserTokenUsageSummaryDetail":
        return cls(user=UserTokenUsage.from_domain(domain_user))


class UserTokenUsageSummary(BaseModel):
    users: List[UserTokenUsage] = Field(
        ..., description="List of users with their token usage"
    )
    start_date: datetime
    end_date: datetime
    total_users: int = Field(..., description="Total number of users with token usage")
    total_input_tokens: int = Field(
        ..., description="Total input tokens across all users"
    )
    total_output_tokens: int = Field(
        ..., description="Total output tokens across all users"
    )
    total_tokens: int = Field(..., description="Total tokens across all users")
    total_requests: int = Field(..., description="Total requests across all users")

    @classmethod
    def from_domain(
        cls, domain: "DomainUserTokenUsageSummary"
    ) -> "UserTokenUsageSummary":
        return cls(
            users=[UserTokenUsage.from_domain(user) for user in domain.users],
            start_date=domain.start_date,
            end_date=domain.end_date,
            total_users=domain.total_users,
            total_input_tokens=domain.total_input_tokens,
            total_output_tokens=domain.total_output_tokens,
            total_tokens=domain.total_tokens,
            total_requests=domain.total_requests,
        )
