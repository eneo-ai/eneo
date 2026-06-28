from dataclasses import dataclass
from typing import Optional

from eneo.main.models import ModelId
from eneo.services.service import RunnerResult
from eneo.services.service_runner import ServiceRunner
from eneo.workflows.filters import Continuation, ContinuationFilter


@dataclass
class StepResult:
    runner_result: RunnerResult
    continuation: Continuation

    @property
    def chain_breaker_message(self) -> str:
        return self.continuation.chain_breaker_message

    def __bool__(self) -> bool:
        return bool(self.continuation)


class Step:
    def __init__(
        self,
        runner: ServiceRunner,
        filter: Optional[ContinuationFilter] = None,
    ) -> None:
        super().__init__()
        self.runner = runner
        self.filter = filter

    async def __call__(
        self, input: str, file_ids: Optional[list[ModelId]] = None
    ) -> StepResult:
        runner_result = await self.runner.run(input, file_ids=file_ids or [])

        if self.filter is not None:
            continuation = self.filter.filter(runner_result.result)
        else:
            continuation = Continuation(cont=True)

        return StepResult(runner_result=runner_result, continuation=continuation)
