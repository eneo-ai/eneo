"""Two focused prompt edits on a real 17-step flow keep everything else.

The fixture is an exported municipal flow (Genomförandeplan IBIC V3.1.1):
17 steps, 5 form fields, review checkpoints, knowledge references, nested
JSON contracts on steps 3 to 13 and two render_verbatim PDF steps. The
journey under test is the one a package import leads to: a saved-step edit
on one step, then a plan-step edit on another against the proposal the
first produced. The compiler must keep the 15 untouched steps byte for
byte and the two edited prompts must lose nothing but the clause asked for.

This proves the compiler, the protection and the scope rules over the real
spec. It does not prove that a model preserves clauses when it rewrites an
instruction; that is measured separately, with a provider.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.flow_packages.infrastructure.flow_package_zip_reader import read_flow_package
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_edit_compiler import (
    canonicalize_saved_revision_spec,
)
from eneo.flows.ai_builder.ai_builder_edit_proposal import process_edit_arguments
from eneo.flows.ai_builder.ai_builder_plan_edit_context import (
    AIBuilderPlanEditContext,
    AIBuilderSavedFlowStepEditContext,
    ResolvedAIBuilderEditContext,
    existing_step_ref_for_order,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import (
    CorrectableFailure,
    ProposalReady,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from eneo.flows.domain.canonical_json_hash import canonical_json_bytes
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore
from eneo.main.exceptions import BadRequestException
from tests.unittests.flows.ai_builder.proposal_turn_builders import _make_turn

PACKAGE = Path(__file__).parents[3] / "fixtures/genomforandeplan_ibic_v3_1_1.eneopkg"


def _saved_spec() -> FlowDraftSpecCore:
    """The package's draft as the saved flow's authoring spec: one existing
    step ref per saved step, as the snapshot builder assigns them."""
    spec = read_flow_package(PACKAGE.read_bytes()).draft.spec
    # current_flow_authoring_spec names a saved step by its existing ref in
    # both places, and the revision baseline is the canonical form of that
    # (plan refs step_a.., runtime aliases in bindings rewritten to them),
    # exactly as _prior_spec_for_revision hands it to the compiler.
    return canonicalize_saved_revision_spec(
        spec.model_copy(
            update={
                "steps": [
                    step.model_copy(
                        update={
                            "plan_step_ref": existing_step_ref_for_order(order),
                            "existing_step_ref": existing_step_ref_for_order(order),
                        }
                    )
                    for order, step in enumerate(spec.steps, 1)
                ]
            }
        )
    )


def _flow(spec: FlowDraftSpecCore) -> SimpleNamespace:
    flow_id = uuid4()
    return SimpleNamespace(
        id=flow_id,
        draft_revision=7,
        name=spec.flow_name,
        description=spec.flow_description,
        metadata_json={},
        steps=[
            FlowStep(
                id=uuid4(),
                flow_id=flow_id,
                tenant_id=uuid4(),
                assistant_id=uuid4(),
                step_order=order,
                user_description=step.name,
                input_source=step.input_source,
                input_type=step.input_type,
                output_mode=step.output_mode,
                output_type=step.output_type,
            )
            for order, step in enumerate(spec.steps, 1)
        ],
    )


async def _propose(
    *,
    flow: SimpleNamespace,
    context: ResolvedAIBuilderEditContext,
    prior: FlowDraftSpecCore,
    steps: list[dict[str, object]],
    removed: list[str] | None = None,
):
    arguments: dict[str, object] = {
        "plan_rationale": "Ändra bara den valda instruktionen.",
        "steps": steps,
    }
    if removed is not None:
        arguments["removed_existing_step_refs"] = removed
    return await process_edit_arguments(
        turn=_make_turn(),
        conversation=[],
        arguments=arguments,
        available_model_refs=None,
        available_kb_refs=None,
        flow=flow,
        assistant_snapshots=None,
        resource_catalog=_catalog(prior),
        planning_state=None,
        plan_edit_context=context,
        prior_spec_for_revision=prior,
        compile_context=create_compile_context_from_planning_state(
            None, ui_language="sv"
        ),
    )


def _catalog(spec: FlowDraftSpecCore):
    """The space has the model and knowledge bases the package binds to."""
    model_refs = sorted(
        {
            step.assistant_spec.model_ref
            for step in spec.steps
            if step.assistant_spec.model_ref
        }
    )
    kb_refs = sorted(
        {
            ref
            for step in spec.steps
            for ref in (step.assistant_spec.knowledge_refs or [])
        }
    )
    return build_ai_builder_resource_catalog(
        available_models=[
            {
                "id": str(uuid4()),
                "ref": ref,
                "name": ref.removeprefix("model."),
                "display_name": ref.removeprefix("model."),
                "provider": "local",
            }
            for ref in model_refs
        ],
        available_kbs=[
            {
                "id": str(uuid4()),
                "ref": ref,
                "name": ref.removeprefix("knowledge."),
                "display_name": ref.removeprefix("knowledge."),
                "description": "",
            }
            for ref in kb_refs
        ],
    )


def _bytes(spec: FlowDraftSpecCore) -> list[bytes]:
    return [canonical_json_bytes(step.model_dump(mode="json")) for step in spec.steps]


def _saved_step_context(
    flow: SimpleNamespace, order: int
) -> ResolvedAIBuilderEditContext:
    return ResolvedAIBuilderEditContext(
        request=AIBuilderSavedFlowStepEditContext(
            flow_step_id=flow.steps[order - 1].id
        ),
        scope="step",
        target_existing_step_ref=existing_step_ref_for_order(order),
        target_step_name=flow.steps[order - 1].user_description,
        target_step_number=order,
    )


def _plan_step_context(plan_id, order: int) -> ResolvedAIBuilderEditContext:
    ref = existing_step_ref_for_order(order)
    return ResolvedAIBuilderEditContext(
        request=AIBuilderPlanEditContext(
            scope="step", plan_id=plan_id, target_existing_step_ref=ref
        ),
        scope="step",
        target_existing_step_ref=ref,
        plan_id=plan_id,
    )


def test_the_fixture_is_the_representative_flow():
    spec = _saved_spec()
    assert len(spec.steps) == 17
    assert len(spec.form_fields or []) == 5
    assert [
        order for order, step in enumerate(spec.steps, 1) if step.review_policy
    ] == [
        2,
        3,
        13,
        14,
        16,
    ]
    assert [
        order
        for order, step in enumerate(spec.steps, 1)
        if str(step.output_mode) == "render_verbatim"
        or step.output_mode.value == "render_verbatim"
    ] == [15, 17]
    assert all(step.output_contract for step in spec.steps[2:13])
    assert sum(len(step.assistant_spec.knowledge_refs or []) for step in spec.steps) > 0
    assert (
        sum(len(step.assistant_spec.instructions or "") for step in spec.steps) > 80_000
    )


async def test_two_sequential_focused_edits_keep_the_other_fifteen_steps_byte_for_byte():
    prior = _saved_spec()
    flow = _flow(prior)
    original = _bytes(prior)

    # Turn 1: a saved-step edit on step 3 changes one clause of its prompt.
    step3 = prior.steps[2].assistant_spec.instructions
    clause_old = "Läs hela transkriptet, även slutet, och formulärets uppgifter."
    clause_new = "Läs hela transkriptet, även slutet, formulärets uppgifter och eventuella bilagor."
    assert clause_old in step3
    first = await _propose(
        flow=flow,
        context=_saved_step_context(flow, 3),
        prior=prior,
        steps=[
            {
                "kind": "modify",
                "existing_step_ref": "existing_step_3",
                "assistant_spec": {
                    "instructions": step3.replace(clause_old, clause_new)
                },
            }
        ],
    )
    assert isinstance(first, ProposalReady), first
    after_first = first.compiled.content.spec
    assert len(after_first.steps) == 17
    assert after_first.steps[2].assistant_spec.instructions == step3.replace(
        clause_old, clause_new
    )
    # Every clause outside the requested change survives inside the edited prompt.
    assert step3.replace(clause_old, "") in after_first.steps[
        2
    ].assistant_spec.instructions.replace(clause_new, "")
    for index, before in enumerate(original):
        if index != 2:
            assert (
                canonical_json_bytes(after_first.steps[index].model_dump(mode="json"))
                == before
            )
    assert after_first.form_fields == prior.form_fields

    # Turn 2: a plan-step edit on step 14 against the proposal turn 1 produced.
    plan_id = uuid4()
    step14 = after_first.steps[13].assistant_spec.instructions
    addition = "\nSkriv datum i formatet ÅÅÅÅ-MM-DD."
    second = await _propose(
        flow=flow,
        context=_plan_step_context(plan_id, 14),
        prior=after_first,
        steps=[
            {
                "kind": "modify",
                "existing_step_ref": "existing_step_14",
                "assistant_spec": {"instructions": step14 + addition},
            }
        ],
    )
    assert isinstance(second, ProposalReady), second
    after_second = second.compiled.content.spec
    assert after_second.steps[13].assistant_spec.instructions == step14 + addition
    assert after_second.steps[13].assistant_spec.instructions.startswith(step14)
    # Turn 1's change is still there and the other fifteen are untouched.
    assert after_second.steps[2].assistant_spec.instructions == step3.replace(
        clause_old, clause_new
    )
    for index, before in enumerate(original):
        if index not in (2, 13):
            assert (
                canonical_json_bytes(after_second.steps[index].model_dump(mode="json"))
                == before
            )
    # The saved spec itself was never mutated by either turn.
    assert _bytes(prior) == original


@pytest.mark.parametrize("violation", ["remove", "add", "outside_scope"])
async def test_a_step_scoped_proposal_may_not_remove_add_or_touch_other_steps(
    violation,
):
    prior = _saved_spec()
    flow = _flow(prior)
    context = _saved_step_context(flow, 3)
    if violation == "add":
        try:
            result = await _propose(
                flow=flow,
                context=context,
                prior=prior,
                steps=[
                    {"kind": "modify", "existing_step_ref": "existing_step_3"},
                    {
                        "kind": "add",
                        "step": {
                            "name": "Extra",
                            "assistant_spec": {"instructions": "x"},
                            "input_source": "previous_step",
                        },
                    },
                ],
            )
        except BadRequestException:
            return
        assert not isinstance(result, ProposalReady), result
        return
    result = await _propose(
        flow=flow,
        context=context,
        prior=prior,
        steps=[
            {
                "kind": "modify",
                "existing_step_ref": "existing_step_5"
                if violation == "outside_scope"
                else "existing_step_3",
                "assistant_spec": {"instructions": "Kortare instruktion."},
            }
        ],
        removed=["existing_step_16"] if violation == "remove" else None,
    )
    assert not isinstance(result, ProposalReady), result
    if isinstance(result, CorrectableFailure):
        assert (
            "existing_step_16" in result.feedback
            or "selected" in result.feedback.lower()
        )
