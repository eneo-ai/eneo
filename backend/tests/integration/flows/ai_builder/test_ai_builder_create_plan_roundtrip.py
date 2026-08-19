from __future__ import annotations

import json
from uuid import UUID

import pytest
from sqlalchemy import func, select

from eneo.database.tables.flow_tables import BuilderPlans
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BUILDER_PROPOSAL_PAYLOAD_CAP_BYTES,
    BUILDER_PROPOSAL_SCHEMA_VERSION,
    BuilderProposalPayloadTooLargeError,
    FlowBuilderProposal,
    FlowBuilderProposalContent,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    StepSpec,
)
from eneo.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)

pytestmark = pytest.mark.integration


async def _create_space(*, db_container, space_name: str) -> UUID:
    from eneo.database.tables.spaces_table import Spaces

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


def _proposal_with_serialized_size(byte_size: int) -> FlowBuilderProposal:
    proposal = FlowBuilderProposal(
        content=FlowBuilderProposalContent(
            spec=_make_spec(),
            plan_rationale="",
        )
    )
    empty_payload = proposal.model_dump(
        mode="json",
        exclude_none=True,
        round_trip=True,
    )
    empty_size = len(
        json.dumps(
            empty_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert empty_size < byte_size
    proposal.content.plan_rationale = "x" * (byte_size - empty_size)
    return proposal


@pytest.mark.asyncio
async def test_create_plan_roundtrips_proposal_json(
    db_container,
) -> None:
    space_id = await _create_space(
        db_container=db_container,
        space_name="AI Builder create_plan roundtrip",
    )
    spec = _make_spec("Canonical create_plan spec")
    proposal = FlowBuilderProposal(
        content=FlowBuilderProposalContent(
            spec=spec,
            assumptions=["Runtime input is plain text."],
            plan_rationale="Direct repository round-trip.",
        ),
    )
    expected_spec_json = spec.model_dump(mode="json")
    expected_stored_spec_json = proposal.storage_json()["content"]["spec"]

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
            proposal=proposal,
        )
        stored_plan = await container.session().get(BuilderPlans, plan.id)
        assert stored_plan is not None
        stored_proposal_json = stored_plan.proposal_json

    assert plan.session_id == session.id
    assert plan.tenant_id == user.tenant_id
    assert plan.status.value == "proposed"
    assert set(stored_proposal_json) == {
        "schema_version",
        "content",
        "resource_bindings",
    }
    assert stored_proposal_json["schema_version"] == BUILDER_PROPOSAL_SCHEMA_VERSION
    assert stored_proposal_json["content"]["spec"] == expected_stored_spec_json
    assert stored_proposal_json["content"]["assumptions"] == [
        "Runtime input is plain text."
    ]
    assert "risk_acknowledgments" not in stored_proposal_json["content"]
    assert "reasoning" not in stored_proposal_json
    assert (
        stored_proposal_json["content"]["plan_rationale"]
        == "Direct repository round-trip."
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        fetched = await repo.get_plan(plan_id=plan.id, tenant_id=user.tenant_id)

    assert fetched.id == plan.id
    assert fetched.resource_bindings == tuple()
    assert fetched.spec.model_dump(mode="json") == expected_spec_json
    assert fetched.proposal.spec.model_dump(mode="json") == expected_spec_json
    assert fetched.proposal.content.assumptions == ["Runtime input is plain text."]
    assert "risk_acknowledgments" not in type(fetched.proposal.content).model_fields
    assert "reasoning" not in type(fetched.proposal).model_fields
    assert fetched.proposal.content.plan_rationale == "Direct repository round-trip."
    assert fetched.proposal.content.spec.model_dump(mode="json") == expected_spec_json
    assert fetched.proposal.schema_version == BUILDER_PROPOSAL_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_create_plan_enforces_proposal_size_before_insert(
    db_container,
) -> None:
    space_id = await _create_space(
        db_container=db_container,
        space_name="AI Builder proposal size boundary",
    )
    at_cap = _proposal_with_serialized_size(BUILDER_PROPOSAL_PAYLOAD_CAP_BYTES)
    over_cap = _proposal_with_serialized_size(BUILDER_PROPOSAL_PAYLOAD_CAP_BYTES + 1)

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
            proposal=at_cap,
        )
        with pytest.raises(BuilderProposalPayloadTooLargeError) as exc:
            await repo.create_plan(
                session_id=session.id,
                tenant_id=user.tenant_id,
                proposal=over_cap,
            )
        plan_count = await container.session().scalar(
            select(func.count(BuilderPlans.id)).where(
                BuilderPlans.session_id == session.id,
                BuilderPlans.tenant_id == user.tenant_id,
            )
        )
        stored_plan = await container.session().get(BuilderPlans, plan.id)
        assert stored_plan is not None
        stored_proposal_json = stored_plan.proposal_json

    assert exc.value.byte_size == BUILDER_PROPOSAL_PAYLOAD_CAP_BYTES + 1
    assert exc.value.cap_bytes == BUILDER_PROPOSAL_PAYLOAD_CAP_BYTES
    assert plan_count == 1
    assert stored_proposal_json["schema_version"] == BUILDER_PROPOSAL_SCHEMA_VERSION


@pytest.mark.asyncio
async def test_create_plan_roundtrips_document_body_writer_refs(
    db_container,
) -> None:
    space_id = await _create_space(
        db_container=db_container,
        space_name="AI Builder document body writer ref roundtrip",
    )
    spec = FlowDraftSpecCore(
        flow_name="Document writer refs",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extract",
                assistant_spec=AssistantSpec(instructions="Extract facts."),
                input_source=InputSource.FLOW_INPUT,
            ),
            StepSpec(
                plan_step_ref="step_b",
                name="Write report body",
                assistant_spec=AssistantSpec(instructions="Write the report."),
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
        document_body_writer_step_refs=("step_b",),
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
            proposal=FlowBuilderProposal(
                content=FlowBuilderProposalContent(spec=spec),
            ),
        )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        fetched = await repo.get_plan(plan_id=plan.id, tenant_id=user.tenant_id)

    assert fetched.spec.document_body_writer_step_refs == ("step_b",)
    assert fetched.spec.model_dump(mode="json") == spec.model_dump(mode="json")
    assert fetched.spec_hash == fetched.spec.spec_hash()


@pytest.mark.asyncio
async def test_create_plan_roundtrips_resource_bindings_in_proposal_json(
    db_container,
) -> None:
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
    expected_proposal_json = FlowBuilderProposal(
        content=FlowBuilderProposalContent(spec=spec),
        resource_bindings=(binding,),
    ).storage_json()

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
            proposal=FlowBuilderProposal(
                content=FlowBuilderProposalContent(spec=spec),
                resource_bindings=(binding,),
            ),
        )
        stored_plan = await container.session().get(BuilderPlans, plan.id)
        assert stored_plan is not None
        stored_proposal_json = stored_plan.proposal_json

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        fetched = await repo.get_plan(plan_id=plan.id, tenant_id=user.tenant_id)

    assert (
        stored_proposal_json["resource_bindings"]
        == expected_proposal_json["resource_bindings"]
    )
    assert fetched.resource_bindings == (binding,)
