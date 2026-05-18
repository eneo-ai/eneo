from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID


class TokenUsageModelKind(str, Enum):
    COMPLETION = "completion"
    EMBEDDING = "embedding"


class TokenUsageSourceType(str, Enum):
    CHAT = "chat"
    APP_RUN = "app_run"
    CRAWLER_EMBEDDING = "crawler_embedding"


@dataclass
class TokenUsageSourceBreakdown:
    source_type: TokenUsageSourceType
    model_kind: TokenUsageModelKind
    input_token_usage: int
    output_token_usage: int
    request_count: int
    total_cost_usd: Decimal | None
    cost_covered_token_usage: int
    cost_trackable_token_usage: int

    @property
    def total_token_usage(self) -> int:
        return self.input_token_usage + self.output_token_usage

    @property
    def cost_coverage_ratio(self) -> float | None:
        if self.cost_trackable_token_usage <= 0:
            return None
        return self.cost_covered_token_usage / self.cost_trackable_token_usage


@dataclass
class ModelTokenUsage:
    model_id: UUID | None
    model_kind: TokenUsageModelKind
    model_name: str
    model_nickname: str
    model_org: str | None
    model_provider: str | None
    input_token_usage: int
    output_token_usage: int
    request_count: int
    source_breakdown: list[TokenUsageSourceBreakdown]
    total_cost_usd: Decimal | None
    cost_covered_token_usage: int
    cost_trackable_token_usage: int

    @property
    def total_token_usage(self) -> int:
        return self.input_token_usage + self.output_token_usage

    @property
    def source_types(self) -> list[TokenUsageSourceType]:
        return [source.source_type for source in self.source_breakdown]

    @property
    def cost_coverage_ratio(self) -> float | None:
        if self.cost_trackable_token_usage <= 0:
            return None
        return self.cost_covered_token_usage / self.cost_trackable_token_usage


@dataclass
class TokenUsageSummary:
    start_date: datetime
    end_date: datetime
    models: list[ModelTokenUsage]

    @property
    def total_input_token_usage(self) -> int:
        return sum(model.input_token_usage for model in self.models)

    @property
    def total_output_token_usage(self) -> int:
        return sum(model.output_token_usage for model in self.models)

    @property
    def total_token_usage(self) -> int:
        return self.total_input_token_usage + self.total_output_token_usage

    @property
    def source_breakdown(self) -> list[TokenUsageSourceBreakdown]:
        by_source: dict[
            tuple[TokenUsageSourceType, TokenUsageModelKind],
            TokenUsageSourceBreakdown,
        ] = {}
        for model in self.models:
            for source in model.source_breakdown:
                key = (source.source_type, source.model_kind)
                existing = by_source.get(key)
                if existing is None:
                    by_source[key] = TokenUsageSourceBreakdown(
                        source_type=source.source_type,
                        model_kind=source.model_kind,
                        input_token_usage=source.input_token_usage,
                        output_token_usage=source.output_token_usage,
                        request_count=source.request_count,
                        total_cost_usd=source.total_cost_usd,
                        cost_covered_token_usage=source.cost_covered_token_usage,
                        cost_trackable_token_usage=source.cost_trackable_token_usage,
                    )
                    continue

                total_cost_usd: Decimal | None
                if existing.total_cost_usd is None and source.total_cost_usd is None:
                    total_cost_usd = None
                else:
                    total_cost_usd = (existing.total_cost_usd or Decimal("0")) + (
                        source.total_cost_usd or Decimal("0")
                    )
                by_source[key] = TokenUsageSourceBreakdown(
                    source_type=source.source_type,
                    model_kind=source.model_kind,
                    input_token_usage=existing.input_token_usage
                    + source.input_token_usage,
                    output_token_usage=existing.output_token_usage
                    + source.output_token_usage,
                    request_count=existing.request_count + source.request_count,
                    total_cost_usd=total_cost_usd,
                    cost_covered_token_usage=existing.cost_covered_token_usage
                    + source.cost_covered_token_usage,
                    cost_trackable_token_usage=existing.cost_trackable_token_usage
                    + source.cost_trackable_token_usage,
                )
        return sorted(
            by_source.values(),
            key=lambda source: (source.model_kind.value, source.source_type.value),
        )

    @property
    def total_cost_usd(self) -> Decimal | None:
        costs = [model.total_cost_usd for model in self.models]
        if all(cost is None for cost in costs):
            return None
        return sum((cost or Decimal("0") for cost in costs), Decimal("0"))

    @property
    def cost_covered_token_usage(self) -> int:
        return sum(model.cost_covered_token_usage for model in self.models)

    @property
    def cost_trackable_token_usage(self) -> int:
        return sum(model.cost_trackable_token_usage for model in self.models)

    @property
    def cost_coverage_ratio(self) -> float | None:
        if self.cost_trackable_token_usage <= 0:
            return None
        return self.cost_covered_token_usage / self.cost_trackable_token_usage

    @classmethod
    def from_model_usages(
        cls,
        model_usages: list[ModelTokenUsage],
        start_date: datetime,
        end_date: datetime,
    ) -> "TokenUsageSummary":
        return cls(
            start_date=start_date,
            end_date=end_date,
            models=model_usages,
        )
