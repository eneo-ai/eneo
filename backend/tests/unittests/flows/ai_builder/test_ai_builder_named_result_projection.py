"""The obligated-field projection, from prepared schema to compiled contract.

The user names the fields the result must carry; the server projects those
names into the one prepared create schema, admits what it can compile, and
compiles the model's answer deterministically. These tests walk that whole
path — raw schema validation, admission, compiler, final validator — because
every earlier version of this contract failed between two of those steps.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

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
from eneo.flows.ai_builder.ai_builder_structured_field_normalizer import (
    StructuredFieldAdmissionError,
    normalize_structured_field_list,
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
from eneo.flows.output_processing import (
    prune_extras_to_strict_schema,
    validate_against_contract,
)

# The two nested cases the repository already declares an outcome contract
# for. They are the fixtures because they carry the most user-named fields in
# the corpus — but the projection compiles every one of them as a ROOT, so
# neither reaches its declared nesting. That is a recorded conformance failure,
# not a success: a parent relationship is user evidence, the understanding pass
# does not persist one, and asking the proposal model to supply it produced
# contradictory parents and repairs it could not escape. Nesting belongs to a
# follow-up slice that captures cited parents first, and the acceptance test
# for the exact nested graph is that slice's to write.
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
        }
        for name in names
    }
    return {name: records[name] for name in (order or names)}


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


def test_every_admitted_obligation_compiles_as_a_root() -> None:
    # Every user-named field reaches the contract, each exactly once, with the
    # shape the user declared. Placement is the part this slice does not
    # attempt.
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None

    spec = _compile_through_the_whole_path(
        state,
        result_keys=_staged_result_keys(projection),
    )

    contract = _terminal_output_contract(spec)
    assert contract is not None
    properties = contract["properties"]
    assert set(properties) >= {name for name, _ in PUBLIC_RECORD_OBLIGATIONS}
    assert properties["documents"]["type"] == "array"
    assert properties["candidate_passages"]["type"] == "array"
    assert properties["source_reference"]["type"] == "string"


def test_permuting_returned_result_keys_preserves_the_compiled_graph() -> None:
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None
    declared_order = projection.ordered_keys
    reversed_order = tuple(reversed(declared_order))

    in_declared_order = _compile_through_the_whole_path(
        state,
        result_keys=_staged_result_keys(projection),
    )
    in_reversed_order = _compile_through_the_whole_path(
        state,
        result_keys=_staged_result_keys(projection, order=reversed_order),
    )

    assert declared_order != reversed_order
    assert _terminal_output_contract(in_declared_order) == _terminal_output_contract(
        in_reversed_order
    )


@pytest.mark.parametrize(
    (
        "obligations",
        "runtime_input",
        "declared_case_id",
        "nested_parent",
        "nested_child",
    ),
    [
        pytest.param(
            PUBLIC_RECORD_OBLIGATIONS,
            "documents",
            "advanced_explicit_public_record_redaction_support",
            "documents",
            "candidate_passages",
            id="public_record",
        ),
        pytest.param(
            MEETING_ACTION_OBLIGATIONS,
            "audio",
            None,
            "actions",
            "named_owner",
            id="meeting_action",
        ),
    ],
)
def test_the_user_is_told_that_a_field_they_nested_will_be_top_level(
    obligations: tuple[tuple[str, NamedResultDeclaredShape | None], ...],
    runtime_input: str,
    declared_case_id: str | None,
    nested_parent: str,
    nested_child: str,
) -> None:
    # Both corpus cases describe a child living inside a parent, and both
    # compile flat. That is a real limitation, so what this pins is that the
    # user is told before confirming — and told the one way to get the
    # hierarchy they described. The limitation itself is measured in the
    # cohort, not blessed here.
    state = _state(obligations, primary_runtime_input=runtime_input)
    projection = named_result_projection(state)
    assert projection is not None

    disclosure = build_requirements_disclosure(
        state,
        ui_language="sv",
        discovery_assumptions=(),
    )
    assert "namngett innehåll" in disclosure.summary
    assert "översta nivån" in disclosure.summary
    assert "utdataschema" in disclosure.summary

    spec = _compile_through_the_whole_path(
        state,
        result_keys=_staged_result_keys(projection),
    )
    contract = _terminal_output_contract(spec)
    assert contract is not None
    parent = contract["properties"][nested_parent]
    assert nested_child in contract["properties"]
    assert nested_child not in parent.get("items", {}).get("properties", {})


def test_an_edit_confirmation_shows_no_placement_limitation() -> None:
    # Edit mode projects nothing, so the sentence would be attesting to a
    # behaviour the turn does not have — and the confirmation is hashed, so the
    # user would be confirming it.
    state = _state(PUBLIC_RECORD_OBLIGATIONS)

    assert named_result_projection(state, is_edit_mode=True) is None
    disclosure = build_requirements_disclosure(
        state,
        ui_language="sv",
        discovery_assumptions=(),
        is_edit_mode=True,
    )

    assert "namngett innehåll" in disclosure.summary
    assert "översta nivån" not in disclosure.summary


def test_a_declared_output_schema_shows_no_placement_limitation() -> None:
    # The projection stands down entirely, so the flat-placement sentence would
    # be describing something that is not happening.
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    state.output_schema_evidence = build_schema_evidence(
        json_schema={"type": "object", "properties": {"documents": {"type": "array"}}},
        source="declared_schema",
        confidence="high",
        evidence=("quote:user_message:user-1:schema",),
    )

    assert named_result_projection(state) is None
    disclosure = build_requirements_disclosure(
        state,
        ui_language="sv",
        discovery_assumptions=(),
    )

    assert "översta nivån" not in disclosure.summary


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
        result_keys=_staged_result_keys(projection),
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
        is_edit_mode=is_edit_mode,
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


def test_a_declared_group_compiles_as_an_open_object() -> None:
    # `stated_route{}` is a group the user named without saying what belongs
    # inside it. Nothing in this contract can name its members, so the honest
    # compilation is an object whose members are unconstrained — not a string
    # that quietly loses the group, and not a refusal.
    state = _state((("stated_route", "object"), ("case_id", None)))
    projection = named_result_projection(state)
    assert projection is not None
    assert isinstance(_refusal_or_confirmation(state), ConfirmRequirements)

    spec = _compile_through_the_whole_path(
        state,
        result_keys=_staged_result_keys(projection),
    )

    contract = _terminal_output_contract(spec)
    assert contract is not None
    stated_route = contract["properties"]["stated_route"]
    assert stated_route["type"] == "object"
    assert stated_route["additionalProperties"] is True
    assert "properties" not in stated_route


def test_an_open_group_keeps_its_members_through_runtime_pruning() -> None:
    # The open object is only worth compiling if the runtime keeps what the
    # step puts in it. Pruning drops keys solely beneath an explicit
    # `additionalProperties: false`, so these members survive.
    state = _state((("stated_route", "object"),))
    projection = named_result_projection(state)
    assert projection is not None
    spec = _compile_through_the_whole_path(
        state,
        result_keys=_staged_result_keys(projection),
    )
    contract = _terminal_output_contract(spec)
    assert contract is not None
    payload: dict[str, Any] = {
        "stated_route": {"fran": "Sundsvall", "till": "Timrå"},
        "ej_deklarerad": "tas bort",
    }

    result = prune_extras_to_strict_schema(payload, contract)

    assert result.dropped_paths == ("/ej_deklarerad",)
    assert payload["stated_route"] == {"fran": "Sundsvall", "till": "Timrå"}
    validate_against_contract(payload, contract, label="terminal")


def test_the_open_object_capability_is_unreachable_from_the_wire() -> None:
    # It is a server capability, so the prepared schema must not offer it: a
    # model cannot ask for an unconstrained object on one of its own fields.
    state = _state((("case_id", None),))
    projection = named_result_projection(state)
    assert projection is not None

    with pytest.raises(ProposalToolArgumentsError):
        validate_propose_flow_tool_arguments(
            arguments=_arguments(
                result_keys=_staged_result_keys(projection),
                model_output_fields=[
                    {
                        "name": "egen_grupp",
                        "field_type": "object",
                        "description": "Modellens egen öppna grupp.",
                        "required": True,
                        "allow_additional_properties": True,
                    }
                ],
            ),
            tool_schema=_prepared_schema(projection),
        )


def test_the_typed_admission_boundary_also_refuses_the_server_only_flag() -> None:
    # The tool schema does not offer it, but the typed boundary must not depend
    # on that: it is the owner of what a proposal may put in an output field.
    with pytest.raises(StructuredFieldAdmissionError) as failure:
        normalize_structured_field_list(
            [
                {
                    "name": "egen_grupp",
                    "field_type": "object",
                    "description": "Modellens egen öppna grupp.",
                    "required": True,
                    "allow_additional_properties": True,
                }
            ]
        )

    assert "allow_additional_properties" in str(failure.value)


def test_a_model_authored_empty_object_is_still_refused() -> None:
    # The open object is a server capability for a user-declared group only.
    # A model that invents an empty object still gets the repairable message.
    with pytest.raises(ValidationError):
        StructuredFieldDraft(
            name="tom_grupp",
            field_type="object",
            description="En grupp modellen hittade på.",
        )
    with pytest.raises(ValidationError):
        StructuredFieldDraft(
            name="inte_ett_objekt",
            field_type="string",
            description="Öppenhet hör bara hemma på objekt.",
            allow_additional_properties=True,
        )
    # Both at once would let the compiler silently pick one: it answers
    # "declared members" first, so the openness would vanish without a word.
    with pytest.raises(ValidationError):
        StructuredFieldDraft(
            name="bade_och",
            field_type="object",
            description="Både beskrivna och öppna medlemmar.",
            allow_additional_properties=True,
            fields=[
                StructuredFieldDraft(
                    name="medlem",
                    field_type="string",
                    description="En beskriven medlem.",
                )
            ],
        )


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


def test_a_model_authored_placement_is_rejected_as_an_extra_property() -> None:
    # Placement left the wire contract with the parent relationship it was
    # guessing at. Raw prepared-schema validation is where that is enforced,
    # before any staged check runs.
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None
    result_keys = _staged_result_keys(projection)
    result_keys["source_reference"]["container"] = 0

    with pytest.raises(ProposalToolArgumentsError):
        validate_propose_flow_tool_arguments(
            arguments=_arguments(result_keys=result_keys),
            tool_schema=_prepared_schema(projection),
        )
    with pytest.raises(ProposalIntentArgumentError):
        parse_create_flow_intent_arguments(
            _arguments(result_keys=result_keys),
            obligation_projection=projection,
        )


def test_the_wire_record_asks_the_model_only_what_the_user_left_open() -> None:
    # A declared shape is the user's, so its enum has exactly one member and
    # the server materializes it either way. An unshaped name is a leaf the
    # model may type — but never as an object, which could not compile.
    state = _state((("documents", "array"), ("case_id", None)))
    projection = named_result_projection(state)
    assert projection is not None

    result_keys = _prepared_schema(projection)["function"]["parameters"]["properties"][
        "result_keys"
    ]

    for record in result_keys["properties"].values():
        assert set(record["properties"]) == {"field_type", "description", "required"}
        assert record["required"] == ["field_type", "description", "required"]
    assert result_keys["properties"]["documents"]["properties"]["field_type"][
        "enum"
    ] == ["array"]
    case_id_types = result_keys["properties"]["case_id"]["properties"]["field_type"][
        "enum"
    ]
    assert "object" not in case_id_types
    assert "string" in case_id_types


def test_a_declared_shape_wins_over_a_model_answer() -> None:
    # The single-value enum makes disagreement unrepresentable on the wire, and
    # the server materializes from the projection so it stays that way.
    state = _state((("documents", "array"),))
    projection = named_result_projection(state)
    assert projection is not None
    result_keys = _staged_result_keys(projection, field_types={"documents": "string"})

    intent = parse_create_flow_intent_arguments(
        _arguments(result_keys=result_keys),
        obligation_projection=projection,
    )

    assert intent.obligated_output_fields[0].field_type == "array"


def test_the_compiler_fails_closed_when_it_drops_an_admitted_obligation() -> None:
    # The postcondition is a defect detector, never a repair: the model cannot
    # cause it to fire, so firing means the compiler dropped a name the user
    # was already shown at confirmation.
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None
    spec = _compile_through_the_whole_path(
        state,
        result_keys=_staged_result_keys(projection),
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


def test_an_obligation_takes_the_envelope_role_of_its_own_name() -> None:
    # The user named `risks` and the server's envelope wants a `risks` too.
    # One field carries both, described the way the user's obligation is —
    # merging the envelope copy beside it would bind the name twice.
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
    arguments = _arguments(result_keys=_staged_result_keys(projection))
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
    assert contract["properties"]["risks"]["description"] == "Innehållet för risks."
    assert contract["properties"]["assessment"]["additionalProperties"] is True


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
        result_keys=_staged_result_keys(projection),
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
        result_keys=_staged_result_keys(projection),
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
    result_keys = _staged_result_keys(projection)
    result_keys["note"]["required"] = False

    spec = _compile_through_the_whole_path(state, result_keys=result_keys)

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert "note" in contract["properties"]
    assert contract["required"] == ["case_id"]


def test_every_obligation_compiles_at_depth_one() -> None:
    # Placement is server-owned and flat, so the authoring depth limit cannot
    # be reached from a projection however many keys it admits.
    names = tuple(f"level_{index}" for index in range(MAX_STRUCTURED_FIELD_DEPTH + 1))
    state = _state(tuple((name, None) for name in names))
    projection = named_result_projection(state)
    assert projection is not None

    intent = parse_create_flow_intent_arguments(
        _arguments(result_keys=_staged_result_keys(projection)),
        obligation_projection=projection,
    )

    assert tuple(field.name for field in intent.obligated_output_fields) == names
    assert all(field.fields is None for field in intent.obligated_output_fields)


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
            result_keys=_staged_result_keys(projection),
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
    assert "properties" not in contract["properties"]["assessment"]


def test_a_surviving_model_field_repeating_an_obligation_is_repairable() -> None:
    state = _state((("assessment", "object"), ("risks", None)))
    projection = named_result_projection(state)
    assert projection is not None
    context = create_compile_context_from_planning_state(state)
    intent = parse_create_flow_intent_arguments(
        _arguments(
            result_keys=_staged_result_keys(projection),
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
            result_keys=_staged_result_keys(projection),
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
            result_keys=_staged_result_keys(projection),
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


def test_the_postcondition_reports_the_path_it_lost_not_just_the_name() -> None:
    # The projection is roots-only, so it hands the postcondition roots. The
    # postcondition still checks each obligation at its own PATH, because a
    # `risks` surviving elsewhere would otherwise mask the loss of the one that
    # was promised. Handing it a nested obligation directly keeps that guard
    # honest, and it is the guard the slice that adds nesting will rely on.
    state = _state((("case_id", None),))
    projection = named_result_projection(state)
    assert projection is not None
    spec = _compile_through_the_whole_path(
        state,
        result_keys=_staged_result_keys(projection),
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
                        "description": "Risker inuti bedömningen.",
                        "required": True,
                    }
                ],
            },
            {
                "name": "risks",
                "field_type": "string",
                "description": "En rot med samma namn.",
                "required": True,
            },
        ],
    )
    compiled = _terminal_output_contract(spec)
    assert compiled is not None
    assert "risks" in compiled["properties"]
    assert "risks" in compiled["properties"]["assessment"]["properties"]
    nested_obligation = StructuredFieldDraft(
        name="assessment",
        field_type="object",
        description="Bedömningen.",
        fields=[
            StructuredFieldDraft(
                name="risks",
                field_type="string",
                description="Risker inuti bedömningen.",
            )
        ],
    )

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
        _spec_preserving_obligations(stripped, (nested_obligation,))

    assert failure.value.log_context["failure_code"] == (
        "named_result_obligation_dropped"
    )
    assert failure.value.log_context["field_names"] == "assessment.risks"
