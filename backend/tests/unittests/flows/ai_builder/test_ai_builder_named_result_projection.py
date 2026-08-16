"""The obligated-field projection, from prepared schema to compiled contract.

The user names the fields the result must carry; the server projects those
names into the one prepared create schema, admits what it can compile, and
compiles the model's answer deterministically. These tests walk that whole
path — raw schema validation, admission, compiler, final validator — because
every earlier version of this contract failed between two of those steps.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from eneo.flows.ai_builder.ai_builder_action_policy import (
    NAMED_RESULT_PROJECTION_MAX_ITEMS,
    named_result_projection,
)
from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    finalize_architecture_commit,
)
from eneo.flows.ai_builder.ai_builder_architecture_derivation import (
    derive_architecture_commit_draft,
)
from eneo.flows.ai_builder.ai_builder_architecture_errors import (
    AIBuilderArchitectureError,
)
from eneo.flows.ai_builder.ai_builder_compiled_spec_preparation import (
    prepare_compiled_spec_for_session,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_create_compiler import (
    _spec_preserving_obligations,
    compile_create_intent_to_spec,
)
from eneo.flows.ai_builder.ai_builder_create_proposal import (
    _retryable_architecture_failure_code,
)
from eneo.flows.ai_builder.ai_builder_domain_models import TargetKind
from eneo.flows.ai_builder.ai_builder_error_contract import AIBuilderErrorCode
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    MAX_STRUCTURED_FIELD_DEPTH,
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    ProposalIntentArgumentError,
    ProposalObligationProjection,
    parse_create_flow_intent_arguments,
)
from eneo.flows.ai_builder.ai_builder_requirements_disclosure import (
    build_requirements_disclosure,
)
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from eneo.flows.ai_builder.ai_builder_schema_evidence import (
    DeclaredSchemaCandidate,
    build_schema_evidence,
    schema_fingerprint,
)
from eneo.flows.ai_builder.ai_builder_tools import (
    ProposalToolArgumentsError,
    build_propose_flow_tool_schema,
    validate_native_strict_schema,
    validate_propose_flow_tool_arguments,
)
from eneo.flows.ai_builder.ai_builder_turn_controller import (
    AskCanonicalQuestion,
    ConfirmRequirements,
    RefuseArchitectureCommit,
    resolve_turn_control,
)
from eneo.flows.ai_builder.planning_state import (
    NamedResultDeclaredShape,
    NamedResultEvidence,
    PlanningState,
    ResolvedSlot,
)
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore


def _battle_harness() -> ModuleType:
    """The corpus grader itself owns what "matches the declared graph" means."""

    module_path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ai_builder_api_battle_test.py"
    )
    spec = importlib.util.spec_from_file_location(
        "ai_builder_api_battle_test", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# The two nested cases the repository already declares an outcome contract
# for. They are the fixtures because they are the shapes the projection
# exists to reach, not because they are convenient.
PUBLIC_RECORD_OBLIGATIONS: tuple[tuple[str, NamedResultDeclaredShape | None], ...] = (
    ("documents", "array"),
    ("source_reference", None),
    ("candidate_passages", "array"),
    ("stated_rule_reference", None),
    ("uncertainty", None),
    ("page_or_section", None),
    ("excerpt_reference", None),
    ("reason_for_review", None),
)
PUBLIC_RECORD_CONTAINERS: dict[str, str | None] = {
    "documents": None,
    "source_reference": "documents",
    "candidate_passages": "documents",
    "stated_rule_reference": "documents",
    "uncertainty": "documents",
    "page_or_section": "candidate_passages",
    "excerpt_reference": "candidate_passages",
    "reason_for_review": "candidate_passages",
}

MEETING_ACTION_OBLIGATIONS: tuple[tuple[str, NamedResultDeclaredShape | None], ...] = (
    ("agenda_items", "array"),
    ("decisions", "array"),
    ("actions", "array"),
    ("open_questions", "array"),
    ("description", None),
    ("named_owner", None),
    ("stated_due_date", None),
    ("evidence_excerpt", None),
    ("confidence", None),
)
MEETING_ACTION_CONTAINERS: dict[str, str | None] = {
    "agenda_items": None,
    "decisions": None,
    "actions": None,
    "open_questions": None,
    "description": "actions",
    "named_owner": "actions",
    "stated_due_date": "actions",
    "evidence_excerpt": "actions",
    "confidence": "actions",
}


def _slot(name: str, value: str) -> ResolvedSlot:
    return ResolvedSlot(
        name=name,
        value=value,
        source="structured_answer",
        confidence="high",
    )


def _state(
    obligations: tuple[tuple[str, NamedResultDeclaredShape | None], ...] = (),
    *,
    primary_runtime_input: str = "documents",
    terminal_output: str = "structured_json",
) -> PlanningState:
    state = PlanningState.empty()
    state.resolved_slots = {
        "primary_runtime_input": _slot("primary_runtime_input", primary_runtime_input),
        "terminal_output": _slot("terminal_output", terminal_output),
    }
    state.named_result_evidence = [
        NamedResultEvidence(
            name=name,
            confidence="high",
            evidence=[f"quote:user_message:user-1:{name}"],
            declared_shape=declared_shape,
        )
        for name, declared_shape in obligations
    ]
    draft = derive_architecture_commit_draft(state)
    if draft is not None:
        state.architecture_commit = finalize_architecture_commit(
            draft,
            now=lambda: datetime(2026, 8, 15, tzinfo=timezone.utc),
        )
    return state


def _prepared_schema(
    projection: ProposalObligationProjection | None,
) -> dict[str, Any]:
    return dict(
        build_propose_flow_tool_schema(
            resource_catalog=build_ai_builder_resource_catalog(
                available_models=[],
                available_kbs=[],
            ),
            obligation_projection=projection,
        )
    )


def _arguments(
    *,
    result_keys: dict[str, Any] | None = None,
    model_output_fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "flow_name": "Utlämnande av allmän handling",
        "flow_description": None,
        "plan_rationale": "Läs handlingarna och peka ut granskningskandidater.",
        "assumptions": [],
        "steps": [
            {
                "name": "Läs handlingar",
                "instructions": "Läs handlingarna och peka ut kandidater.",
                "output_fields": model_output_fields,
                "model_ref": None,
                "knowledge_refs": [],
                "citations_requested": False,
            }
        ],
    }
    if result_keys is not None:
        arguments["result_keys"] = result_keys
    return arguments


def _staged_result_keys(
    projection: ProposalObligationProjection,
    containers: dict[str, str | None],
    *,
    field_types: dict[str, str] | None = None,
    order: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """One well-formed model answer for a projection, in a chosen member order."""

    names = projection.ordered_keys
    declared_shapes = {key.name: key.declared_shape for key in projection.keys}
    records = {
        name: {
            "field_type": (field_types or {}).get(
                name,
                declared_shapes[name] or "string",
            ),
            "description": f"Innehållet för {name}.",
            "required": True,
            "container": (
                None if containers[name] is None else names.index(containers[name])  # type: ignore[arg-type]
            ),
        }
        for name in names
    }
    return {name: records[name] for name in (order or names)}


def _container_index(names: tuple[str, ...], container: str | None) -> int | None:
    return None if container is None else names.index(container)


def _terminal_output_contract(spec: FlowDraftSpecCore) -> dict[str, Any] | None:
    for step in reversed(spec.steps):
        if step.output_contract is not None:
            return dict(step.output_contract)
    return None


def _compile_through_the_whole_path(
    state: PlanningState,
    *,
    result_keys: dict[str, Any] | None,
    model_output_fields: list[dict[str, Any]] | None = None,
) -> FlowDraftSpecCore:
    """Raw schema -> admission -> compiler -> final validator, with no repair."""

    projection = named_result_projection(state)
    schema = _prepared_schema(projection)
    validate_native_strict_schema(schema["function"]["parameters"])
    arguments = _arguments(
        result_keys=result_keys,
        model_output_fields=model_output_fields,
    )
    validate_propose_flow_tool_arguments(arguments=arguments, tool_schema=schema)
    intent = parse_create_flow_intent_arguments(
        arguments,
        obligation_projection=projection,
    )
    context = create_compile_context_from_planning_state(state)
    spec = compile_create_intent_to_spec(intent, context=context)
    prepared = prepare_compiled_spec_for_session(
        spec=spec,
        target_kind=TargetKind.CREATE,
        available_model_refs=None,
        available_kb_refs=None,
        resource_catalog=None,
        terminal_output_type=(context.final_output_type if context else None),
        ui_language="sv",
    )
    assert prepared.failure_feedback is None, prepared.failure_feedback
    assert prepared.spec is not None
    return prepared.spec


def _declared_case_schema(case_id: str) -> dict[str, Any]:
    corpus = Path(__file__).resolve().parents[4] / "scripts"
    payload = json.loads(
        (corpus / "ai_builder_api_battle_cases.json").read_text(encoding="utf-8")
    )
    cases = payload["cases"] if isinstance(payload, dict) else payload
    case = next(entry for entry in cases if entry["id"] == case_id)
    return dict(case["expected"]["expected_output_contract_schema"])


def test_admitted_obligations_compile_to_the_repository_declared_graph() -> None:
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None

    spec = _compile_through_the_whole_path(
        state,
        result_keys=_staged_result_keys(projection, PUBLIC_RECORD_CONTAINERS),
    )

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert _battle_harness()._json_subset_matches(
        _declared_case_schema("advanced_explicit_public_record_redaction_support"),
        contract,
    )


def test_permuting_returned_result_keys_preserves_the_compiled_graph() -> None:
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None
    declared_order = projection.ordered_keys
    reversed_order = tuple(reversed(declared_order))

    in_declared_order = _compile_through_the_whole_path(
        state,
        result_keys=_staged_result_keys(projection, PUBLIC_RECORD_CONTAINERS),
    )
    in_reversed_order = _compile_through_the_whole_path(
        state,
        result_keys=_staged_result_keys(
            projection,
            PUBLIC_RECORD_CONTAINERS,
            order=reversed_order,
        ),
    )

    assert declared_order != reversed_order
    assert _terminal_output_contract(in_declared_order) == _terminal_output_contract(
        in_reversed_order
    )


def test_admitted_obligations_compile_to_the_declared_meeting_action_nesting() -> None:
    # The declared meeting-action contract also asks for JSON `null` unions on
    # two leaves. Nullability is not in the authoring field-type vocabulary at
    # all (`StructuredFieldType`), so it is a corpus expectation no create
    # proposal can reach — a separate gap from placement, which is what D1
    # owns and what this asserts.
    state = _state(MEETING_ACTION_OBLIGATIONS, primary_runtime_input="audio")
    projection = named_result_projection(state)
    assert projection is not None

    spec = _compile_through_the_whole_path(
        state,
        result_keys=_staged_result_keys(projection, MEETING_ACTION_CONTAINERS),
    )

    contract = _terminal_output_contract(spec)
    assert contract is not None
    properties = contract["properties"]
    assert set(properties) >= {
        "agenda_items",
        "decisions",
        "actions",
        "open_questions",
    }
    action_item_properties = properties["actions"]["items"]["properties"]
    assert set(action_item_properties) == {
        "description",
        "named_owner",
        "stated_due_date",
        "evidence_excerpt",
        "confidence",
    }
    assert set(properties["actions"]["items"]["required"]) == set(
        action_item_properties
    )


def test_the_obligated_graph_wins_over_a_conflicting_model_field() -> None:
    # A model-authored `documents: string` must not stand in for the user's
    # `documents[]`: the assembly's result-contract completion would accept it
    # at any depth and under any folded alias, which is why placement is
    # server-owned instead.
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None

    spec = _compile_through_the_whole_path(
        state,
        result_keys=_staged_result_keys(projection, PUBLIC_RECORD_CONTAINERS),
        model_output_fields=[
            {
                "name": "documents",
                "field_type": "string",
                "description": "En sammanfattning av handlingarna.",
                "required": True,
            },
            {
                "name": "extra_note",
                "field_type": "string",
                "description": "Modellens egen anteckning.",
                "required": True,
            },
        ],
    )

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert contract["properties"]["documents"]["type"] == "array"
    assert "extra_note" in contract["properties"]


_SCHEMA_CANDIDATE = DeclaredSchemaCandidate(
    fingerprint=schema_fingerprint({"type": "object"}),
    json_schema={"type": "object"},
    source_file_ids=(),
    provenance=("quote:user_message:user-1:schema",),
)


def _refusal_or_confirmation(
    state: PlanningState,
    *,
    is_edit_mode: bool = False,
    schema_direction_pending: bool = False,
) -> object:
    disclosure = build_requirements_disclosure(
        state,
        ui_language="sv",
        discovery_assumptions=(),
    )
    return resolve_turn_control(
        session_state=state,
        selected_discovery_question_ids=(),
        requirements_disclosure=disclosure,
        confirmed_requirements_version=None,
        ui_language="sv",
        is_edit_mode=is_edit_mode,
        schema_direction_pending=schema_direction_pending,
        schema_candidates=(_SCHEMA_CANDIDATE,) if schema_direction_pending else (),
    ).decision


@pytest.mark.parametrize(
    ("count", "confirms"),
    [
        (NAMED_RESULT_PROJECTION_MAX_ITEMS, True),
        (NAMED_RESULT_PROJECTION_MAX_ITEMS + 1, False),
    ],
)
def test_the_projection_cap_refuses_before_any_confirmation(
    count: int,
    confirms: bool,
) -> None:
    state = _state(tuple((f"field_{index}", None) for index in range(count)))

    decision = _refusal_or_confirmation(state)

    if confirms:
        assert isinstance(decision, ConfirmRequirements)
        return
    assert isinstance(decision, RefuseArchitectureCommit)
    assert decision.code is AIBuilderErrorCode.SCHEMA_LIMIT_EXCEEDED


@pytest.mark.parametrize(
    "name",
    ["åtgärder", "foo[]", "2024_summary"],
)
def test_a_name_that_cannot_compile_unchanged_refuses_on_its_stored_spelling(
    name: str,
) -> None:
    # Folding is how the compiler keeps a Swedish field name usable, but a
    # folded obligation would reach the contract under a spelling the user was
    # never shown. Refusing keeps the disclosure honest.
    state = _state((("case_id", None), (name, None)))

    decision = _refusal_or_confirmation(state)

    assert isinstance(decision, RefuseArchitectureCommit)
    assert decision.code is AIBuilderErrorCode.NAMED_RESULT_KEY_UNSUPPORTED


def test_a_compilable_name_is_admitted_verbatim() -> None:
    state = _state((("case_id", None),))

    projection = named_result_projection(state)

    assert projection is not None
    assert projection.ordered_keys == ("case_id",)
    assert isinstance(_refusal_or_confirmation(state), ConfirmRequirements)


def test_a_lone_declared_object_refuses_instead_of_looping_repair() -> None:
    # An object must declare nested fields and only another projected key can
    # nest inside one, so a single declared object is a grain no proposal can
    # satisfy.
    state = _state((("case_metadata", "object"),))

    decision = _refusal_or_confirmation(state)

    assert isinstance(decision, RefuseArchitectureCommit)
    # Its own code: the name is valid, so telling the user to fix the spelling
    # would be advice that cannot work.
    assert decision.code is AIBuilderErrorCode.NAMED_RESULT_GRAIN_UNSUPPORTED
    assert "inneh" in decision.message


def test_pending_schema_direction_asks_before_the_projection_refuses() -> None:
    # Selecting the attached schema as the output schema stands the projection
    # down entirely, so refusing before that question answers the wrong request.
    state = _state(
        tuple(
            (f"field_{index}", None)
            for index in range(NAMED_RESULT_PROJECTION_MAX_ITEMS + 1)
        )
    )

    decision = _refusal_or_confirmation(state, schema_direction_pending=True)

    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "schema_direction"


def test_edit_mode_neither_projects_nor_refuses() -> None:
    state = _state(
        tuple(
            (f"field_{index}", None)
            for index in range(NAMED_RESULT_PROJECTION_MAX_ITEMS + 1)
        )
    )

    assert named_result_projection(state, is_edit_mode=True) is None
    assert not isinstance(
        _refusal_or_confirmation(state, is_edit_mode=True),
        RefuseArchitectureCommit,
    )


@pytest.mark.parametrize(
    "state",
    [
        pytest.param(_state(), id="no_obligations"),
        pytest.param(
            _state(PUBLIC_RECORD_OBLIGATIONS, terminal_output="text"),
            id="text_terminal",
        ),
    ],
)
def test_the_prepared_schema_is_unchanged_where_the_projection_stands_down(
    state: PlanningState,
) -> None:
    assert named_result_projection(state) is None
    assert _prepared_schema(named_result_projection(state)) == _prepared_schema(None)


def test_an_exact_declared_output_schema_stands_the_projection_down() -> None:
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    state.output_schema_evidence = build_schema_evidence(
        json_schema={"type": "object", "properties": {"documents": {"type": "array"}}},
        source="declared_schema",
        confidence="high",
        evidence=("quote:user_message:user-1:schema",),
    )

    assert named_result_projection(state) is None


def test_result_keys_are_refused_when_no_projection_was_prepared() -> None:
    schema = _prepared_schema(None)
    arguments = _arguments(result_keys={"documents": {}})

    with pytest.raises(ProposalToolArgumentsError):
        validate_propose_flow_tool_arguments(arguments=arguments, tool_schema=schema)
    with pytest.raises(ProposalIntentArgumentError):
        parse_create_flow_intent_arguments(arguments)


@pytest.mark.parametrize(
    "container",
    [0, 99],
    ids=["own_index", "out_of_range"],
)
def test_the_container_index_enum_is_closed_and_self_excluding(
    container: int,
) -> None:
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None
    result_keys = _staged_result_keys(projection, PUBLIC_RECORD_CONTAINERS)
    result_keys["documents"]["container"] = container

    with pytest.raises(ProposalToolArgumentsError):
        validate_propose_flow_tool_arguments(
            arguments=_arguments(result_keys=result_keys),
            tool_schema=_prepared_schema(projection),
        )


def test_a_containment_cycle_is_repairable_rather_than_fatal() -> None:
    state = _state((("alpha", "object"), ("beta", "object")))
    projection = named_result_projection(state)
    assert projection is not None
    result_keys = _staged_result_keys(
        projection,
        {"alpha": "beta", "beta": "alpha"},
    )

    with pytest.raises(ProposalIntentArgumentError):
        parse_create_flow_intent_arguments(
            _arguments(result_keys=result_keys),
            obligation_projection=projection,
        )


def test_a_parent_that_cannot_hold_children_is_repairable() -> None:
    state = _state((("case_id", None), ("status", None)))
    projection = named_result_projection(state)
    assert projection is not None
    result_keys = _staged_result_keys(
        projection,
        {"case_id": None, "status": "case_id"},
        field_types={"case_id": "string"},
    )

    with pytest.raises(ProposalIntentArgumentError) as failure:
        parse_create_flow_intent_arguments(
            _arguments(result_keys=result_keys),
            obligation_projection=projection,
        )

    assert "case_id" in str(failure.value)


def test_the_compiler_fails_closed_when_it_drops_an_admitted_obligation() -> None:
    # The postcondition is a defect detector, never a repair: the model cannot
    # cause it to fire, so firing means the compiler dropped a name the user
    # was already shown at confirmation.
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None
    spec = _compile_through_the_whole_path(
        state,
        result_keys=_staged_result_keys(projection, PUBLIC_RECORD_CONTAINERS),
    )

    with pytest.raises(AIBuilderArchitectureError) as failure:
        _spec_preserving_obligations(
            spec,
            (
                StructuredFieldDraft(
                    name="never_compiled",
                    field_type="string",
                    description="Ett fält som kompilatorn tappade.",
                ),
            ),
        )

    assert failure.value.log_context["failure_code"] == (
        "named_result_obligation_dropped"
    )


def test_a_nested_obligation_does_not_suppress_a_server_owned_envelope_root() -> None:
    # The assembly's completion finds a name at any depth, so an obligation
    # nested as `assessment{risks}` would have stood in for the server's own
    # required root `risks`. Only an obligated ROOT may satisfy an envelope
    # role; the envelope is merged here for exactly that reason.
    state = _state((("assessment", "object"), ("risks", None)))
    projection = named_result_projection(state)
    assert projection is not None
    context = create_compile_context_from_planning_state(state)
    assert context is not None
    envelope_risks = StructuredFieldDraft(
        name="risks",
        field_type="string",
        description="Serverägda risker.",
    )
    context = replace(
        context,
        result_contract_output_fields=(envelope_risks,),
    )
    arguments = _arguments(
        result_keys=_staged_result_keys(
            projection,
            {"assessment": None, "risks": "assessment"},
        )
    )
    validate_propose_flow_tool_arguments(
        arguments=arguments,
        tool_schema=_prepared_schema(projection),
    )
    intent = parse_create_flow_intent_arguments(
        arguments,
        obligation_projection=projection,
    )

    spec = compile_create_intent_to_spec(intent, context=context)

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert "assessment" in contract["properties"]
    assert "risks" in contract["properties"]
    assert "risks" in contract["properties"]["assessment"]["properties"]


def test_an_envelope_field_the_model_already_declared_is_not_duplicated() -> None:
    state = _state((("case_id", None),))
    projection = named_result_projection(state)
    assert projection is not None
    context = create_compile_context_from_planning_state(state)
    assert context is not None
    context = replace(
        context,
        result_contract_output_fields=(
            StructuredFieldDraft(
                name="risks",
                field_type="string",
                description="Serverägda risker.",
            ),
        ),
    )
    arguments = _arguments(
        result_keys=_staged_result_keys(projection, {"case_id": None}),
        model_output_fields=[
            {
                "name": "risks",
                "field_type": "string",
                "description": "Modellens egna risker.",
                "required": True,
            }
        ],
    )
    intent = parse_create_flow_intent_arguments(
        arguments,
        obligation_projection=projection,
    )

    spec = compile_create_intent_to_spec(intent, context=context)

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert contract["properties"]["risks"]["description"] == "Modellens egna risker."


def test_a_model_field_that_buries_an_obligated_name_is_repairable() -> None:
    state = _state((("case_id", None),))
    projection = named_result_projection(state)
    assert projection is not None
    context = create_compile_context_from_planning_state(state)
    arguments = _arguments(
        result_keys=_staged_result_keys(projection, {"case_id": None}),
        model_output_fields=[
            {
                "name": "envelope",
                "field_type": "object",
                "description": "Modellens egen behållare.",
                "required": True,
                "fields": [
                    {
                        "name": "case_id",
                        "field_type": "string",
                        "description": "En andra hemvist för samma fält.",
                        "required": True,
                    }
                ],
            }
        ],
    )
    intent = parse_create_flow_intent_arguments(
        arguments,
        obligation_projection=projection,
    )

    with pytest.raises(AIBuilderArchitectureError) as failure:
        compile_create_intent_to_spec(intent, context=context)

    failure_code = failure.value.log_context["failure_code"]
    assert failure_code == "named_result_obligation_collision"
    # Repairable: the model chose the second home and can remove it.
    assert _retryable_architecture_failure_code(failure.value) == failure_code


def test_a_dropped_obligation_is_never_handed_to_the_model_to_repair() -> None:
    dropped = AIBuilderArchitectureError(
        public_code="architecture_materialization_failed",
        detail="The compiled Flow lost result fields the user named: case_id.",
        log_context={"failure_code": "named_result_obligation_dropped"},
    )

    assert _retryable_architecture_failure_code(dropped) is None


def test_an_optional_obligation_survives_compilation_as_optional() -> None:
    state = _state((("case_id", None), ("note", None)))
    projection = named_result_projection(state)
    assert projection is not None
    result_keys = _staged_result_keys(projection, {"case_id": None, "note": None})
    result_keys["note"]["required"] = False

    spec = _compile_through_the_whole_path(state, result_keys=result_keys)

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert "note" in contract["properties"]
    assert contract["required"] == ["case_id"]


def test_an_over_deep_obligation_chain_is_repairable() -> None:
    depth = MAX_STRUCTURED_FIELD_DEPTH + 1
    names = tuple(f"level_{index}" for index in range(depth))
    state = _state(
        tuple(
            (name, "object" if index < depth - 1 else None)
            for index, name in enumerate(names)
        )
    )
    projection = named_result_projection(state)
    assert projection is not None
    containers = {
        name: (names[index - 1] if index else None) for index, name in enumerate(names)
    }

    with pytest.raises(ProposalIntentArgumentError):
        parse_create_flow_intent_arguments(
            _arguments(result_keys=_staged_result_keys(projection, containers)),
            obligation_projection=projection,
        )


def test_a_discarded_model_root_cannot_suppress_an_envelope_field() -> None:
    # `assessment` is outranked by the obligated root of the same name, so its
    # nested `risks` is never emitted. Judging envelope satisfaction against
    # what was submitted rather than what survives let that dead subtree
    # suppress the server's own required root.
    state = _state((("assessment", "object"), ("detail", None)))
    projection = named_result_projection(state)
    assert projection is not None
    context = create_compile_context_from_planning_state(state)
    assert context is not None
    context = replace(
        context,
        result_contract_output_fields=(
            StructuredFieldDraft(
                name="risks",
                field_type="string",
                description="Serverägda risker.",
            ),
        ),
    )
    intent = parse_create_flow_intent_arguments(
        _arguments(
            result_keys=_staged_result_keys(
                projection,
                {"assessment": None, "detail": "assessment"},
            ),
            model_output_fields=[
                {
                    "name": "assessment",
                    "field_type": "object",
                    "description": "Modellens egen bedömning.",
                    "required": True,
                    "fields": [
                        {
                            "name": "risks",
                            "field_type": "string",
                            "description": "Risker som aldrig kompileras.",
                            "required": True,
                        }
                    ],
                }
            ],
        ),
        obligation_projection=projection,
    )

    spec = compile_create_intent_to_spec(intent, context=context)

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert "risks" in contract["properties"]
    assert "risks" not in contract["properties"]["assessment"]["properties"]


def test_a_surviving_model_field_repeating_a_nested_obligation_is_repairable() -> None:
    state = _state((("assessment", "object"), ("risks", None)))
    projection = named_result_projection(state)
    assert projection is not None
    context = create_compile_context_from_planning_state(state)
    intent = parse_create_flow_intent_arguments(
        _arguments(
            result_keys=_staged_result_keys(
                projection,
                {"assessment": None, "risks": "assessment"},
            ),
            model_output_fields=[
                {
                    "name": "other",
                    "field_type": "object",
                    "description": "Modellens egen behållare.",
                    "required": True,
                    "fields": [
                        {
                            "name": "risks",
                            "field_type": "string",
                            "description": "En andra hemvist för samma fält.",
                            "required": True,
                        }
                    ],
                }
            ],
        ),
        obligation_projection=projection,
    )

    with pytest.raises(AIBuilderArchitectureError) as failure:
        compile_create_intent_to_spec(intent, context=context)

    assert failure.value.log_context["failure_code"] == (
        "named_result_obligation_collision"
    )


def test_a_wholly_discarded_model_tree_does_not_demand_a_repair() -> None:
    # The model's `assessment` root is outranked, so nothing it contains — not
    # even a repeat of its own name — can reach the contract. Demanding a
    # repair for content that is already gone would burn the turn's budget.
    state = _state((("assessment", "object"), ("detail", None)))
    projection = named_result_projection(state)
    assert projection is not None
    context = create_compile_context_from_planning_state(state)
    intent = parse_create_flow_intent_arguments(
        _arguments(
            result_keys=_staged_result_keys(
                projection,
                {"assessment": None, "detail": "assessment"},
            ),
            model_output_fields=[
                {
                    "name": "assessment",
                    "field_type": "object",
                    "description": "Modellens egen bedömning.",
                    "required": True,
                    "fields": [
                        {
                            "name": "assessment",
                            "field_type": "string",
                            "description": "En kopia som aldrig kompileras.",
                            "required": True,
                        }
                    ],
                }
            ],
        ),
        obligation_projection=projection,
    )

    spec = compile_create_intent_to_spec(intent, context=context)

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert contract["properties"]["assessment"]["type"] == "object"


def test_legacy_any_depth_model_satisfaction_of_an_envelope_field_is_unchanged() -> (
    None
):
    # A surviving model field satisfies an envelope role at any depth, exactly
    # as the assembly has always done. Only obligations changed.
    state = _state((("case_id", None),))
    projection = named_result_projection(state)
    assert projection is not None
    context = create_compile_context_from_planning_state(state)
    assert context is not None
    context = replace(
        context,
        result_contract_output_fields=(
            StructuredFieldDraft(
                name="risks",
                field_type="string",
                description="Serverägda risker.",
            ),
        ),
    )
    intent = parse_create_flow_intent_arguments(
        _arguments(
            result_keys=_staged_result_keys(projection, {"case_id": None}),
            model_output_fields=[
                {
                    "name": "wrapper",
                    "field_type": "object",
                    "description": "Modellens egen behållare.",
                    "required": True,
                    "fields": [
                        {
                            "name": "risks",
                            "field_type": "string",
                            "description": "Modellens egna risker.",
                            "required": True,
                        }
                    ],
                }
            ],
        ),
        obligation_projection=projection,
    )

    spec = compile_create_intent_to_spec(intent, context=context)

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert "risks" not in contract["properties"]
    assert "risks" in contract["properties"]["wrapper"]["properties"]


def test_the_postcondition_covers_a_dropped_nested_obligation() -> None:
    # A lost `assessment.risks` is exactly as broken a promise as a lost
    # `assessment`, and only the roots survive by accident when a branch is
    # rewritten.
    # The server's envelope legitimately puts a `risks` root beside the user's
    # `assessment.risks`, so a flat name set would let the survivor mask the
    # loss. The postcondition matches paths for exactly that reason.
    state = _state((("assessment", "object"), ("risks", None)))
    projection = named_result_projection(state)
    assert projection is not None
    context = create_compile_context_from_planning_state(state)
    assert context is not None
    context = replace(
        context,
        result_contract_output_fields=(
            StructuredFieldDraft(
                name="risks",
                field_type="string",
                description="Serverägda risker.",
            ),
        ),
    )
    containers = {"assessment": None, "risks": "assessment"}
    intent = parse_create_flow_intent_arguments(
        _arguments(result_keys=_staged_result_keys(projection, containers)),
        obligation_projection=projection,
    )
    spec = compile_create_intent_to_spec(intent, context=context)
    compiled = _terminal_output_contract(spec)
    assert compiled is not None
    assert "risks" in compiled["properties"]
    assert "risks" in compiled["properties"]["assessment"]["properties"]

    stripped_step = spec.steps[-1].model_copy(
        update={
            "output_contract": {
                "type": "object",
                "properties": {
                    "assessment": {"type": "object", "properties": {}},
                    "risks": {"type": "string"},
                },
            }
        }
    )
    stripped = spec.model_copy(update={"steps": [*spec.steps[:-1], stripped_step]})

    with pytest.raises(AIBuilderArchitectureError) as failure:
        _spec_preserving_obligations(stripped, intent.obligated_output_fields)

    assert failure.value.log_context["failure_code"] == (
        "named_result_obligation_dropped"
    )
    assert failure.value.log_context["field_names"] == "assessment.risks"
