"""Integration tests for the materialization-bridge write path.

The bridge's write-path helper ``apply_to_draft`` wraps the pure
``materialize`` output in a ``PlannerPlanEnvelope`` and persists the
spec via ``AIBuilderRepository.create_plan``. The contract this suite
pins is that the full cycle — materialize → apply_to_draft → get_plan
— round-trips byte-identically: what the compiler produced lands on
the ``builder_plans`` row unchanged, including through the JSON
serialization the repo uses for ``spec_json``.

This is the single end-to-end test chaining every bridge layer from
planner envelope validation through compile, compiled-spec validator,
and persistence. The LLM and planner machinery are out of scope for
the bridge itself; the integration-test harness for planner-driven
acceptance lives in ``test_ai_builder_orchestrator_v2.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest

from intric.flows.ai_builder.ai_builder_draft_plan import DraftPlanEnvelope
from intric.flows.ai_builder.ai_builder_materialization_bridge import (
    apply_to_draft,
    materialize,
)
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    PlannerPlanEnvelope,
    StepSpec,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.planning_state import ArchitectureCommit, StepTriple
from intric.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)

pytestmark = pytest.mark.integration


def _architecture_commit() -> ArchitectureCommit:
    return ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            ),
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=["summarize_text"],
        committed_at=datetime(2026, 4, 24, 12, 0, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )


def _envelope() -> DraftPlanEnvelope:
    return DraftPlanEnvelope(
        plan_id="plan_apply_to_draft_roundtrip",
        steps=[
            {
                "name": "Summarize the provided text",
                "instructions": "Skriv en kort sammanfattning av texten.",
                "input_source": "flow_input",
                "input_type": "text",
                "output_type": "text",
            },
        ],
        form_fields=[],
    )


async def _create_space(*, db_container: Any, space_name: str) -> UUID:
    """User-scoped Space so we dodge ``idx_unique_org_space_per_tenant``.

    The bridge write path only needs a valid ``space_id`` to create a
    builder session; it doesn't touch completion-model associations.
    """
    from intric.database.tables.spaces_table import Spaces

    async with db_container() as container:
        session = container.session()
        user = container.user()
        space = Spaces(name=space_name, tenant_id=user.tenant_id, user_id=user.id)
        session.add(space)
        await session.flush()
        return space.id


@pytest.mark.asyncio
async def test_apply_to_draft_persists_materialized_spec_byte_identical(
    db_container,
) -> None:
    """materialize → apply_to_draft → get_plan must round-trip the spec
    byte-identically.

    ``builder_plans.spec_json`` is the single source of truth for the
    compiled spec; the envelope stores metadata only (the
    ``20260421_builder_envelope_slim`` migration enforces that). This
    test proves the write path preserves the compiler's output without
    field drift, normalization-after-persist, or JSON round-trip lossy
    coercion.
    """
    space_id = await _create_space(
        db_container=db_container,
        space_name="AI Builder apply_to_draft roundtrip",
    )
    materialized = materialize(
        architecture_commit=_architecture_commit(),
        draft_plan=_envelope(),
        flow_name="Summarisation flow",
        flow_description="End-to-end apply_to_draft integration test.",
        plan_rationale="Round-trip materialized spec through create_plan.",
    )
    expected_spec_json = materialized.spec.model_dump(mode="json")

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

        plan = await apply_to_draft(
            repo=repo,
            session_id=session.id,
            tenant_id=user.tenant_id,
            materialized=materialized,
            assumptions=["Runtime input is a plain text buffer."],
            risk_acknowledgments=["Summaries are not fact-checked."],
            reasoning="Chose summarize_text because single-step text→text.",
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
    # Envelope metadata survives the round-trip; spec field on the
    # rehydrated envelope matches the original (re-injected from
    # spec_json per the slim-envelope migration).
    assert fetched.envelope.plan_rationale == (
        "Round-trip materialized spec through create_plan."
    )
    assert fetched.envelope.assumptions == ["Runtime input is a plain text buffer."]
    assert fetched.envelope.risk_acknowledgments == ["Summaries are not fact-checked."]
    assert fetched.envelope.reasoning == (
        "Chose summarize_text because single-step text→text."
    )
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
                name="Use model",
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
    assert fetched.resource_bindings[0].slot_ref.label == "Fast model"
