from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
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
from eneo.flows import FlowFactory, FlowRepository, FlowVersionRepository
from eneo.flows.application.flow_run_terminalization import FlowRunTerminalizer
from eneo.flows.domain.flow import (
    Flow,
    FlowRunStatus,
    FlowStep,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
)
from eneo.flows.enums import FlowRunLifecycleSource
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_error import FlowRunError
from eneo.flows.flow_run_step_result_file import FlowStepResultFileReference
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_rerun_repo import FlowRunRerunRepository
from eneo.flows.infrastructure.flow_run_review_checkpoint_repo import (
    FlowRunReviewCheckpointRepository,
)
from eneo.flows.published_definition import FLOW_DEFINITION_SCHEMA_VERSION


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
                mcp_policy="inherit",
                input_config={"runtime_input": {"enabled": True}},
            )
        ],
    )


def _file(
    *,
    user_id: UUID,
    tenant_id: UUID,
    name: str,
    text: str | None = "file text",
) -> Files:
    return Files(
        name=name,
        text=text,
        blob=None,
        checksum=f"checksum-{name}",
        size=128,
        mimetype="application/pdf",
        file_type="document",
        transcription=None,
        owner_type="user",
        owner_user_id=user_id,
        owner_service_id=None,
        tenant_id=tenant_id,
    )


async def _create_version(
    *,
    session,
    flow: Flow,
    tenant_id: UUID,
) -> None:
    version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
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
                    "step_order": step.step_order,
                    "input_source": step.input_source,
                    "input_type": step.input_type,
                    "input_config": step.input_config,
                    "output_mode": step.output_mode,
                    "output_type": step.output_type,
                    "mcp_policy": step.mcp_policy,
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
):
    model = await completion_model_factory(session, "gpt-4o-mini")
    space = await space_factory(session, "Flows terminal guard files", [model.id])
    assistant = await assistant_factory(
        session,
        "Step result terminal guard assistant",
        model.id,
        space_id=space.id,
    )
    flow_repo = FlowRepository(session=session, factory=FlowFactory())
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
    flow = await flow_repo.update(
        flow=flow.model_copy(update={"published_version": 1}),
        tenant_id=admin_user.tenant_id,
    )
    step = flow.steps[0]
    run_repo = FlowRunRepository(session=session, factory=FlowFactory())
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
        celery_task_id="terminal-guard-files",
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
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows step file mapping", [model.id])
        assistant = await assistant_factory(
            session,
            "Step file mapping assistant",
            model.id,
            space_id=space.id,
        )
        input_file_a = _file(
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            name="a.pdf",
        )
        input_file_b = _file(
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            name="b.pdf",
        )
        session.add_all([input_file_a, input_file_b])
        await session.flush()
        input_file_a_id = input_file_a.id
        input_file_b_id = input_file_b.id

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
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

        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
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
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows shared runtime file", [model.id])
        assistant = await assistant_factory(
            session,
            "Shared runtime file assistant",
            model.id,
            space_id=space.id,
        )
        input_file = _file(
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            name="shared.pdf",
        )
        session.add(input_file)
        await session.flush()
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

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
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

        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
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
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows current runtime inputs", [model.id])
        assistant = await assistant_factory(
            session,
            "Current runtime input assistant",
            model.id,
            space_id=space.id,
        )
        file_a = _file(
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            name="current-a.pdf",
        )
        file_b = _file(
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            name="current-b.pdf",
        )
        file_c = _file(
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            name="current-c.pdf",
        )
        session.add_all([file_a, file_b, file_c])
        await session.flush()
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
        flow_repo = FlowRepository(session=session, factory=FlowFactory())
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

        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
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
    assert first_metadata.checksum == "checksum-current-b.pdf"
    assert first_metadata.size == 128
    assert first_metadata.mimetype == "application/pdf"
    assert first_metadata.file_type.value == "document"
    assert first_metadata.text_length == len("file text")
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
        output_file = _file(
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            name="orphan-attempt-output.pdf",
        )
        session.add(output_file)
        await session.flush()
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
            factory=FlowFactory(),
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
async def test_step_result_files_are_attempt_scoped_and_deduplicated(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flows step result files", [model.id])
        assistant = await assistant_factory(
            session,
            "Step result file assistant",
            model.id,
            space_id=space.id,
        )
        generated_file = _file(
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            name="generated.pdf",
        )
        artifact_file = _file(
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            name="artifact.pdf",
        )
        purged_file = _file(
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            name="purged.pdf",
            text=None,
        )
        session.add_all([generated_file, artifact_file, purged_file])
        await session.flush()
        generated_file_id = generated_file.id
        artifact_file_id = artifact_file.id
        purged_file_id = purged_file.id

        flow_repo = FlowRepository(session=session, factory=FlowFactory())
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

        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
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
            celery_task_id="result-files-attempt-3",
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
            celery_task_id="result-files-attempt-4",
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
    assert [item.file_id for item in listed_files_for_runs] == [
        item.file_id for item in listed_files
    ]
    assert artifact_projection is not None
    assert artifact_projection.availability == "available"
    assert artifact_projection.checksum == "checksum-artifact.pdf"
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
    setup_database,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    target_status,
    target_step_status,
    target_attempt_status,
):
    async with sessionmanager.session() as setup_session, setup_session.begin():
        late_file = _file(
            user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            name=f"late-{target_status.value}.pdf",
        )
        setup_session.add(late_file)
        await setup_session.flush()
        late_file_id = late_file.id
        flow, step, run, run_repo = await _create_running_step_file_flow(
            session=setup_session,
            admin_user=admin_user,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
        )

    async with sessionmanager.session() as terminal_session, terminal_session.begin():
        run_repo = FlowRunRepository(session=terminal_session, factory=FlowFactory())
        terminalizer = FlowRunTerminalizer(
            run_repo,
            FlowRunRerunRepository(
                session=run_repo.session,
                factory=run_repo.factory,
            ),
            run_repo.audit_outbox_repo,
            FlowRunReviewCheckpointRepository(
                session=run_repo.session,
                factory=run_repo.factory,
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
        late_save = await FlowRunRepository(
            session=late_session, factory=FlowFactory()
        ).save_step_result(
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
