from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from intric.token_usage.domain.token_usage_models import ModelTokenUsage


@dataclass
class UserTokenUsage:
    """Token usage data for a specific user."""
    user_id: UUID
    username: str
    email: str
    total_input_tokens: int
    total_output_tokens: int
    total_requests: int
    models_used: list[ModelTokenUsage]

    @property
    def total_tokens(self) -> int:
        """Get total token usage (input + output)."""
        return self.total_input_tokens + self.total_output_tokens


@dataclass
class UserTokenUsageSummary:
    """Summary of token usage across multiple users."""
    users: list[UserTokenUsage]
    start_date: datetime
    end_date: datetime
    total_users: int
    total_input_tokens: int
    total_output_tokens: int
    total_requests: int

    @property
    def total_tokens(self) -> int:
        """Get total tokens across all users."""
        return self.total_input_tokens + self.total_output_tokens
