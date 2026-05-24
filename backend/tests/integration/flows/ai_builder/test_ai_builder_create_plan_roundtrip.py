from __future__ import annotations

from uuid import UUID

import pytest

from intric.flows.ai_builder.ai_builder_domain_models import (
    PlannerPlanEnvelope,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    StepSpec,
)
from intric.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)

pytestmark = pytest.mark.integration


async def _create_space(*, db_container, space_name: str) -> UUID:
    from intric.database.tables.spaces_table import Spaces

    async with db_container() as container:
        session = container.session()
        user = container.user()
        space = Spaces(name=space_name, tenant_id=user.tenant_id, user_id=user.id)
        session.add(space)
        await session.flush()
        return space.id


def _make_spec(flow_name: str = "Create plan roundtrip") -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name=flow_name,
        flow_description="Repository round-trip test.",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Summarize text",
                assistant_spec=AssistantSpec(
                    instructions="Write a short summary.",
                ),
                input_source=InputSource.FLOW_INPUT,
            )
        ],
    )


@pytest.mark.asyncio
async def test_create_plan_roundtrips_spec_json_and_envelope_metadata(
    db_container,
) -> None:
    space_id = await _create_space(
        db_container=db_container,
        space_name="AI Builder create_plan roundtrip",
    )
    spec = _make_spec("Canonical create_plan spec")
    expected_spec_json = spec.model_dump(mode="json")

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=space_id,
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        plan = await repo.create_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            spec=spec,
            envelope=PlannerPlanEnvelope(
                spec=spec,
                assumptions=["Runtime input is plain text."],
                risk_acknowledgments=["Summary is not fact-checked."],
                reasoning="Use a single text step.",
                plan_rationale="Direct repository round-trip.",
            ),
        )

    assert plan.session_id == session.id
    assert plan.tenant_id == user.tenant_id
    assert plan.status.value == "proposed"

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        fetched = await repo.get_plan(plan_id=plan.id, tenant_id=user.tenant_id)

    assert fetched.id == plan.id
    assert fetched.resource_bindings == tuple()
    assert fetched.spec.model_dump(mode="json") == expected_spec_json
    assert fetched.envelope.assumptions == ["Runtime input is plain text."]
    assert fetched.envelope.risk_acknowledgments == ["Summary is not fact-checked."]
    assert fetched.envelope.reasoning == "Use a single text step."
    assert fetched.envelope.plan_rationale == "Direct repository round-trip."
    assert fetched.envelope.spec.model_dump(mode="json") == expected_spec_json


@pytest.mark.asyncio
async def test_create_plan_roundtrips_resource_bindings_json(db_container) -> None:
    space_id = await _create_space(
        db_container=db_container,
        space_name="AI Builder resource binding roundtrip",
    )
    local_model_id = UUID("11111111-1111-4111-8111-111111111111")
    binding = LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind.MODEL,
            slot="fast-model",
            label="Fast model",
        ),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=local_model_id,
    )
    spec = FlowDraftSpecCore(
        flow_name="Resource binding roundtrip",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Use selected model",
                assistant_spec=AssistantSpec(
                    instructions="Use the selected model.",
                    model_ref="model.fast-model",
                ),
                input_source=InputSource.FLOW_INPUT,
            )
        ],
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=space_id,
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )
        plan = await repo.create_plan(
            session_id=session.id,
            tenant_id=user.tenant_id,
            spec=spec,
            envelope=PlannerPlanEnvelope(spec=spec),
            resource_bindings=(binding,),
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        fetched = await repo.get_plan(plan_id=plan.id, tenant_id=user.tenant_id)

    assert fetched.resource_bindings == (binding,)
