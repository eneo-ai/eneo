from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers
from sqlalchemy.exc import IntegrityError

from eneo.database.database import sessionmanager
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowRuntimeUploadedFiles,
    FlowStepAttempts,
    FlowStepResults,
)
from eneo.database.tables.object_content_table import (
    FileContentReferences,
    InlineContentPayloads,
    ObjectContents,
)
from eneo.files.file_models import FileContentVariant, FileInfo, FileType
from eneo.files.file_protocol import PendingFileContent, PreparedFileUpload
from eneo.files.file_service import FileService
from eneo.files.transcriber import TranscribedAudio
from eneo.flows import FlowRepository, FlowVersionRepository
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.domain.flow import (
    Flow,
    FlowRunStatus,
    FlowStep,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from eneo.flows.domain.step_output import FileBackedStepText, interpret_step_text
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.flow_run_step_result_file import FlowStepResultFileReference
from eneo.flows.infrastructure.flow_run_repo import (
    FlowRunExecutionOwner,
    FlowRunRepository,
    flow_run_execution_owner,
)
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.published_definition import FLOW_DEFINITION_SCHEMA_VERSION
from eneo.flows.runtime.step_execution_runtime import build_output_payload
from eneo.flows.runtime.step_input_resolution import resolve_step_input
from eneo.flows.runtime.step_result_builder import build_completed_step_result
from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session
from eneo.main.container.container import Container
from eneo.object_content.content import ContentFailureCode, ContentState
from tests.flow_snapshot_fixtures import assistant_snapshot
from tests.unittests.flows.test_flow_transcription import _SpaceStub, _state
from tests.unittests.flows.test_typed_io_executor import (
    _build_executor,
    _mock_assistant_for_execute_step,
    _runtime_step,
)


def _flow(
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
) -> Flow:
    now = datetime.now(timezone.utc)
    return Flow(
        id=None,
        tenant_id=tenant_id,
        space_id=space_id,
        name="Step file mapping flow",
        description="Flow used for step file mapping contract tests.",
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json=None,
        data_retention_days=30,
        created_at=now,
        updated_at=now,
        steps=[
            FlowStep(
                id=None,
                assistant_id=assistant_id,
                step_order=2,
                user_description="Runtime document step",
                input_source="flow_input",
                input_type="document",
                output_mode="pass_through",
                output_type="json",
                input_config={"runtime_input": {"enabled": True}},
            )
        ],
    )


async def _bytes(payload: bytes) -> AsyncIterator[bytes]:
    yield payload


async def _save_test_file(
    *,
    file_service: FileService,
    name: str,
    text: str | None = "file text",
) -> FileInfo:
    source_payload = f"durable source for {name}".encode("utf-8")
    contents = [
        PendingFileContent(
            variant=FileContentVariant.ORIGINAL,
            chunks=_bytes(source_payload),
            declared_media_type="application/pdf",
            verified_media_type="application/pdf",
        )
    ]
    if text is not None:
        contents.append(
            PendingFileContent(
                variant=FileContentVariant.EXTRACTED_TEXT,
                chunks=_bytes(text.encode("utf-8")),
                declared_media_type="text/plain",
                verified_media_type="text/plain",
            )
        )
    return await file_service.save_prepared_file(
        PreparedFileUpload(
            name=name,
            file_type=FileType.DOCUMENT,
            display_media_type="application/pdf",
            contents=tuple(contents),
        )
    )


async def _mark_primary_content_unavailable(*, session, file_id: UUID) -> None:
    content_id = await session.scalar(
        sa.select(FileContentReferences.content_id).where(
            FileContentReferences.file_id == file_id,
            FileContentReferences.variant == FileContentVariant.ORIGINAL.value,
        )
    )
    assert content_id is not None
    await session.execute(
        sa.update(ObjectContents)
        .where(ObjectContents.id == content_id)
        .values(
            state=ContentState.FAILED.value,
            failure_code=ContentFailureCode.BACKEND_MISSING.value,
            failure_detail="Simulated missing durable content",
        )
    )


async def _create_version(
    *,
    session,
    flow: Flow,
    tenant_id: UUID,
) -> None:
    version_repo = FlowVersionRepository(session=session)
    await version_repo.create(
        flow_id=flow.id,
        version=1,
        tenant_id=tenant_id,
        definition_json={
            "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
            "flow_id": str(flow.id),
            "steps": [
                {
                    "step_id": str(step.id),
                    "assistant_id": str(step.assistant_id),
                    "assistant_snapshot": assistant_snapshot(step.assistant_id),
                    "step_order": step.step_order,
                    "input_source": step.input_source,
                    "input_type": step.input_type,
                    "input_config": step.input_config,
                    "output_mode": step.output_mode,
                    "output_type": step.output_type,
                }
                for step in flow.steps
            ],
        },
    )


async def _bind_runtime_uploaded_files(
    *,
    session,
    flow_id: UUID,
    tenant_id: UUID,
    user_id: UUID,
    uploaded_for_step_id: UUID,
    file_ids: list[UUID],
) -> None:
    session.add_all(
        [
            FlowRuntimeUploadedFiles(
                file_id=file_id,
                flow_id=flow_id,
                tenant_id=tenant_id,
                uploaded_for_step_id=uploaded_for_step_id,
                owner_type="user",
                owner_user_id=user_id,
                owner_service_id=None,
            )
            for file_id in file_ids
        ]
    )
    await session.flush()


async def _create_running_step_file_flow(
    *,
    session,
    admin_user,
    completion_model_factory,
    space_factory,
    assistant_factory,
    additional_step=False,
):
    model = await completion_model_factory(session, "gpt-4o-mini")
    space = await space_factory(session, "Flows terminal guard files", [model.id])
    assistant = await assistant_factory(
        session,
        "Step result terminal guard assistant",
        model.id,
        space_id=space.id,
    )
    flow_repo = FlowRepository(session=session)
    definition = _flow(
        tenant_id=admin_user.tenant_id,
        space_id=space.id,
        user_id=admin_user.id,
        assistant_id=assistant.id,
    )
    if additional_step:
        definition.steps.append(
            definition.steps[0].model_copy(update={"step_order": 3})
        )
    flow = await flow_repo.create(
        flow=definition,
        tenant_id=admin_user.tenant_id,
    )
    await _create_version(
        session=session,
        flow=flow,
        tenant_id=admin_user.tenant_id,
    )
    flow = await flow_repo.update(
        flow=flow.model_copy(update={"published_version": 1}),
        tenant_id=admin_user.tenant_id,
    )
    step = flow.steps[0]
    run_repo = FlowRunRepository(session=session)
    run = await run_repo.create(
        flow_id=flow.id,
        flow_version=1,
        principal_user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        input_payload_json={"expected_flow_version": 1},
        preseed_steps=[
            {
                "step_id": step.id,
                "assistant_id": step.assistant_id,
                "step_order": step.step_order,
            }
            for step in flow.steps
        ],
    )
    assert await run_repo.mark_running_if_claimable(
        run_id=run.id,
        tenant_id=admin_user.tenant_id,
        expected_revision=run.revision,
    )
    claimed = await run_repo.claim_step_result(
        run_id=run.id,
        step_id=step.id,
        tenant_id=admin_user.tenant_id,
    )
    assert claimed is not None
    await run_repo.create_or_get_attempt_started(
        run_id=run.id,
        flow_id=flow.id,
        tenant_id=admin_user.tenant_id,
        step_id=step.id,
        step_order=step.step_order,
        attempt_no=1,
        dispatch_task_id="terminal-guard-files",
    )
    return flow, step, run, run_repo


@pytest.mark.asyncio
@pytest.mark.integration
async def test_semantic_run_payload_separates_input_file_projection(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        file_service = container.file_service(user=admin_user)
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows step file mapping", [model.id])
        assistant = await assistant_factory(
            session,
            "Step file mapping assistant",
            model.id,
            space_id=space.id,
        )
        input_file_a = await _save_test_file(
            file_service=file_service,
            name="a.pdf",
        )
        input_file_b = await _save_test_file(
            file_service=file_service,
            name="b.pdf",
        )
        input_file_a_id = input_file_a.id
        input_file_b_id = input_file_b.id

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        await _create_version(
            session=session,
            flow=flow,
            tenant_id=admin_user.tenant_id,
        )
        flow = flow.model_copy(update={"published_version": 1})
        flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)
        step = flow.steps[0]
        await _bind_runtime_uploaded_files(
            session=session,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            uploaded_for_step_id=step.id,
            file_ids=[input_file_a_id, input_file_b_id],
        )

        run_repo = FlowRunRepository(session=session)
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"expected_flow_version": 1},
            preseed_steps=[
                {
                    "step_id": step.id,
                    "assistant_id": step.assistant_id,
                    "step_order": step.step_order,
                }
            ],
            step_input_files=[
                {
                    "step_id": step.id,
                    "step_order": step.step_order,
                    "file_ids": [input_file_a.id, input_file_b.id],
                }
            ],
        )
        await session.flush()

        step_input_rows = [
            (row.step_id, row.file_id, row.ordinal)
            for row in (
                (
                    await session.execute(
                        sa.select(FlowRunStepInputFiles)
                        .where(FlowRunStepInputFiles.flow_run_id == run.id)
                        .order_by(FlowRunStepInputFiles.ordinal.asc())
                    )
                )
                .scalars()
                .all()
            )
        ]
        run_payload = run.input_payload_json
        step_id = step.id
        historical_top_level_count = await session.scalar(
            (
                sa.select(sa.func.count())
                .select_from(FlowRuns)
                .where(FlowRuns.input_payload_json.op("?")("file_ids"))
            )
        )

    assert run_payload == {"expected_flow_version": 1}
    assert step_input_rows == [
        (step_id, input_file_a_id, 0),
        (step_id, input_file_b_id, 1),
    ]
    assert historical_top_level_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_same_runtime_file_id_can_bind_to_multiple_steps(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        file_service = container.file_service(user=admin_user)
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows shared runtime file", [model.id])
        assistant = await assistant_factory(
            session,
            "Shared runtime file assistant",
            model.id,
            space_id=space.id,
        )
        input_file = await _save_test_file(
            file_service=file_service,
            name="shared.pdf",
        )
        input_file_id = input_file.id

        base_flow = _flow(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=admin_user.id,
            assistant_id=assistant.id,
        )
        first_step = base_flow.steps[0].model_copy(
            update={"step_order": 1, "user_description": "First runtime document step"}
        )
        second_step = base_flow.steps[0].model_copy(
            update={
                "id": None,
                "step_order": 2,
                "user_description": "Second runtime document step",
            }
        )

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=base_flow.model_copy(update={"steps": [first_step, second_step]}),
            tenant_id=admin_user.tenant_id,
        )
        await _create_version(
            session=session,
            flow=flow,
            tenant_id=admin_user.tenant_id,
        )
        flow = flow.model_copy(update={"published_version": 1})
        flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)
        runtime_steps = sorted(flow.steps, key=lambda step: step.step_order)
        assert len(runtime_steps) == 2
        await _bind_runtime_uploaded_files(
            session=session,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            uploaded_for_step_id=runtime_steps[0].id,
            file_ids=[input_file_id],
        )

        run_repo = FlowRunRepository(session=session)
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"expected_flow_version": 1},
            preseed_steps=[
                {
                    "step_id": step.id,
                    "assistant_id": step.assistant_id,
                    "step_order": step.step_order,
                }
                for step in runtime_steps
            ],
            step_input_files=[
                {
                    "step_id": step.id,
                    "step_order": step.step_order,
                    "file_ids": [input_file_id],
                }
                for step in runtime_steps
            ],
        )
        await session.flush()

        rows = (
            (
                await session.execute(
                    sa.select(FlowRunStepInputFiles)
                    .where(FlowRunStepInputFiles.flow_run_id == run.id)
                    .order_by(
                        FlowRunStepInputFiles.step_order.asc(),
                        FlowRunStepInputFiles.ordinal.asc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        row_projection = [(row.step_id, row.file_id, row.ordinal) for row in rows]

    assert row_projection == [
        (runtime_steps[0].id, input_file_id, 0),
        (runtime_steps[1].id, input_file_id, 0),
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_current_step_input_file_read_model_uses_relational_current_attempts(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        file_service = container.file_service(user=admin_user)
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows current runtime inputs", [model.id])
        assistant = await assistant_factory(
            session,
            "Current runtime input assistant",
            model.id,
            space_id=space.id,
        )
        file_a = await _save_test_file(
            file_service=file_service,
            name="current-a.pdf",
        )
        file_b = await _save_test_file(
            file_service=file_service,
            name="current-b.pdf",
        )
        file_c = await _save_test_file(
            file_service=file_service,
            name="current-c.pdf",
        )
        file_a_id = file_a.id
        file_b_id = file_b.id
        file_c_id = file_c.id

        base_flow = _flow(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=admin_user.id,
            assistant_id=assistant.id,
        )
        runtime_steps = [
            base_flow.steps[0].model_copy(
                update={
                    "id": None,
                    "step_order": step_order,
                    "user_description": f"Runtime input step {step_order}",
                }
            )
            for step_order in (1, 2, 3)
        ]
        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=base_flow.model_copy(update={"steps": runtime_steps}),
            tenant_id=admin_user.tenant_id,
        )
        await _create_version(
            session=session,
            flow=flow,
            tenant_id=admin_user.tenant_id,
        )
        flow = await flow_repo.update(
            flow=flow.model_copy(update={"published_version": 1}),
            tenant_id=admin_user.tenant_id,
        )
        runtime_steps = sorted(flow.steps, key=lambda step: step.step_order)
        await _bind_runtime_uploaded_files(
            session=session,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            uploaded_for_step_id=runtime_steps[0].id,
            file_ids=[file_a_id, file_b_id, file_c_id],
        )

        run_repo = FlowRunRepository(session=session)
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"expected_flow_version": 1},
            preseed_steps=[
                {
                    "step_id": step.id,
                    "assistant_id": step.assistant_id,
                    "step_order": step.step_order,
                }
                for step in runtime_steps
            ],
            step_input_files=[
                {
                    "step_id": runtime_steps[0].id,
                    "step_order": runtime_steps[0].step_order,
                    "file_ids": [file_b_id, file_a_id],
                },
                {
                    "step_id": runtime_steps[1].id,
                    "step_order": runtime_steps[1].step_order,
                    "file_ids": [file_c_id],
                },
                {
                    "step_id": runtime_steps[2].id,
                    "step_order": runtime_steps[2].step_order,
                    "file_ids": [file_a_id],
                },
            ],
        )
        now = datetime.now(timezone.utc)
        for step in runtime_steps[:2]:
            await run_repo.save_step_result(
                run.id,
                FlowStepResult(
                    id=uuid4(),
                    flow_run_id=run.id,
                    flow_id=flow.id,
                    tenant_id=admin_user.tenant_id,
                    step_id=step.id,
                    step_order=step.step_order,
                    assistant_id=step.assistant_id,
                    input_payload_json={
                        "runtime_input": {
                            "file_ids": [str(uuid4())],
                            "input_format": "document",
                        }
                    },
                    effective_prompt="prompt",
                    output_payload_json={"text": "output"},
                    model_parameters_json={},
                    num_tokens_input=1,
                    num_tokens_output=1,
                    status=FlowStepResultStatus.COMPLETED,
                    error_message=None,
                    flow_step_execution_hash=f"hash-{step.step_order}",
                    created_at=now,
                    updated_at=now,
                ),
                tenant_id=admin_user.tenant_id,
                attempt_no=1,
            )
        await session.flush()

        step_results = await run_repo.list_step_results(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
        )
        step_result_id_by_order: dict[int, UUID] = {}
        for result in step_results:
            assert result.id is not None
            step_result_id_by_order[result.step_order] = result.id
        step_input_file_selects = 0

        def count_step_input_file_selects(
            _conn,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            nonlocal step_input_file_selects
            normalized_statement = statement.lower().lstrip()
            if (
                normalized_statement.startswith("select")
                and "flow_run_step_input_files" in normalized_statement
            ):
                step_input_file_selects += 1

        sync_bind = session.sync_session.get_bind()
        sa.event.listen(
            sync_bind,
            "before_cursor_execute",
            count_step_input_file_selects,
        )
        try:
            file_ids_by_step_result_id = (
                await run_repo.list_current_step_input_file_ids_by_step_result_id(
                    run_id=run.id,
                    tenant_id=admin_user.tenant_id,
                    step_results=step_results,
                )
            )
        finally:
            sa.event.remove(
                sync_bind,
                "before_cursor_execute",
                count_step_input_file_selects,
            )
        cross_tenant_projections = (
            await run_repo.list_current_step_input_file_ids_by_step_result_id(
                run_id=run.id,
                tenant_id=uuid4(),
                step_results=step_results,
            )
        )
        no_current_attempt_projections = (
            await run_repo.list_current_step_input_file_ids_by_step_result_id(
                run_id=run.id,
                tenant_id=admin_user.tenant_id,
                step_results=[
                    result.model_copy(update={"current_attempt_no": None})
                    for result in step_results
                ],
            )
        )
        metadata_selects = 0
        metadata_statements: list[str] = []

        def count_step_input_metadata_selects(
            _conn,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ) -> None:
            nonlocal metadata_selects
            normalized_statement = statement.lower().lstrip()
            if (
                normalized_statement.startswith("select")
                and "flow_run_step_input_files" in normalized_statement
            ):
                metadata_selects += 1
                metadata_statements.append(normalized_statement)

        sa.event.listen(
            sync_bind,
            "before_cursor_execute",
            count_step_input_metadata_selects,
        )
        try:
            metadata_by_step_result_id = (
                await run_repo.list_current_step_input_file_metadata_by_step_result_id(
                    run_id=run.id,
                    tenant_id=admin_user.tenant_id,
                    step_results=step_results,
                )
            )
        finally:
            sa.event.remove(
                sync_bind,
                "before_cursor_execute",
                count_step_input_metadata_selects,
            )
        cross_tenant_metadata = (
            await run_repo.list_current_step_input_file_metadata_by_step_result_id(
                run_id=run.id,
                tenant_id=uuid4(),
                step_results=step_results,
            )
        )
        no_current_attempt_metadata = (
            await run_repo.list_current_step_input_file_metadata_by_step_result_id(
                run_id=run.id,
                tenant_id=admin_user.tenant_id,
                step_results=[
                    result.model_copy(update={"current_attempt_no": None})
                    for result in step_results
                ],
            )
        )

    assert step_input_file_selects == 1
    assert file_ids_by_step_result_id == {
        step_result_id_by_order[1]: (file_b_id, file_a_id),
        step_result_id_by_order[2]: (file_c_id,),
        step_result_id_by_order[3]: (file_a_id,),
    }
    assert cross_tenant_projections == {}
    assert no_current_attempt_projections == {}
    assert metadata_selects == 1
    assert len(metadata_statements) == 1
    metadata_statement = metadata_statements[0]
    assert "files.blob" not in metadata_statement
    assert "files.text as text" not in metadata_statement
    assert "files.transcription as transcription" not in metadata_statement
    assert [
        metadata.name
        for metadata in metadata_by_step_result_id[step_result_id_by_order[1]]
    ] == ["current-b.pdf", "current-a.pdf"]
    assert [
        metadata.file_id
        for metadata in metadata_by_step_result_id[step_result_id_by_order[1]]
    ] == [file_b_id, file_a_id]
    first_metadata = metadata_by_step_result_id[step_result_id_by_order[1]][0]
    assert first_metadata.checksum == file_b.checksum
    assert first_metadata.size == file_b.size
    assert first_metadata.mimetype == "application/pdf"
    assert first_metadata.file_type.value == "document"
    assert first_metadata.text_size_bytes == len("file text".encode("utf-8"))
    assert first_metadata.has_text is True
    assert first_metadata.has_transcription is False
    assert [
        metadata.name
        for metadata in metadata_by_step_result_id[step_result_id_by_order[2]]
    ] == ["current-c.pdf"]
    assert [
        metadata.name
        for metadata in metadata_by_step_result_id[step_result_id_by_order[3]]
    ] == ["current-a.pdf"]
    assert cross_tenant_metadata == {}
    assert no_current_attempt_metadata == {}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_step_result_file_requires_matching_step_attempt(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        file_service = container.file_service(user=admin_user)
        output_file = await _save_test_file(
            file_service=file_service,
            name="orphan-attempt-output.pdf",
        )
        output_file_id = output_file.id

        flow, step, run, _ = await _create_running_step_file_flow(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )
        result = FlowStepResult(
            id=uuid4(),
            flow_run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=step.id,
            step_order=step.step_order,
            assistant_id=step.assistant_id,
            input_payload_json={"text": "input"},
            effective_prompt="prompt",
            output_payload_json={"text": "output"},
            model_parameters_json={},
            num_tokens_input=1,
            num_tokens_output=1,
            status=FlowStepResultStatus.COMPLETED,
            error_message=None,
            flow_step_execution_hash="hash",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        saved_result = await FlowRunRepository(
            session=session,
        ).save_step_result(
            run.id,
            result,
            tenant_id=admin_user.tenant_id,
            attempt_no=1,
        )
        assert saved_result is not None

        session.add(
            FlowRunStepResultFiles(
                flow_run_id=run.id,
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                step_result_id=saved_result.id,
                step_id=step.id,
                step_order=step.step_order,
                attempt_no=2,
                file_id=output_file_id,
                ordinal=0,
                source="generated_output",
            )
        )
        with pytest.raises(
            IntegrityError,
            match="fk_flow_run_step_result_files_step_attempt",
        ):
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_step_result_files_keep_history_but_bulk_run_view_uses_current_attempt(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        file_service = container.file_service(user=admin_user)
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows step result files", [model.id])
        assistant = await assistant_factory(
            session,
            "Step result file assistant",
            model.id,
            space_id=space.id,
        )
        generated_file = await _save_test_file(
            file_service=file_service,
            name="generated.pdf",
        )
        artifact_file = await _save_test_file(
            file_service=file_service,
            name="artifact.pdf",
        )
        purged_file = await _save_test_file(
            file_service=file_service,
            name="purged.pdf",
            text=None,
        )
        generated_file_id = generated_file.id
        artifact_file_id = artifact_file.id
        purged_file_id = purged_file.id
        await _mark_primary_content_unavailable(
            session=session,
            file_id=purged_file_id,
        )

        flow_repo = FlowRepository(session=session)
        flow = await flow_repo.create(
            flow=_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        await _create_version(
            session=session,
            flow=flow,
            tenant_id=admin_user.tenant_id,
        )
        flow = flow.model_copy(update={"published_version": 1})
        flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)
        step = flow.steps[0]

        run_repo = FlowRunRepository(session=session)
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={"expected_flow_version": 1},
            preseed_steps=[
                {
                    "step_id": step.id,
                    "assistant_id": step.assistant_id,
                    "step_order": step.step_order,
                }
            ],
        )
        result = FlowStepResult(
            id=uuid4(),
            flow_run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=step.id,
            step_order=step.step_order,
            assistant_id=step.assistant_id,
            input_payload_json={"text": "input"},
            effective_prompt="prompt",
            output_payload_json={
                "text": "output",
            },
            model_parameters_json={},
            num_tokens_input=1,
            num_tokens_output=1,
            status=FlowStepResultStatus.COMPLETED,
            error_message=None,
            flow_step_execution_hash="hash",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await run_repo.create_or_get_attempt_started(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=step.id,
            step_order=step.step_order,
            attempt_no=3,
            dispatch_task_id="result-files-attempt-3",
        )
        await run_repo.save_step_result(
            run.id,
            result,
            tenant_id=admin_user.tenant_id,
            attempt_no=3,
            result_file_references=[
                FlowStepResultFileReference(
                    file_id=artifact_file_id,
                    source="declared_artifact",
                ),
                FlowStepResultFileReference(
                    file_id=generated_file_id,
                    source="generated_output",
                ),
            ],
        )
        retry_result = result.model_copy(
            update={
                "output_payload_json": {
                    "text": "retry output",
                },
            }
        )
        await run_repo.create_or_get_attempt_started(
            run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=step.id,
            step_order=step.step_order,
            attempt_no=4,
            dispatch_task_id="result-files-attempt-4",
        )
        await run_repo.save_step_result(
            run.id,
            retry_result,
            tenant_id=admin_user.tenant_id,
            attempt_no=4,
            result_file_references=[
                FlowStepResultFileReference(
                    file_id=purged_file_id,
                    source="generated_output",
                )
            ],
        )
        await session.flush()

        result_rows = [
            (row.file_id, row.attempt_no, row.source, row.ordinal)
            for row in (
                (
                    await session.execute(
                        sa.select(FlowRunStepResultFiles)
                        .where(FlowRunStepResultFiles.flow_run_id == run.id)
                        .order_by(
                            FlowRunStepResultFiles.attempt_no.asc(),
                            FlowRunStepResultFiles.ordinal.asc(),
                        )
                    )
                )
                .scalars()
                .all()
            )
        ]
        listed_files = await run_repo.list_result_files(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
        )
        listed_files_for_runs = await run_repo.list_result_files_for_runs(
            run_ids=[run.id, run.id],
            tenant_id=admin_user.tenant_id,
        )
        artifact_projection = await run_repo.get_result_file(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            file_id=artifact_file_id,
        )
        purged_projection = await run_repo.get_result_file(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            file_id=purged_file_id,
        )
        cross_tenant_projection = await run_repo.get_result_file(
            run_id=run.id,
            tenant_id=uuid4(),
            file_id=artifact_file_id,
        )

    assert {
        file_id: (attempt_no, source) for file_id, attempt_no, source, _ in result_rows
    } == {
        artifact_file_id: (3, "declared_artifact"),
        generated_file_id: (3, "generated_output"),
        purged_file_id: (4, "generated_output"),
    }
    assert [attempt_no for _, attempt_no, _, _ in result_rows] == [3, 3, 4]
    assert [ordinal for _, _, _, ordinal in result_rows] == [0, 1, 0]
    assert [item.file_id for item in listed_files] == [
        result_rows[0][0],
        result_rows[1][0],
        purged_file_id,
    ]
    assert [item.file_id for item in listed_files_for_runs] == [purged_file_id]
    assert artifact_projection is not None
    assert artifact_projection.availability == "available"
    assert artifact_projection.checksum == artifact_file.checksum
    assert purged_projection is not None
    assert purged_projection.availability == "content_purged"
    assert cross_tenant_projection is None


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("target_status", "target_step_status", "target_attempt_status"),
    [
        (
            FlowRunStatus.CANCELLED,
            FlowStepResultStatus.CANCELLED,
            FlowStepAttemptStatus.CANCELLED,
        ),
        (
            FlowRunStatus.FAILED,
            FlowStepResultStatus.FAILED,
            FlowStepAttemptStatus.FAILED,
        ),
    ],
)
async def test_late_step_result_save_after_terminalization_preserves_result_files(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    target_status,
    target_step_status,
    target_attempt_status,
):
    async with db_container(user=admin_user) as setup_container:
        setup_session = setup_container.session()
        late_file = await _save_test_file(
            file_service=setup_container.file_service(user=admin_user),
            name=f"late-{target_status.value}.pdf",
        )
        late_file_id = late_file.id
        flow, step, run, run_repo = await _create_running_step_file_flow(
            session=setup_session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )

    async with sessionmanager.session() as terminal_session, terminal_session.begin():
        run_repo = FlowRunRepository(session=terminal_session)
        terminalizer = FlowRunTerminalizer(
            run_repo,
            run_repo.audit_outbox_repo,
            FlowRunReviewCheckpointRepository(
                session=run_repo.session,
                audit_outbox_repo=run_repo.audit_outbox_repo,
            ),
        )
        await terminalizer.terminalize_run(
            run_id=run.id,
            tenant_id=admin_user.tenant_id,
            target_status=target_status,
            source=(
                FlowRunLifecycleSource.USER_CANCEL
                if target_status == FlowRunStatus.CANCELLED
                else FlowRunLifecycleSource.STALE_RUNNING_RECONCILER
            ),
            error=FlowRunError.from_source(
                (
                    FlowRunLifecycleSource.USER_CANCEL
                    if target_status == FlowRunStatus.CANCELLED
                    else FlowRunLifecycleSource.STALE_RUNNING_RECONCILER
                ),
                code=(
                    FlowApiErrorCode.RUN_USER_CANCELLED
                    if target_status == FlowRunStatus.CANCELLED
                    else FlowApiErrorCode.RUN_WORKER_STALLED
                ),
                message=f"Run was terminalized as {target_status.value}.",
            ),
        )

    async with sessionmanager.session() as late_session, late_session.begin():
        late_result = FlowStepResult(
            id=uuid4(),
            flow_run_id=run.id,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            step_id=step.id,
            step_order=step.step_order,
            assistant_id=step.assistant_id,
            input_payload_json={"text": "late input"},
            effective_prompt="late prompt",
            output_payload_json={"text": "late output"},
            model_parameters_json={},
            num_tokens_input=1,
            num_tokens_output=1,
            status=FlowStepResultStatus.COMPLETED,
            error_message=None,
            flow_step_execution_hash="late-hash",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        late_save = await FlowRunRepository(session=late_session).save_step_result(
            run.id,
            late_result,
            tenant_id=admin_user.tenant_id,
            attempt_no=1,
            result_file_references=[
                FlowStepResultFileReference(
                    file_id=late_file_id,
                    source="generated_output",
                )
            ],
        )

    async with sessionmanager.session() as read_session, read_session.begin():
        run_status = await read_session.scalar(
            sa.select(FlowRuns.status).where(FlowRuns.id == run.id)
        )
        result_row = (
            await read_session.execute(
                sa.select(
                    FlowStepResults.status,
                    FlowStepResults.output_payload_json,
                    FlowStepResults.error_message,
                ).where(FlowStepResults.flow_run_id == run.id)
            )
        ).one()
        attempt_status = await read_session.scalar(
            sa.select(FlowStepAttempts.status).where(
                FlowStepAttempts.flow_run_id == run.id
            )
        )
        file_rows = (
            (
                await read_session.execute(
                    sa.select(FlowRunStepResultFiles).where(
                        FlowRunStepResultFiles.flow_run_id == run.id
                    )
                )
            )
            .scalars()
            .all()
        )

    assert late_save is None
    assert run_status == target_status.value
    assert result_row is not None
    assert result_row.status == target_step_status.value
    assert result_row.output_payload_json is None
    assert result_row.error_message == f"Run was terminalized as {target_status.value}."
    assert attempt_status == target_attempt_status.value
    assert file_rows == []


@pytest.fixture(params=["inline_completion", "transformed_output"])
async def transcript_spill_runtime(
    request,
    db_container,
    object_content_runtime_ready,
    admin_user,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
):
    text = ("Å long meeting transcript.\n" * 200).strip()
    async with db_container(user=admin_user) as container:
        session = container.session()
        flow, source, run, _ = await _create_running_step_file_flow(
            session=session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            additional_step=True,
        )
        audio = await container.file_service(user=admin_user).save_prepared_file(
            PreparedFileUpload(
                name="meeting.wav",
                file_type=FileType.AUDIO,
                display_media_type="audio/wav",
                contents=(
                    PendingFileContent(
                        variant=FileContentVariant.ORIGINAL,
                        chunks=_bytes(b"audio supplied to the transcription provider"),
                        declared_media_type="audio/wav",
                        verified_media_type="audio/wav",
                    ),
                ),
            )
        )
        await _bind_runtime_uploaded_files(
            session=session,
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            uploaded_for_step_id=source.id,
            file_ids=[audio.id],
        )
        session.add(
            FlowRunStepInputFiles(
                flow_run_id=run.id,
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                step_id=source.id,
                step_order=source.step_order,
                attempt_no=1,
                file_id=audio.id,
                ordinal=0,
            )
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run.id)
            .values(execution_heartbeat_at=datetime.now(timezone.utc))
        )

    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        container = Container(
            session=providers.Object(session),
            user=providers.Object(admin_user),
            tenant=providers.Object(test_tenant),
        )
        executor, _, _, _ = _build_executor(admin_user, max_inline_text_bytes=2048)
        executor.session = session
        executor.flow_run_repo = container.flow_run_repo()
        executor.file_service = container.file_service(user=admin_user)
        executor.file_repo = container.file_repo()
        executor.flow_run_terminalizer = container.flow_run_terminalizer()
        model = SimpleNamespace(
            id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True
        )
        executor.space_repo.get_space_by_assistant.return_value = _SpaceStub(
            [model], model
        )
        executor.transcriber = SimpleNamespace(
            transcribe=AsyncMock(
                return_value=TranscribedAudio(text=text, duration_seconds=15000)
            )
        )
        assistant = _mock_assistant_for_execute_step()
        assistant.get_prompt_text.return_value = ""
        executor._load_assistant = AsyncMock(return_value=assistant)
        step = replace(
            _runtime_step(
                input_type="audio",
                output_mode=(
                    "transcribe_only"
                    if request.param == "transformed_output"
                    else "pass_through"
                ),
                input_bindings={"question": "Meeting notes\n{{step_input.text}}"},
            ),
            step_id=source.id,
            step_order=source.step_order,
            assistant_id=source.assistant_id,
        )
        run = await executor.flow_run_repo.get(run_id=run.id, tenant_id=run.tenant_id)
        owner_token = flow_run_execution_owner.set(
            FlowRunExecutionOwner(
                run_id=run.id, tenant_id=run.tenant_id, revision=run.revision
            )
        )
        try:
            yield SimpleNamespace(
                executor=executor,
                run=run,
                step=step,
                following_step=flow.steps[1],
                text=text,
                transformed=request.param == "transformed_output",
                metadata={
                    "wizard": {
                        "transcription_enabled": True,
                        "transcription_model": {"id": str(model.id)},
                    }
                },
            )
        finally:
            flow_run_execution_owner.reset(owner_token)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "failure_at", ["ownership_registration", "reference_persistence"]
)
async def test_transcript_spill_rolls_back_bytes_and_ownership(
    transcript_spill_runtime, monkeypatch, failure_at
):
    case = transcript_spill_runtime
    executor = case.executor
    repo = executor.flow_run_repo
    columns = (
        Files.id,
        ObjectContents.id,
        InlineContentPayloads.content_id,
        FileContentReferences.content_id,
        FlowRunStepResultFiles.id,
    )
    before = [
        set(await executor.session.scalars(sa.select(column))) for column in columns
    ]
    claimed = await repo.get_step_result(
        run_id=case.run.id, step_id=case.step.step_id, tenant_id=case.run.tenant_id
    )
    method = (
        "_replace_step_result_file_rows"
        if failure_at == "ownership_registration"
        else "update_input_payload"
    )
    original = getattr(repo, method)
    written = []

    async def fail_after_bytes(**kwargs):
        rows = (
            await executor.session.execute(
                sa.select(Files.id, InlineContentPayloads.payload)
                .join(FileContentReferences, FileContentReferences.file_id == Files.id)
                .join(
                    InlineContentPayloads,
                    InlineContentPayloads.content_id
                    == FileContentReferences.content_id,
                )
                .where(Files.id.not_in(before[0]))
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].payload == case.text.encode("utf-8")
        written.append(rows[0].id)
        if failure_at == "reference_persistence":
            await original(**kwargs)
            assert (
                await executor.session.scalar(
                    sa.select(FlowRunStepResultFiles.file_id).where(
                        FlowRunStepResultFiles.flow_run_id == case.run.id
                    )
                )
                == rows[0].id
            )
        raise RuntimeError("Injected transcript persistence failure")

    monkeypatch.setattr(repo, method, fail_after_bytes)
    with pytest.raises(
        RuntimeError, match="Injected transcript persistence failure"
    ) as caught:
        await executor._execute_step(
            step=case.step, run=case.run, attempt_no=1, version_metadata=case.metadata
        )
    assert len(written) == 1
    await executor._handle_generic_step_failure(
        run_id=case.run.id,
        tenant_id=case.run.tenant_id,
        step=case.step,
        attempt_no=1,
        claimed=claimed,
        exc=caught.value,
    )
    async with sessionmanager.session() as fresh, fresh.begin():
        after = [set(await fresh.scalars(sa.select(column))) for column in columns]
        assert after == before
        saved_run = await FlowRunRepository(fresh).get(
            run_id=case.run.id, tenant_id=case.run.tenant_id
        )
        assert saved_run.status == FlowRunStatus.FAILED
        assert "transkribering" not in saved_run.input_payload_json


async def _read_committed_transcript(*, case, db_container, admin_user):
    async with db_container(user=admin_user) as container:
        repo = container.flow_run_repo()
        run = await repo.get(run_id=case.run.id, tenant_id=case.run.tenant_id)
        reference = FileBackedStepText.model_validate(
            run.input_payload_json["transkribering"]
        )
        owned = await repo.get_result_file(
            run_id=run.id, tenant_id=run.tenant_id, file_id=reference.file_id
        )
        assert owned is not None
        assert await container.session().scalar(
            sa.select(InlineContentPayloads.payload)
            .join(
                FileContentReferences,
                FileContentReferences.content_id == InlineContentPayloads.content_id,
            )
            .where(FileContentReferences.file_id == reference.file_id)
        ) == case.text.encode("utf-8")
        deps = replace(
            case.executor._build_step_input_resolution_deps(),
            file_service=container.file_service(user=admin_user),
            flow_run_repo=repo,
        )
        value = await resolve_step_input(
            step=_runtime_step(
                step_order=4, input_bindings={"question": "{{transkribering}}"}
            ),
            context={"flow_input": run.input_payload_json},
            run=run,
            prior_results=await repo.list_step_results(
                run_id=run.id, tenant_id=run.tenant_id
            ),
            deps=deps,
        )
        assert value.text == case.text
        assert [material.file_id for material in value.materials] == [reference.file_id]
        return reference


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("later_event", ["step_failure", "output_replacement"])
async def test_committed_transcript_survives_failure_and_output_replacement(
    transcript_spill_runtime, db_container, admin_user, later_event
):
    case = transcript_spill_runtime
    executor = case.executor
    repo = executor.flow_run_repo
    claimed = await repo.get_step_result(
        run_id=case.run.id, step_id=case.step.step_id, tenant_id=case.run.tenant_id
    )
    state = _state()
    execution = await executor._execute_step(
        step=case.step,
        run=case.run,
        state=state,
        attempt_no=1,
        version_metadata=case.metadata,
    )
    output = execution.output
    result = build_completed_step_result(
        claimed=claimed,
        run_id=case.run.id,
        flow_id=case.run.flow_id,
        tenant_id=case.run.tenant_id,
        step=case.step,
        output=output,
        output_payload_json=build_output_payload(output),
        execution_hash="transcript-spill",
    )
    assert (
        await executor._persist_successful_step(
            run_id=case.run.id,
            tenant_id=case.run.tenant_id,
            step=case.step,
            output=output,
            step_result=result,
            attempt_no=1,
            attempt_start=state.attempt_start_by_step[case.step.step_id],
        )
        is not None
    )
    reference = await _read_committed_transcript(
        case=case, db_container=db_container, admin_user=admin_user
    )
    if case.transformed:
        assert output.full_text == "Meeting notes\n" + case.text
        assert (
            interpret_step_text(result.output_payload_json).file_id != reference.file_id
        )
    else:
        assert result.output_payload_json["text"] == "ok"
        assert output.generated_file_ids == []

    if later_event == "step_failure":
        following = replace(
            _runtime_step(step_order=case.following_step.step_order),
            step_id=case.following_step.id,
            assistant_id=case.following_step.assistant_id,
        )
        claimed = await repo.claim_step_result(
            run_id=case.run.id, step_id=following.step_id, tenant_id=case.run.tenant_id
        )
        await repo.create_or_get_attempt_started(
            run_id=case.run.id,
            flow_id=case.run.flow_id,
            tenant_id=case.run.tenant_id,
            step_id=following.step_id,
            step_order=following.step_order,
            attempt_no=1,
            dispatch_task_id="later-step-failure",
        )
        await executor.session.commit()
        failed = await executor._handle_generic_step_failure(
            run_id=case.run.id,
            tenant_id=case.run.tenant_id,
            step=following,
            attempt_no=1,
            claimed=claimed,
            exc=RuntimeError("Later completion failed"),
        )
        assert failed["status"] == "failed"
    else:
        replacement = "Replacement output.\n" * 200
        (
            output.persisted_text,
            output.generated_file_ids,
        ) = await executor._apply_output_cap(
            text=replacement, run=case.run, step=case.step
        )
        output.full_text = replacement
        result.output_payload_json = build_output_payload(output)
        assert (
            await executor._persist_successful_step(
                run_id=case.run.id,
                tenant_id=case.run.tenant_id,
                step=case.step,
                output=output,
                step_result=result,
                attempt_no=1,
                attempt_start=state.attempt_start_by_step[case.step.step_id],
            )
            is not None
        )
        async with db_container(user=admin_user) as container:
            ids = set(
                await container.session().scalars(
                    sa.select(FlowRunStepResultFiles.file_id).where(
                        FlowRunStepResultFiles.flow_run_id == case.run.id
                    )
                )
            )
            assert ids == {reference.file_id, *output.generated_file_ids}

    assert (
        await _read_committed_transcript(
            case=case, db_container=db_container, admin_user=admin_user
        )
        == reference
    )
