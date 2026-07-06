from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class ModelTokenUsage:
    model_id: UUID
    model_name: str
    model_nickname: str
    model_org: str | None
    model_provider: str | None
    input_token_usage: int
    output_token_usage: int
    request_count: int

    @property
    def total_token_usage(self) -> int:
        """Get total token usage (input + output)."""
        return self.input_token_usage + self.output_token_usage


@dataclass
class TokenUsageSummary:
    start_date: datetime
    end_date: datetime
    models: list[ModelTokenUsage]

    @property
    def total_input_token_usage(self) -> int:
        """Get total input token usage across all models."""
        return sum(model.input_token_usage for model in self.models)

    @property
    def total_output_token_usage(self) -> int:
        """Get total output token usage across all models."""
        return sum(model.output_token_usage for model in self.models)

    @property
    def total_token_usage(self) -> int:
        """Get combined total token usage across all models."""
        return self.total_input_token_usage + self.total_output_token_usage

    @classmethod
    def from_model_usages(
        cls,
        model_usages: list[ModelTokenUsage],
        start_date: datetime,
        end_date: datetime,
    ) -> "TokenUsageSummary":
        """Create a TokenUsageSummary from a list of ModelTokenUsage objects."""
        return cls(
            start_date=start_date,
            end_date=end_date,
            models=model_usages,
        )
