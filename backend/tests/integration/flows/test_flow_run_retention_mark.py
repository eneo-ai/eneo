"""A run is marked when it starts in a shared space that has a time.

Only marked runs are ever removed automatically. The mark is read from the
space in the statement that inserts the run, on every path that creates one,
and nothing changes it afterwards.
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID

import pytest
import sqlalchemy as sa
from httpx import AsyncClient, Response

from eneo.database.database import sessionmanager
from eneo.database.tables.flow_tables import FlowRuns, Flows, FlowStepResults
from eneo.database.tables.spaces_table import Spaces
from eneo.flows.api import (
    flow_run_lifecycle_router,
    flow_run_retry_router,
    flow_transcript_regeneration_router,
)
from eneo.flows.application.flow_transcript_regeneration_service import (
    render_original_segments,
)
from eneo.flows.domain.flow import FlowRunStatus
from eneo.flows.domain.transcript_corrections import segments_content_hash
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunError
from tests.integration.flows.test_flow_live_transcription_session import (
    LiveFlow,
    _published_flow,
)
from tests.integration.flows.test_transcript_corrections import (
    SEGMENTS,
    _store_segments,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    async def skip(*, run_id: UUID, tenant_id: UUID, expected_revision: int) -> None:
        return None

    for router in (
        flow_run_lifecycle_router,
        flow_run_retry_router,
        flow_transcript_regeneration_router,
    ):
        monkeypatch.setattr(router, "dispatch_flow_run_recoverably_after_commit", skip)


async def _flow(client: AsyncClient, headers: Mapping[str, str], db_container):
    return await _published_flow(
        client, headers, db_container, input_required=False, summarize=True
    )


async def _space(
    db_container,
    flow: LiveFlow,
    *,
    days: int | None,
    owner: UUID | None = None,
) -> None:
    """Give the flow's space this time, and make it ``owner``'s personal space."""
    async with db_container() as container:
        await container.session().execute(
            sa.update(Spaces)
            .where(Spaces.id == UUID(flow.space_id))
            .values(data_retention_days=days, user_id=owner)
        )


async def _start(
    client: AsyncClient,
    headers: Mapping[str, str],
    flow: LiveFlow,
    *,
    key: str | None = None,
) -> Response:
    return await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/",
        json={},
        headers={**headers, **({"Idempotency-Key": key} if key else {})},
    )


async def _marks(db_container, flow: LiveFlow) -> dict[str, bool]:
    async with db_container() as container:
        rows = await container.session().execute(
            sa.select(FlowRuns.id, FlowRuns.started_under_space_retention).where(
                FlowRuns.flow_id == UUID(flow.flow_id)
            )
        )
        return {str(run_id): marked for run_id, marked in rows}


async def _finish_with_a_transcript(
    db_container, flow: LiveFlow, *, failed: UUID, completed: UUID, tenant_id: UUID
) -> int:
    """One run failed after its transcript, one completed with it; the
    completed run's revision."""
    async with db_container() as container:
        session = container.session()
        for run_id in (failed, completed):
            await _store_segments(
                session=session,
                run_id=run_id,
                step_id=UUID(flow.step_id),
                segments=SEGMENTS,
            )
            await session.execute(
                sa.update(FlowStepResults)
                .where(
                    FlowStepResults.flow_run_id == run_id,
                    FlowStepResults.step_order == 1,
                )
                .values(
                    status="completed",
                    output_payload_json={"text": render_original_segments(SEGMENTS)},
                )
            )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == completed)
            .values(status="completed", finished_at=sa.func.now())
        )
        await container.flow_run_terminalizer().terminalize_run(
            run_id=failed,
            tenant_id=tenant_id,
            target_status=FlowRunStatus.FAILED,
            source=FlowRunLifecycleSource.EXECUTOR_FAILED,
            error=FlowRunError(
                code=FlowApiErrorCode.STEP_EXECUTION_FAILED,
                message="The summary failed.",
            ),
        )
        revision = await session.scalar(
            sa.select(FlowRuns.revision).where(FlowRuns.id == completed)
        )
        assert revision is not None
        return revision


async def test_every_path_that_starts_a_run_marks_it_and_a_replay_changes_nothing(
    client, flow_process_auth_headers, db_container, admin_user
):
    """Mutants: a path creates its run without the mark, the mark is read
    from anything but the space, or a replay updates the run it returns."""
    headers = dict(flow_process_auth_headers)
    flow = await _flow(client, headers, db_container)
    await _space(db_container, flow, days=30)
    started = [await _start(client, headers, flow) for _ in range(2)]
    assert [response.status_code for response in started] == [201, 201]
    failed, completed = (UUID(response.json()["id"]) for response in started)
    revision = await _finish_with_a_transcript(
        db_container,
        flow,
        failed=failed,
        completed=completed,
        tenant_id=admin_user.tenant_id,
    )

    retry_path = f"/api/v1/flows/{flow.flow_id}/runs/{failed}/retry/"
    retry_headers = {**headers, "Idempotency-Key": "mark-retry"}
    retried = await client.post(retry_path, headers=retry_headers)
    regenerated = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/{completed}/steps/{flow.step_id}"
        "/transcript-regenerations/",
        headers={**headers, "Idempotency-Key": "mark-regeneration"},
        json={
            "expected_run_revision": revision,
            "expected_correction_revision": None,
            "segments_hash": segments_content_hash(SEGMENTS),
        },
    )
    assert (retried.status_code, regenerated.status_code) == (201, 201), (
        retried.text,
        regenerated.text,
    )
    retry_id = retried.json()["run"]["id"]
    children = {retry_id, regenerated.json()["run"]["id"]}
    assert await _marks(db_container, flow) == dict.fromkeys(
        {str(failed), str(completed), *children}, True
    )

    # The space loses its time: a replay returns the run as it was, and only a
    # new run starts unmarked.
    await _space(db_container, flow, days=None)
    replayed = await client.post(retry_path, headers=retry_headers)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["run"]["id"] == retry_id
    unmarked = await _start(client, headers, flow)
    assert unmarked.status_code == 201, unmarked.text
    marks = await _marks(db_container, flow)
    assert marks.pop(unmarked.json()["id"]) is False
    assert marks == dict.fromkeys({str(failed), str(completed), *children}, True)


async def test_a_replay_after_the_space_got_a_time_keeps_the_run_unmarked(
    client, flow_process_auth_headers, db_container
):
    """Mutant: a replayed start re-reads the space and marks the run it returns."""
    headers = dict(flow_process_auth_headers)
    flow = await _flow(client, headers, db_container)
    first = await _start(client, headers, flow, key="mark-start")
    assert first.status_code == 201, first.text

    await _space(db_container, flow, days=30)
    replayed = await _start(client, headers, flow, key="mark-start")

    assert replayed.json()["id"] == first.json()["id"], replayed.text
    assert await _marks(db_container, flow) == {first.json()["id"]: False}


@pytest.mark.parametrize("case", ["flow_time_only", "personal_space"])
async def test_without_a_shared_space_time_a_run_is_not_marked(
    client, flow_process_auth_headers, db_container, admin_user, case: str
):
    """Mutants: the mark follows the flow's own time, or a personal space's
    stored time."""
    headers = dict(flow_process_auth_headers)
    flow = await _flow(client, headers, db_container)
    if case == "flow_time_only":
        async with db_container() as container:
            await container.session().execute(
                sa.update(Flows)
                .where(Flows.id == UUID(flow.flow_id))
                .values(flow_run_history_retention_days=30)
            )
    else:
        await _space(db_container, flow, days=30, owner=admin_user.id)

    started = await _start(client, headers, flow)

    assert started.status_code == 201, started.text
    assert await _marks(db_container, flow) == {started.json()["id"]: False}


async def test_the_app_reads_the_space_time_committed_when_the_run_is_inserted():
    """The mark is the space's time at the insert: under READ COMMITTED the
    statement sees the time committed before it began."""
    async with sessionmanager.session() as session, session.begin():
        isolation = await session.scalar(sa.text("SHOW transaction_isolation"))

    assert isolation == "read committed"
