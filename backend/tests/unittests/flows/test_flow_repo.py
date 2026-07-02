from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.flows import FlowFactory
from eneo.flows.assistant_authoring_snapshot import (
    AssistantAuthoringResourceRef,
    AssistantAuthoringSnapshot,
)
from eneo.flows.domain.flow import Flow, FlowStepResult
from eneo.flows.domain.flow_invariant_exceptions import FlowPersistedIdMissingError
from eneo.flows.enums import FlowStepResultStatus
from eneo.flows.flow_resource_bindings import LocalResourceKind
from eneo.flows.flow_run_step_result_file import FlowStepResultFileReference
from eneo.flows.infrastructure.flow_repo import FlowRepository


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def _step_result(status: FlowStepResultStatus) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={},
        effective_prompt="Prompt",
        output_payload_json={},
        model_parameters_json={},
        num_tokens_input=1,
        num_tokens_output=1,
        status=status,
        error_message=None,
        flow_step_execution_hash="hash",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_update_requires_persisted_flow_id() -> None:
    tenant_id = uuid4()
    session = AsyncMock()
    repo = FlowRepository(session=session, factory=FlowFactory())
    flow = Flow(
        id=None,
        tenant_id=tenant_id,
        space_id=uuid4(),
        name="Draft-only flow",
        steps=[],
    )

    with pytest.raises(FlowPersistedIdMissingError):
        await repo.update(flow=flow, tenant_id=tenant_id)

    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_assistant_snapshots_scopes_collection_query_to_tenant() -> None:
    tenant_id = uuid4()
    assistant_id = uuid4()
    kb_id = uuid4()
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[
            _RowsResult(
                [
                    SimpleNamespace(
                        id=assistant_id,
                        completion_model_id=None,
                        instructions="Do work",
                    )
                ]
            ),
            _RowsResult(
                [
                    SimpleNamespace(
                        assistant_id=assistant_id,
                        id=kb_id,
                        name="tenant-visible-kb",
                    )
                ]
            ),
            _RowsResult([]),
            _RowsResult([]),
        ]
    )
    repo = FlowRepository(session=session, factory=FlowFactory())

    snapshots = await repo.get_assistant_snapshots(
        assistant_ids=[assistant_id],
        tenant_id=tenant_id,
    )

    assert snapshots == {
        assistant_id: AssistantAuthoringSnapshot(
            instructions="Do work",
            knowledge_refs=(
                AssistantAuthoringResourceRef(
                    local_ref=str(kb_id),
                    label="tenant-visible-kb",
                    local_kind=LocalResourceKind.COLLECTION,
                ),
            ),
        )
    }
    collection_stmt = session.execute.await_args_list[1].args[0]
    compiled = str(collection_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "groups.tenant_id" in compiled
    assert tenant_id.hex in compiled


@pytest.mark.asyncio
async def test_save_step_result_requires_attempt_for_completed_result() -> None:
    session = AsyncMock()
    repo = FlowRepository(session=session, factory=FlowFactory())

    with pytest.raises(
        ValueError,
        match="attempt_no is required for completed Flow step results",
    ):
        await repo.save_step_result(
            flow_run_id=uuid4(),
            result=_step_result(FlowStepResultStatus.COMPLETED),
            tenant_id=uuid4(),
            attempt_no=None,
        )

    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_step_result_requires_attempt_for_result_files() -> None:
    session = AsyncMock()
    repo = FlowRepository(session=session, factory=FlowFactory())

    with pytest.raises(
        ValueError,
        match="attempt_no is required for Flow step result files",
    ):
        await repo.save_step_result(
            flow_run_id=uuid4(),
            result=_step_result(FlowStepResultStatus.FAILED),
            tenant_id=uuid4(),
            attempt_no=None,
            result_file_references=[
                FlowStepResultFileReference(
                    file_id=uuid4(),
                    source="generated_output",
                )
            ],
        )

    session.scalar.assert_not_awaited()
