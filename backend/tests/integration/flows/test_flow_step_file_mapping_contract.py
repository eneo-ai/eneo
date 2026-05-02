from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.database.tables.files_table import Files
from intric.database.tables.flow_tables import (
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
)
from intric.flows import (
    Flow,
    FlowFactory,
    FlowRepository,
    FlowStep,
    FlowVersionRepository,
)
from intric.flows.domain.flow import FlowStepResult
from intric.flows.flow import FlowStepResultStatus
from intric.flows.infrastructure.flow_run_repo import FlowRunRepository
from intric.flows.published_definition import FLOW_DEFINITION_SCHEMA_VERSION


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
        owner_api_key_id=None,
        user_id=user_id,
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
        definition_checksum=f"checksum-{flow.id}",
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


@pytest.mark.asyncio
@pytest.mark.integration
async def test_step_inputs_snapshot_matches_input_file_projection(
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
        flow = flow.model_copy(update={"published_version": 1})
        flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)
        await _create_version(
            session=session,
            flow=flow,
            tenant_id=admin_user.tenant_id,
        )
        step = flow.steps[0]

        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
            principal_user_id=admin_user.id,
            tenant_id=admin_user.tenant_id,
            input_payload_json={
                "expected_flow_version": 1,
                "step_inputs": {
                    str(step.id): {
                        "file_ids": [str(input_file_a.id), str(input_file_b.id)]
                    }
                },
            },
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

    assert run_payload == {
        "expected_flow_version": 1,
        "step_inputs": {
            str(step_id): {"file_ids": [str(input_file_a_id), str(input_file_b_id)]}
        },
    }
    assert step_input_rows == [
        (step_id, input_file_a_id, 0),
        (step_id, input_file_b_id, 1),
    ]
    assert historical_top_level_count == 0


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
        flow = flow.model_copy(update={"published_version": 1})
        flow = await flow_repo.update(flow=flow, tenant_id=admin_user.tenant_id)
        await _create_version(
            session=session,
            flow=flow,
            tenant_id=admin_user.tenant_id,
        )
        step = flow.steps[0]

        run_repo = FlowRunRepository(session=session, factory=FlowFactory())
        run = await run_repo.create(
            flow_id=flow.id,
            flow_version=1,
            user_id=admin_user.id,
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
                "generated_file_ids": [str(generated_file_id), str(artifact_file_id)],
                "artifacts": [
                    {"file_id": str(artifact_file_id), "kind": "pdf"},
                ],
            },
            model_parameters_json={},
            num_tokens_input=1,
            num_tokens_output=1,
            status=FlowStepResultStatus.COMPLETED,
            error_message=None,
            flow_step_execution_hash="hash",
            tool_calls_metadata=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await flow_repo.save_step_result(
            run.id,
            result,
            tenant_id=admin_user.tenant_id,
            attempt_no=3,
        )
        retry_result = result.model_copy(
            update={
                "output_payload_json": {
                    "text": "retry output",
                    "generated_file_ids": [str(purged_file_id)],
                },
            }
        )
        await flow_repo.save_step_result(
            run.id,
            retry_result,
            tenant_id=admin_user.tenant_id,
            attempt_no=4,
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
    assert artifact_projection is not None
    assert artifact_projection.availability == "available"
    assert artifact_projection.checksum == "checksum-artifact.pdf"
    assert purged_projection is not None
    assert purged_projection.availability == "content_purged"
    assert cross_tenant_projection is None
