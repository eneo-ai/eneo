"""The run an endpoint that starts a run answers with."""

from __future__ import annotations

from typing import TYPE_CHECKING

from eneo.flows.api.flow_assembler import FlowAssembler
from eneo.flows.api.flow_models import FlowRunPublic, FlowRunStartedByPublic
from eneo.flows.api.flow_run_started_by import started_by_for_run
from eneo.flows.application.flow_run_service import FlowRunWithResultFilesAndUsage
from eneo.flows.domain.flow import FlowRun, FlowRunStatus

if TYPE_CHECKING:
    from eneo.main.container.container import Container


async def started_run_public(container: "Container", run: FlowRun) -> FlowRunPublic:
    """``run`` as creating, retrying or regenerating it returns it.

    A new run has no result yet. An idempotent replay hands back the run the
    key first started, which may have completed since: that run is read with
    its result files, usage and final-output contract, so its ``result`` is
    projected as the run's own detail would project it.
    """
    started_by = await started_by_for_run(container, run)
    if run.status is not FlowRunStatus.COMPLETED:
        return FlowAssembler().to_run_public(run, started_by=started_by)
    view = await container.flow_run_service().enrich_run_with_result_files_and_usage(
        run=run
    )
    return read_run_public(view, started_by=started_by)


def read_run_public(
    view: FlowRunWithResultFilesAndUsage,
    *,
    started_by: FlowRunStartedByPublic | None,
) -> FlowRunPublic:
    """The run ``view`` read, with its result files, usage and final-output
    contract: the one projection every endpoint that answers with a run it
    has read uses."""
    return FlowAssembler().to_run_public(
        view.run,
        result_files=view.result_files,
        token_usage=view.token_usage,
        transcription_usage=view.transcription_usage,
        outputs=view.outputs,
        started_by=started_by,
    )
