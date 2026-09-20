from dataclasses import dataclass
from typing import Any, Final, Literal

from eneo.completion_models.domain.model_capacity import ModelCapacity
from eneo.tokens.token_utils import TokenCount

DEFAULT_USEFUL_OUTPUT_RESERVE_TOKENS: Final = 256


@dataclass(frozen=True, slots=True)
class CompletionRequestPackage:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    response_format: dict[str, Any] | None
    input_reserve: TokenCount
    useful_output_reserve_tokens: int
    output_cap_tokens: int | None

    @property
    def fits(self) -> bool:
        return (
            self.output_cap_tokens is not None
            and self.output_cap_tokens >= self.useful_output_reserve_tokens
        )


@dataclass(frozen=True, slots=True)
class CompletionRequestPreflight:
    """Retrieval is included only when the caller supplies its results, even empty."""

    model_route: str
    capacity: ModelCapacity
    retrieval_included: bool
    preferred: CompletionRequestPackage
    fallback: CompletionRequestPackage
    refusal: (
        Literal["fixed_overhead_too_large", "smallest_admissible_input_cannot_fit"]
        | None
    ) = None
