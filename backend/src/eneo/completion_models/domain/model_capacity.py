from dataclasses import dataclass
from typing import Literal

CapacityDimension = Literal["max_input_tokens", "max_output_tokens"]
CapacityAvailability = Literal["ready", "capacity_undeclared", "capacity_too_small"]


@dataclass(frozen=True, slots=True)
class ModelCapacityNoFit:
    """The complete input reserve leaves no positive output cap."""


class UnknownModelCapacityError(ValueError):
    def __init__(self, missing_dimensions: tuple[CapacityDimension, ...]) -> None:
        self.missing_dimensions = missing_dimensions
        super().__init__(f"Unknown model capacity: {', '.join(missing_dimensions)}")


@dataclass(frozen=True, slots=True)
class ModelCapacity:
    max_input_tokens: int | None
    max_output_tokens: int | None

    def __post_init__(self) -> None:
        for value in (
            self.max_input_tokens,
            self.max_output_tokens,
        ):
            if value is not None and (type(value) is not int or value <= 0):
                raise ValueError("Model capacity must be a positive integer or None")

    def missing_dimensions(self) -> tuple[CapacityDimension, ...]:
        dimensions: tuple[CapacityDimension, ...] = (
            "max_input_tokens",
            "max_output_tokens",
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

    def resolve_output_cap(
        self, *, input_tokens: int, safety_tokens: int, caller_cap: int | None = None
    ) -> int | ModelCapacityNoFit:
        self._require("max_input_tokens", "max_output_tokens")
        assert self.max_input_tokens is not None
        assert self.max_output_tokens is not None
        cap = min(
            self.max_output_tokens, self.max_input_tokens - safety_tokens - input_tokens
        )
        if caller_cap is not None:
            cap = min(cap, caller_cap)
        return cap if cap >= 1 else ModelCapacityNoFit()

    def input_allowance(self, *, output_reserve_tokens: int, safety_tokens: int) -> int:
        return self.require_input_tokens() - safety_tokens - output_reserve_tokens

    def availability(self, *, safety_tokens: int) -> CapacityAvailability:
        if self.missing_dimensions():
            return "capacity_undeclared"
        if self.require_input_tokens() < safety_tokens + 2:
            return "capacity_too_small"
        return "ready"
