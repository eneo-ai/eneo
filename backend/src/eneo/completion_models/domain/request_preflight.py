from dataclasses import dataclass, field
from typing import Any, Final, Literal
from uuid import UUID

from eneo.completion_models.domain.model_capacity import ModelCapacity
from eneo.main.exceptions import ProviderRejectedRequestException
from eneo.tokens.token_utils import TokenCount

DEFAULT_USEFUL_OUTPUT_RESERVE_TOKENS: Final = 256


class CompletionOutputCapacityError(ProviderRejectedRequestException):
    def __init__(
        self,
        *,
        input_reserve_tokens: int,
        useful_output_reserve_tokens: int,
        max_input_tokens: int,
        max_output_tokens: int,
    ) -> None:
        super().__init__(
            f"The request requires {useful_output_reserve_tokens} output tokens, "
            f"but the available output capacity is {max_output_tokens} tokens.",
            code="provider_rejected_request",
            details={
                "reason": "current_request_output_capacity_insufficient",
                "input_reserve_tokens": input_reserve_tokens,
                "useful_output_reserve_tokens": useful_output_reserve_tokens,
                "max_input_tokens": max_input_tokens,
                "max_output_tokens": max_output_tokens,
                "retryable": False,
            },
        )


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
    fallback: CompletionRequestPackage | None
    file_reference_urls: dict[UUID, str] = field(default_factory=dict[UUID, str])
    refusal: (
        Literal[
            "current_request_input_does_not_fit",
            "current_request_output_capacity_insufficient",
        ]
        | None
    ) = None

    @property
    def packages(self) -> tuple[CompletionRequestPackage, ...]:
        return (
            (self.preferred, self.fallback)
            if self.fallback is not None
            else (self.preferred,)
        )

    @property
    def selected_package(self) -> CompletionRequestPackage | None:
        return next((package for package in self.packages if package.fits), None)
