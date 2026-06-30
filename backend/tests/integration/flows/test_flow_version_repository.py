from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from intric.flows import FlowFactory, FlowRepository, FlowVersionRepository
from intric.flows.domain.flow import Flow, FlowPersistedJsonObject, FlowStep
from intric.flows.published_definition import (
    build_published_definition_json,
    published_definition_checksum,
)


def _flow(
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
) -> Flow:
    return Flow(
        id=None,
        tenant_id=tenant_id,
        space_id=space_id,
        name="Versioned Flow",
        description=None,
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json=None,
        data_retention_days=None,
        created_at=None,
        updated_at=None,
        steps=[
            FlowStep(
                id=None,
                flow_id=None,
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=1,
                user_description="Persist version",
                input_source="flow_input",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
                mcp_policy="inherit",
            )
        ],
    )


def _definition_json(
    *,
    flow: Flow,
    step: FlowStep,
    output_config: dict[str, str] | None = None,
) -> FlowPersistedJsonObject:
    assert flow.id is not None
    assert step.id is not None
    return build_published_definition_json(
        flow_id=flow.id,
        name=flow.name,
        description=flow.description,
        metadata_json=flow.metadata_json,
        steps=[
            {
                "step_id": str(step.id),
                "assistant_id": str(step.assistant_id),
                "step_order": step.step_order,
                "input_source": step.input_source,
                "input_type": step.input_type,
                "output_mode": step.output_mode,
                "output_type": step.output_type,
                "mcp_policy": step.mcp_policy,
                "output_config": output_config,
            }
        ],
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_derives_definition_checksum_from_stored_definition(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(session, "Flow version repository", [model.id])
        assistant = await assistant_factory(
            session,
            "Flow Version Assistant",
            model.id,
            space_id=space.id,
        )
        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        step = flow.steps[0]
        assert flow.id is not None
        assert step.id is not None
        definition_json = build_published_definition_json(
            flow_id=flow.id,
            name=flow.name,
            description=flow.description,
            metadata_json=flow.metadata_json,
            steps=[
                {
                    "step_id": str(step.id),
                    "assistant_id": str(step.assistant_id),
                    "step_order": step.step_order,
                    "input_source": step.input_source,
                    "input_type": step.input_type,
                    "output_mode": step.output_mode,
                    "output_type": step.output_type,
                    "mcp_policy": step.mcp_policy,
                }
            ],
        )

        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_json=definition_json,
            tenant_id=admin_user.tenant_id,
        )

        stored_version = await version_repo.get(
            flow_id=flow.id,
            version=1,
            tenant_id=admin_user.tenant_id,
        )

        assert stored_version.definition_checksum == published_definition_checksum(
            definition_json
        )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_template_asset_reference_check_scans_non_current_versions(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(session, "gpt-4o-mini")
        space = await space_factory(
            session, "Flow version template reference", [model.id]
        )
        assistant = await assistant_factory(
            session,
            "Flow Version Template Assistant",
            model.id,
            space_id=space.id,
        )
        flow_repo = FlowRepository(session=session, factory=FlowFactory())
        version_repo = FlowVersionRepository(session=session, factory=FlowFactory())
        flow = await flow_repo.create(
            flow=_flow(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                user_id=admin_user.id,
                assistant_id=assistant.id,
            ),
            tenant_id=admin_user.tenant_id,
        )
        step = flow.steps[0]
        assert flow.id is not None
        template_asset_id = uuid4()
        template_file_id = uuid4()

        await version_repo.create(
            flow_id=flow.id,
            version=1,
            definition_json=_definition_json(
                flow=flow,
                step=step,
                output_config={
                    "template_asset_id": str(template_asset_id),
                    "template_file_id": str(template_file_id),
                },
            ),
            tenant_id=admin_user.tenant_id,
        )
        await version_repo.create(
            flow_id=flow.id,
            version=2,
            definition_json=_definition_json(flow=flow, step=step),
            tenant_id=admin_user.tenant_id,
        )

        assert await version_repo.has_template_asset_reference(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            template_asset_id=template_asset_id,
            template_file_id=template_file_id,
        )
        assert not await version_repo.has_template_asset_reference(
            flow_id=flow.id,
            tenant_id=admin_user.tenant_id,
            template_asset_id=uuid4(),
            template_file_id=uuid4(),
        )
