"""Edit turns on a saved flow whose steps read MCP tools, in a space whose
tools the turn does not name.

A tool step is then carried as saved and never changed by the Builder: a turn
that targets one is refused, every other turn keeps its tool and fixed values,
and its bound arguments are reads that the final flow's validation and the
write judge like any other read. (With tools named, an edit may write a tool
step's tool use: test_ai_builder_tool_steps.)
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    metadata_for_user_message,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from eneo.flows.ai_builder.ai_builder_edit_compiler import compile_edit_proposal
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
)
from eneo.flows.ai_builder.ai_builder_flow_context import build_flow_context
from eneo.flows.ai_builder.ai_builder_flow_review import (
    AIBuilderRunFailureContext,
    repair_message,
)
from eneo.flows.ai_builder.ai_builder_new_step_models import StructuredFieldDraft
from eneo.flows.ai_builder.ai_builder_planner_request_preparation import (
    ProposalPrepared,
    SavedStepsNotEditablePrepared,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    AddStep,
    AssistantSpecPatch,
    ModifyExistingStep,
    OrderedEditProposal,
    SemanticStepIntent,
)
from eneo.flows.ai_builder.ai_builder_step_transition_policy import (
    normalize_ai_builder_spec,
)
from eneo.flows.ai_builder.ai_builder_validation_common import SpecValidationResult
from eneo.flows.application.flow_authoring_snapshot import UnsupportedSavedStepsError
from eneo.flows.application.flow_draft_materialization import (
    FlowDraftChangeSet,
    compile_flow_draft_changeset,
)
from eneo.flows.assistant_authoring_snapshot import AssistantAuthoringSnapshot
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore
from tests.unittests.flows.ai_builder.test_ai_builder_planner import (
    _document_architecture_state,
    _make_planner,
    _prepare_planner_request_for_test,
    _repair_handoff,
    _reviewed_flow,
    _route,
)
from tests.unittests.flows.ai_builder.test_ai_builder_unsupported_saved_steps import (
    _build,
    _flow,
    _scoped_to,
    _step,
)

S1, S2, S3, S4 = (f"existing_step_{order}" for order in range(1, 5))
SERVER = UUID("8f2f0a2e-51f5-4c53-9d0c-0c1a2b3c4d5e")
DAYS = "{{step_1.output.structured.anomaly_days}}"


def _contract(*fields: str) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            name: {"type": "array", "items": {"type": "string"}} for name in fields
        },
        "required": list(fields),
    }


def _tool(order: int, arguments: dict[str, object], *out: str) -> FlowStep:
    return _step(
        order,
        input_source="tool",
        input_type="json",
        output_type="json",
        output_contract=_contract(*out) if out else None,
        input_config={
            "tool": {
                "mcp_server_id": str(SERVER),
                "tool_id": str(uuid4()),
                "arguments": arguments,
            }
        },
    )


def _seab(first: FlowStep | None = None) -> Flow:
    """Steps 1-2 read tools, step 2 for the days step 1 found; 3 analyses, 4 reports.
    `first` replaces the first tool with an ordinary step that finds the days."""

    return _flow(
        first or _tool(1, {"from": "2026-09-01", "to": "2026-09-30"}, "anomaly_days"),
        _tool(2, {"days": DAYS, "limit": 50}),
        _step(3, input_type="json"),
        _step(4),
    )


def _apply(
    flow: Flow,
    *steps: ModifyExistingStep | AddStep,
    removed: frozenset[str] = frozenset(),
    prompts: Mapping[int, str] | None = None,
) -> tuple[SpecValidationResult, FlowDraftChangeSet]:
    """The edit as the Builder prepares it, and the changeset its apply writes.
    `prompts` replaces the saved instructions of the steps it numbers."""

    compiled = compile_edit_proposal(
        OrderedEditProposal(
            plan_rationale="Edit.",
            steps=list(steps),
            removed_existing_step_refs=removed,
        ),
        flow.steps,
        base_flow_revision=1,
        flow_name=flow.name,
        assistant_snapshots={
            step.assistant_id: AssistantAuthoringSnapshot(
                instructions=(prompts or {}).get(
                    step.step_order, f"Gör {step.step_order}."
                )
            )
            for step in flow.steps
        },
    )
    prepared = asyncio.run(
        prepare_compiled_spec_for_session(
            spec=compiled.spec,
            target_kind=TargetKind.EDIT,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
            mutation_scope=compiled.mutation_scope,
        )
    )
    assert prepared.spec is not None and prepared.validation is not None
    changes = compiled.approval_for_prepared_spec(prepared.spec).diff.step_changes
    modified = {change.step_ref for change in changes if change.kind == "modified"}
    changeset = compile_flow_draft_changeset(
        prepared.spec,
        flow,
        removed_existing_step_refs=removed,
        updated_existing_step_refs=frozenset(ref for ref in modified if ref),
        updated_step_fields={},
    )
    return prepared.validation, changeset


def _keep(*refs: str) -> list[ModifyExistingStep]:
    return [ModifyExistingStep(existing_step_ref=ref) for ref in refs]


def test_an_edit_of_the_report_keeps_both_tool_steps_as_saved() -> None:
    # Kills: a normalizer or the diff rewriting a kept tool step's config; a
    # repair asked for the contract of a tool step no edit may change.
    flow = _seab()
    validation, changeset = _apply(
        flow,
        *_keep(S1, S2, S3),
        ModifyExistingStep(
            existing_step_ref=S4,
            assistant_spec=AssistantSpecPatch(instructions="Kortare."),
        ),
    )

    assert (validation.errors, validation.warnings) == ([], [])
    assert [step.input_config for step in changeset.compiled_steps[:2]] == [
        step.input_config for step in flow.steps[:2]
    ]


def test_moving_the_producer_rewrites_the_bound_argument_to_follow_it() -> None:
    # Kills: tool arguments left out of the edit's alias canonicalization (the
    # validator then reads step_1 as the added step) or out of the renumbering.
    flow = _seab()

    validation, changeset = _apply(
        flow,
        AddStep(step=SemanticStepIntent(name="Förbered", instructions="Förbered.")),
        *_keep(S1, S2, S3, S4),
    )

    assert validation.errors == []
    first_tool, second_tool = changeset.compiled_steps[1:3]
    assert first_tool.input_config == flow.steps[0].input_config
    assert second_tool.input_config == json.loads(
        json.dumps(flow.steps[1].input_config).replace(DAYS, DAYS.replace("_1", "_2"))
    )


def _finder() -> FlowStep:
    return _step(
        1,
        input_type="text",
        output_type="json",
        output_contract=_contract("anomaly_days"),
    )


def test_an_edit_that_drops_the_field_a_tool_argument_reads_is_not_valid() -> None:
    # Kills: tool arguments missing from the Builder's template sites, so the
    # final-flow validation cannot see the read.
    validation, _ = _apply(
        _seab(_finder()),
        ModifyExistingStep(
            existing_step_ref=S1,
            output_fields=[
                StructuredFieldDraft(
                    name="summary", field_type="string", description="S."
                )
            ],
        ),
        *_keep(S2, S3, S4),
    )

    assert [error.code for error in validation.errors] == [
        "unknown_output_contract_field"
    ]


def _failure_handoff(step_order: int) -> ConversationMessage:
    return ConversationMessage(
        role="user",
        content=repair_message(step_order),
        metadata=metadata_for_user_message(
            review_context=AIBuilderRunFailureContext(
                flow_version=1,
                definition_checksum="sum",
                run_id=uuid4(),
                step_order=step_order,
            ),
            review_evidence_level=3,
            acts_on_review=True,
        ),
    )


@pytest.mark.parametrize("handoff", [False, True], ids=["scoped_step", "run_failure"])
def test_a_turn_that_targets_only_a_tool_step_is_answered_not_proposed(
    handoff: bool,
) -> None:
    # Kills: a scoped turn or a run-failure handoff on a tool step reaching the
    # model, which may only keep that step.
    flow = _seab()

    with pytest.raises(UnsupportedSavedStepsError) as caught:
        if handoff:
            _build(flow, None, turn=_failure_handoff(2))
        else:
            _build(flow, _scoped_to(flow.steps[1]))
    assert [step.step_order for step in caught.value.steps] == [2]


@pytest.mark.asyncio
async def test_a_tool_step_with_an_unusable_configuration_is_answered_not_proposed() -> (
    None
):
    # Kills: the edit context raising on the configuration before the typed
    # answer; an edit asking the model to repair a step it may only keep.
    flow = _reviewed_flow()
    flow.steps += [
        _step(3, input_source="tool", input_type="json", output_type="json"),
        _step(4, input_type="json"),
    ]
    handoff, evidence, scope = _repair_handoff(flow)

    prepared = await _prepare_planner_request_for_test(
        _make_planner(),
        conversation=[handoff],
        completion_model_route=_route(),
        persisted_planning_state=_document_architecture_state(),
        flow=flow,
        plan_edit_context=scope,
        review_evidence=evidence,
    )

    assert isinstance(prepared, SavedStepsNotEditablePrepared)
    assert isinstance(prepared.error, UnsupportedSavedStepsError)
    assert [step.step_order for step in prepared.error.steps] == [3]


def _named(order: int, name: str, **fields: object) -> FlowStep:
    return _step(order, user_description=name, input_type="text", **fields)


@pytest.mark.parametrize(
    ("site", "name"),
    [
        ("argument", "Original"),
        ("argument", "existing_step_3"),
        ("instructions", "Original"),
    ],
)
def test_a_kept_tool_step_keeps_the_producer_each_read_names(
    site: str, name: str
) -> None:
    # Kills: a step name binding read as an unknown reference; a read of a
    # kept tool step, at any template site, that names its producer by name
    # silently reading another step after the producer is removed and another
    # step takes its name; a compiler ref (existing_step_3) read in place of
    # the name the run binds.
    read = f"{{{{{name}}}}}"
    # A tool step holds no underlag (input_bindings): the step graph refuses it.
    tool = _tool(4, {"q": read if site == "argument" else "fast"})
    flow = _flow(
        _step(1), _named(2, name), _named(3, "Other"), tool, _named(5, "Rapport")
    )
    prompts = {4: f"Använd {read}."} if site == "instructions" else None
    report = ModifyExistingStep(
        existing_step_ref="existing_step_5",
        assistant_spec=AssistantSpecPatch(instructions="Ny."),
    )

    kept, _ = _apply(flow, *_keep(S1, S2, S3, S4), report, prompts=prompts)
    retargeted, _ = _apply(
        flow,
        *_keep(S1),
        ModifyExistingStep(existing_step_ref=S3, name=name),
        *_keep(S4, "existing_step_5"),
        removed=frozenset({S2}),
        prompts=prompts,
    )

    assert kept.errors == []
    assert [e.code for e in retargeted.errors] == ["kept_step_read_retargeted"]


def test_a_tool_read_that_no_producer_fits_is_repaired_at_the_producer() -> None:
    # Kills: refusing before the proposal a read only the producer's edit fixes.
    flow = _seab(
        _step(1, input_type="text", output_type="json", output_contract=_contract("x"))
    )
    assert isinstance(_build(flow, None), ProposalPrepared)

    validation, _ = _apply(
        flow,
        ModifyExistingStep(
            existing_step_ref=S1,
            output_fields=[
                StructuredFieldDraft(
                    name="anomaly_days",
                    field_type="array",
                    description="D.",
                    item_fields=None,
                )
            ],
        ),
        *_keep(S2, S3, S4),
    )

    assert validation.errors == []


def test_no_turn_is_offered_a_change_to_a_tool_step() -> None:
    # Kills: a tool step offered for modify or removal; a step turned into a
    # tool step; the edit context without a tool step's arguments.
    flow = _seab()
    context = build_flow_context(flow, is_edit_mode=True)
    assert f'(kind=keep): argument {{"days": "{DAYS}", "limit": 50}}' in context

    schema = _build(flow, None).proposal_tool_schema["function"]["parameters"]
    modify, keep, _ = schema["properties"]["steps"]["items"]["anyOf"]
    assert modify["properties"]["existing_step_ref"]["enum"] == [S3, S4]
    assert "tool" not in modify["properties"]["input_source"]["enum"]
    assert keep["properties"]["existing_step_ref"]["enum"] == [S1, S2, S3, S4]
    assert schema["properties"]["removed_existing_step_refs"]["items"]["enum"] == [
        S3,
        S4,
    ]


@pytest.mark.parametrize(
    ("steps", "removed"),
    [
        ([*_keep(S1, S3, S4)], frozenset({S2})),
        (
            [
                *_keep(S1),
                ModifyExistingStep(existing_step_ref=S2, name="Ny"),
                *_keep(S3, S4),
            ],
            frozenset(),
        ),
    ],
    ids=["remove", "modify"],
)
def test_a_compiled_change_to_a_tool_step_is_refused(
    steps: list[ModifyExistingStep], removed: frozenset[str]
) -> None:
    # Kills: the keep-only rule resting on the provider's schema alone.
    with pytest.raises(AIBuilderBadRequestException, match="read an MCP tool"):
        _apply(_seab(), *steps, removed=removed)


def test_a_name_another_step_takes_from_a_tool_step_is_suffixed_on_that_step() -> None:
    # Kills: name disambiguation suffixing the tool step; normalization
    # changes to a kept step surviving to the approval.
    flow = _seab(
        _step(
            1,
            input_type="text",
            output_type="json",
            output_contract=_contract("anomaly_days"),
        )
    )
    compiled = compile_edit_proposal(
        OrderedEditProposal(
            plan_rationale="Edit.",
            steps=[
                ModifyExistingStep(existing_step_ref=S1, name="Steg 2"),
                *_keep(S2, S3, S4),
            ],
        ),
        flow.steps,
        base_flow_revision=1,
    )

    prepared = asyncio.run(
        prepare_compiled_spec_for_session(
            spec=compiled.spec,
            target_kind=TargetKind.EDIT,
            available_model_refs=None,
            available_kb_refs=None,
            resource_catalog=None,
            mutation_scope=compiled.mutation_scope,
        )
    ).spec
    assert prepared is not None
    changes = compiled.approval_for_prepared_spec(prepared).diff.step_changes
    assert [step.name for step in prepared.steps[:2]] == ["Steg 2 (2)", "Steg 2"]
    assert [c.step_ref for c in changes if c.kind != "unchanged"] == [S1]


def test_a_normalization_that_touches_a_tool_step_is_undone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Kills: kept steps left out of the mutation scope, so a rewrite by
    # session preparation's normalization reaches the approval and the apply.
    real = normalize_ai_builder_spec

    def renaming(
        spec: FlowDraftSpecCore, **kwargs: Any
    ) -> tuple[FlowDraftSpecCore, Any]:
        normalized, changes = real(spec, **kwargs)
        steps = [
            step.model_copy(update={"name": "Omdöpt"}) for step in normalized.steps
        ]
        return normalized.model_copy(update={"steps": steps}), changes

    monkeypatch.setattr(
        "eneo.flows.ai_builder.ai_builder_compiled_spec_preparation.normalize_ai_builder_spec",
        renaming,
    )

    _, changeset = _apply(_seab(), *_keep(S1, S2, S3, S4))

    assert [step.change_kind.value for step in changeset.compiled_steps[:2]] == [
        "unchanged",
        "unchanged",
    ]
