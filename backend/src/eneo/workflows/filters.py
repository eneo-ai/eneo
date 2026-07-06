from dataclasses import dataclass, field


@dataclass
class Continuation:
    cont: bool
    chain_breaker_message: str = field(default="")

    def __bool__(self) -> bool:
        return self.cont


class ContinuationFilter:
    def __init__(
        self, chain_breaker_message: str = "", continue_on: bool = True
    ) -> None:
        super().__init__()
        self.chain_breaker_message = chain_breaker_message
        self.continue_on = continue_on

    def filter(
        self, value: object
    ) -> Continuation:  # renamed from 'bool' to avoid shadowing builtin
        return Continuation(
            cont=self.continue_on == value,
            chain_breaker_message=self.chain_breaker_message,
        )
