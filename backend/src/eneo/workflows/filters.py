from dataclasses import dataclass


@dataclass
class Continuation:
    cont: bool
    chain_breaker_message: str = None

    def __bool__(self):
        return self.cont


class ContinuationFilter:
    def __init__(self, chain_breaker_message: str = "", continue_on: bool = True):
        self.chain_breaker_message = chain_breaker_message
        self.continue_on = continue_on

    def filter(self, bool: bool) -> Continuation:
        return Continuation(
            cont=self.continue_on == bool,
            chain_breaker_message=self.chain_breaker_message,
        )
