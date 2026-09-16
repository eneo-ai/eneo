from dataclasses import dataclass
from typing import Literal

CapacityDimension = Literal[
    "max_input_tokens", "max_output_tokens", "context_window_tokens"
]


class UnknownModelCapacityError(ValueError):
    def __init__(self, missing_dimensions: tuple[CapacityDimension, ...]) -> None:
        self.missing_dimensions = missing_dimensions
        super().__init__(f"Unknown model capacity: {', '.join(missing_dimensions)}")


@dataclass(frozen=True, slots=True)
class ModelCapacity:
    max_input_tokens: int | None
    max_output_tokens: int | None
    context_window_tokens: int | None

    def __post_init__(self) -> None:
        for value in (
            self.max_input_tokens,
            self.max_output_tokens,
            self.context_window_tokens,
        ):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError("Model capacity must be a positive integer or None")

    def missing_dimensions(self) -> tuple[CapacityDimension, ...]:
        dimensions: tuple[CapacityDimension, ...] = (
            "max_input_tokens",
            "max_output_tokens",
            "context_window_tokens",
        )
        return tuple(name for name in dimensions if getattr(self, name) is None)

    def _require(self, *dimensions: CapacityDimension) -> None:
        missing: tuple[CapacityDimension, ...] = tuple(
            name for name in dimensions if getattr(self, name) is None
        )
        if missing:
            raise UnknownModelCapacityError(missing)

    def require_input_tokens(self) -> int:
        self._require("max_input_tokens")
        assert self.max_input_tokens is not None
        return self.max_input_tokens

    def require_output_tokens(self) -> int:
        self._require("max_output_tokens")
        assert self.max_output_tokens is not None
        return self.max_output_tokens

    def admits_input(self, input_tokens: int, *, safety_tokens: int) -> bool:
        self._require("max_input_tokens")
        assert self.max_input_tokens is not None
        return input_tokens + safety_tokens <= self.max_input_tokens

    def output_reserve_fits(self, reserve_tokens: int) -> bool:
        self._require("max_output_tokens")
        assert self.max_output_tokens is not None
        return reserve_tokens <= self.max_output_tokens

    def admits_request(
        self, input_tokens: int, *, safety_tokens: int, output_reserve_tokens: int
    ) -> bool:
        self._require("max_input_tokens", "max_output_tokens", "context_window_tokens")
        assert self.context_window_tokens is not None
        return (
            self.admits_input(input_tokens, safety_tokens=safety_tokens)
            and self.output_reserve_fits(output_reserve_tokens)
            and input_tokens + safety_tokens + output_reserve_tokens
            <= self.context_window_tokens
        )

    def builder_input_allowance(
        self, *, output_reserve_tokens: int, safety_tokens: int
    ) -> int:
        self._require("max_input_tokens", "context_window_tokens")
        assert self.max_input_tokens is not None
        assert self.context_window_tokens is not None
        return (
            min(
                self.max_input_tokens,
                self.context_window_tokens - output_reserve_tokens,
            )
            - safety_tokens
        )
