from unittest.mock import AsyncMock

from eneo.services.service import DatastoreResult, RunnerResult
from eneo.workflows.filters import ContinuationFilter
from eneo.workflows.steps import Step


async def test_steps_when_not_continuation():
    cont_filter = ContinuationFilter("Stop in the name of the law")
    runner = AsyncMock()
    runner.run.return_value = RunnerResult(
        result=False,
        datastore_result=DatastoreResult(
            chunks=[], no_duplicate_chunks=[], info_blobs=[]
        ),
    )
    step = Step(runner=runner, filter=cont_filter)

    step_result = await step("Hacker input")

    assert not step_result
    assert step_result.chain_breaker_message == "Stop in the name of the law"
