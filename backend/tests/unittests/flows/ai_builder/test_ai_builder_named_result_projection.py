"""The attested result contract, from prompt to compiled verification.

The user names the fields the result must carry; the prompt states them
concretely, the model authors output_fields, admission verifies the
declaration against the attested names, and the compiled postcondition
re-runs the same predicate on the terminal contract. These tests walk that
whole path — prompt, raw schema validation, admission, compiler, final
validator — because every earlier version of this contract failed between
two of those steps.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

import pytest

from eneo.flows.ai_builder.ai_builder_action_policy import (
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
    _spec_satisfying_attested_contract,
    compile_create_intent_to_spec,
)
from eneo.flows.ai_builder.ai_builder_domain_models import TargetKind
from eneo.flows.ai_builder.ai_builder_error_contract import AIBuilderErrorCode
from eneo.flows.ai_builder.ai_builder_new_step_models import (
    StructuredFieldDraft,
)
from eneo.flows.ai_builder.ai_builder_proposal_intent import (
    AttestedResultField,
    ObligatedResultKey,
    ProposalIntentArgumentError,
    ProposalObligationProjection,
    attested_result_contract_violations,
    attested_violation_message,
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
    build_native_strict_tool_schema,
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
    ExactNamedResultPlacement,
    NamedResultDeclaredShape,
    NamedResultEvidence,
    PlanningState,
    ResolvedSlot,
    UnplacedNamedResultPlacement,
    named_content_fields_edit_evidence_reference,
)
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore

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


def _prepared_schema() -> dict[str, Any]:
    return dict(
        build_propose_flow_tool_schema(
            resource_catalog=build_ai_builder_resource_catalog(
                available_models=[],
                available_kbs=[],
            ),
        )
    )


def _arguments(
    *,
    model_output_fields: list[dict[str, Any]] | None = None,
    leading_step_output_fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    leading_steps: list[dict[str, Any]] = (
        [
            {
                "name": "Förbered underlag",
                "instructions": "Sammanställ underlaget inför granskningen.",
                "output_fields": leading_step_output_fields,
                "model_ref": None,
                "knowledge_refs": [],
                "citations_requested": False,
            }
        ]
        if leading_step_output_fields is not None
        else []
    )
    arguments: dict[str, Any] = {
        "flow_name": "Utlämnande av allmän handling",
        "flow_description": None,
        "plan_rationale": "Läs handlingarna och peka ut granskningskandidater.",
        "assumptions": [],
        "steps": [
            *leading_steps,
            {
                "name": "Läs handlingar",
                "instructions": "Läs handlingarna och peka ut kandidater.",
                "output_fields": model_output_fields,
                "model_ref": None,
                "knowledge_refs": [],
                "citations_requested": False,
            },
        ],
    }
    return arguments


def _terminal_output_contract(spec: FlowDraftSpecCore) -> dict[str, Any] | None:
    for step in reversed(spec.steps):
        if step.output_contract is not None:
            return dict(step.output_contract)
    return None


def _attested_model_fields(
    projection: ProposalObligationProjection,
    *,
    field_types: dict[str, str] | None = None,
    extra: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The model's own declaration of every attested name, plus extras."""

    fields: list[dict[str, Any]] = [
        {
            "name": key.name,
            "field_type": (field_types or {}).get(
                key.name, key.declared_shape or "string"
            ),
            "description": f"Innehållet för {key.name}.",
            "required": True,
        }
        for key in projection.keys
    ]
    return fields + list(extra or [])


def _compile_through_the_whole_path(
    state: PlanningState,
    *,
    model_output_fields: list[dict[str, Any]] | None = None,
    leading_step_output_fields: list[dict[str, Any]] | None = None,
) -> FlowDraftSpecCore:
    """Raw schema -> admission -> compiler -> final validator, with no repair."""

    projection = named_result_projection(state)
    schema = _prepared_schema()
    strict_schema = build_native_strict_tool_schema(schema)
    validate_native_strict_schema(strict_schema["function"]["parameters"])
    arguments = _arguments(
        model_output_fields=model_output_fields,
        leading_step_output_fields=leading_step_output_fields,
    )
    validate_propose_flow_tool_arguments(arguments=arguments, tool_schema=schema)
    intent = parse_create_flow_intent_arguments(
        arguments,
        obligation_projection=projection,
    )
    context = create_compile_context_from_planning_state(state)
    spec = compile_create_intent_to_spec(
        intent, context=context, obligation_projection=projection
    )
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


def test_projection_preserves_locations_and_same_leaf_paths() -> None:
    state = _state()
    state.named_result_evidence = [
        NamedResultEvidence(
            name="events",
            declared_shape="array",
            confidence="high",
            evidence=["quote:user_message:user-1:events"],
        ),
        NamedResultEvidence(
            name="alerts",
            declared_shape="array",
            confidence="high",
            evidence=["quote:user_message:user-1:alerts"],
        ),
        NamedResultEvidence(
            name="timestamp",
            placement=ExactNamedResultPlacement(segments=("events",)),
            confidence="high",
            evidence=["quote:user_message:user-1:events.timestamp"],
        ),
        NamedResultEvidence(
            name="timestamp",
            placement=ExactNamedResultPlacement(segments=("alerts",)),
            confidence="high",
            evidence=["quote:user_message:user-1:alerts.timestamp"],
        ),
        NamedResultEvidence(
            name="owner",
            placement=UnplacedNamedResultPlacement(),
            confidence="high",
            evidence=["quote:user_message:user-1:owner"],
        ),
    ]

    projection = named_result_projection(state)

    assert projection is not None
    assert [(key.name, key.placement) for key in projection.keys] == [
        ("events", ExactNamedResultPlacement()),
        ("alerts", ExactNamedResultPlacement()),
        ("timestamp", ExactNamedResultPlacement(segments=("events",))),
        ("timestamp", ExactNamedResultPlacement(segments=("alerts",))),
        ("owner", UnplacedNamedResultPlacement()),
    ]


def test_exact_nested_locations_compile_without_root_duplicates() -> None:
    state = _state()
    state.named_result_evidence = [
        NamedResultEvidence(
            name="documents",
            placement=ExactNamedResultPlacement(),
            declared_shape="array",
            confidence="high",
            evidence=["quote:user_message:user-1:documents"],
        ),
        NamedResultEvidence(
            name="candidate_passages",
            placement=ExactNamedResultPlacement(segments=("documents",)),
            declared_shape="array",
            confidence="high",
            evidence=["quote:user_message:user-1:candidate_passages"],
        ),
        NamedResultEvidence(
            name="page_or_section",
            placement=ExactNamedResultPlacement(
                segments=("documents", "candidate_passages")
            ),
            confidence="high",
            evidence=["quote:user_message:user-1:page_or_section"],
        ),
    ]
    model_fields = [
        {
            "name": "documents",
            "field_type": "array",
            "description": "Handlingarna.",
            "required": False,
            "children": [
                {
                    "name": "candidate_passages",
                    "field_type": "array",
                    "description": "Kandidatpassagerna.",
                    "required": False,
                    "children": [
                        {
                            "name": "page_or_section",
                            "field_type": "string",
                            "description": "Sida eller avsnitt.",
                            "required": False,
                        }
                    ],
                }
            ],
        }
    ]

    spec = _compile_through_the_whole_path(
        state,
        model_output_fields=model_fields,
    )

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert list(contract["properties"]) == ["documents"]
    documents = contract["properties"]["documents"]
    passages = documents["items"]["properties"]["candidate_passages"]
    assert list(passages["items"]["properties"]) == ["page_or_section"]


def test_exact_child_inside_an_extra_wrapper_is_rejected_with_its_parent() -> None:
    state = _state()
    state.named_result_evidence = [
        NamedResultEvidence(
            name="events",
            declared_shape="array",
            confidence="high",
            evidence=["quote:user_message:user-1:events"],
        ),
        NamedResultEvidence(
            name="timestamp",
            placement=ExactNamedResultPlacement(segments=("events",)),
            confidence="high",
            evidence=["quote:user_message:user-1:events.timestamp"],
        ),
    ]
    model_fields = [
        {
            "name": "events",
            "field_type": "array",
            "description": "Händelserna.",
            "children": [
                {
                    "name": "event",
                    "field_type": "object",
                    "description": "Ett extra omslag.",
                    "children": [
                        {
                            "name": "timestamp",
                            "field_type": "string",
                            "description": "Tidpunkten.",
                        }
                    ],
                }
            ],
        }
    ]

    with pytest.raises(ProposalIntentArgumentError) as rejected:
        _compile_through_the_whole_path(
            state,
            model_output_fields=model_fields,
        )

    assert list(rejected.value.issues) == [
        "steps.0.output_fields: the user-named result `timestamp` must exist "
        "directly under `events` in the final step's output_fields [value_error]"
    ]


def test_exact_path_rename_copy_names_the_respelled_parent_path() -> None:
    state = _state()
    state.named_result_evidence = [
        NamedResultEvidence(
            name="events",
            declared_shape="array",
            confidence="high",
            evidence=["quote:user_message:user-1:events"],
        ),
        NamedResultEvidence(
            name="timestamp",
            placement=ExactNamedResultPlacement(segments=("events",)),
            confidence="high",
            evidence=["quote:user_message:user-1:events.timestamp"],
        ),
    ]
    projection = named_result_projection(state)
    assert projection is not None
    terminal_fields = (
        AttestedResultField(
            name="Events",
            field_type="array",
            children=(AttestedResultField(name="timestamp", field_type="string"),),
        ),
    )

    violations = attested_result_contract_violations(
        terminal_fields,
        projection=projection,
    )

    timestamp_violation = next(
        violation for violation in violations if violation.key_name == "timestamp"
    )
    assert attested_violation_message(timestamp_violation) == (
        "rename location `Events[].timestamp` to exactly `events[].timestamp` — "
        "the user attested to that path"
    )


def test_unplaced_result_resolves_at_its_single_occurrence() -> None:
    state = _state()
    state.named_result_evidence = [
        NamedResultEvidence(
            name="timestamp",
            placement=UnplacedNamedResultPlacement(),
            confidence="high",
            evidence=["quote:user_message:user-1:timestamp"],
        )
    ]
    model_fields = [
        {
            "name": "events",
            "field_type": "array",
            "description": "Händelserna.",
            "required": False,
            "children": [
                {
                    "name": "timestamp",
                    "field_type": "string",
                    "description": "Tidpunkten.",
                    "required": False,
                }
            ],
        }
    ]

    spec = _compile_through_the_whole_path(
        state,
        model_output_fields=model_fields,
    )

    contract = _terminal_output_contract(spec)
    assert contract is not None
    timestamp = contract["properties"]["events"]["items"]["properties"]["timestamp"]
    assert timestamp["type"] == ["string", "null"]
    assert "timestamp" in contract["properties"]["events"]["items"]["required"]


def test_unplaced_result_rejects_zero_occurrences() -> None:
    state = _state()
    state.named_result_evidence = [
        NamedResultEvidence(
            name="timestamp",
            placement=UnplacedNamedResultPlacement(),
            confidence="high",
            evidence=["quote:user_message:user-1:timestamp"],
        )
    ]
    projection = named_result_projection(state)
    assert projection is not None

    violations = attested_result_contract_violations((), projection=projection)

    assert len(violations) == 1
    assert violations[0].kind == "missing_location"
    assert "exactly once somewhere" in attested_violation_message(violations[0])


@pytest.mark.parametrize(
    ("declared_shape", "terminal_field", "expected_kind"),
    [
        pytest.param(
            None,
            AttestedResultField(name="Timestamp", field_type="string"),
            "rename",
            id="folded_alias",
        ),
        pytest.param(
            "array",
            AttestedResultField(name="timestamp", field_type="object"),
            "shape_conflict",
            id="declared_shape",
        ),
    ],
)
def test_unplaced_unique_occurrence_keeps_rename_and_shape_checks(
    declared_shape: NamedResultDeclaredShape | None,
    terminal_field: AttestedResultField,
    expected_kind: str,
) -> None:
    state = _state()
    state.named_result_evidence = [
        NamedResultEvidence(
            name="timestamp",
            placement=UnplacedNamedResultPlacement(),
            declared_shape=declared_shape,
            confidence="high",
            evidence=["quote:user_message:user-1:timestamp"],
        )
    ]
    projection = named_result_projection(state)
    assert projection is not None

    violations = attested_result_contract_violations(
        (terminal_field,),
        projection=projection,
    )

    assert len(violations) == 1
    assert violations[0].kind == expected_kind


def test_unplaced_ambiguity_lists_only_the_first_ten_candidate_paths() -> None:
    state = _state()
    state.named_result_evidence = [
        NamedResultEvidence(
            name="timestamp",
            placement=UnplacedNamedResultPlacement(),
            confidence="high",
            evidence=["quote:user_message:user-1:timestamp"],
        )
    ]
    projection = named_result_projection(state)
    assert projection is not None
    terminal_fields = tuple(
        AttestedResultField(
            name=f"events_{index:02d}",
            field_type="array",
            children=(AttestedResultField(name="timestamp", field_type="string"),),
        )
        for index in range(12)
    )

    violations = attested_result_contract_violations(
        terminal_fields,
        projection=projection,
    )

    assert len(violations) == 1
    violation = violations[0]
    assert violation.kind == "ambiguous_placement"
    assert violation.candidate_paths == tuple(
        f"events_{index:02d}[].timestamp" for index in range(10)
    )
    message = attested_violation_message(violation)
    assert "events_00[].timestamp" in message
    assert "events_10[].timestamp" not in message
    assert "showing 10 of 12" in message
    assert message.endswith(
        "declare it exactly once at one of those paths and remove every other "
        "occurrence"
    )


def test_nested_and_top_level_copies_of_an_unplaced_name_get_the_declare_once_instruction() -> (
    None
):
    """Captured rejection shape: `ansvarig` under `beslut[]` and at the top level.

    Repair prompts that only listed the candidates left the model moving the
    field between the two places across the whole call budget.
    """

    state = _state()
    state.named_result_evidence = [
        NamedResultEvidence(
            name="ansvarig",
            placement=UnplacedNamedResultPlacement(),
            confidence="high",
            evidence=["quote:user_message:user-1:ansvarig"],
        )
    ]
    projection = named_result_projection(state)
    assert projection is not None
    terminal_fields = (
        AttestedResultField(
            name="beslut",
            field_type="array",
            children=(
                AttestedResultField(name="text", field_type="string"),
                AttestedResultField(name="ansvarig", field_type="string"),
                AttestedResultField(name="deadline", field_type="string"),
            ),
        ),
        AttestedResultField(name="ansvarig", field_type="string"),
    )

    violations = attested_result_contract_violations(
        terminal_fields,
        projection=projection,
    )

    assert [violation.kind for violation in violations] == ["ambiguous_placement"]
    assert set(violations[0].candidate_paths) == {"ansvarig", "beslut[].ansvarig"}
    message = attested_violation_message(violations[0])
    assert "`ansvarig`" in message
    assert "`beslut[].ansvarig`" in message
    assert message.endswith("remove every other occurrence")


def test_nested_canonicalization_moves_complete_attested_groups_in_place() -> None:
    state = _state()
    state.named_result_evidence = [
        NamedResultEvidence(
            name="documents",
            declared_shape="array",
            confidence="high",
            evidence=["quote:user_message:user-1:documents"],
        ),
        NamedResultEvidence(
            name="candidate_passages",
            placement=ExactNamedResultPlacement(segments=("documents",)),
            declared_shape="array",
            confidence="high",
            evidence=["quote:user_message:user-1:candidate_passages"],
        ),
        NamedResultEvidence(
            name="page_or_section",
            placement=ExactNamedResultPlacement(
                segments=("documents", "candidate_passages")
            ),
            confidence="high",
            evidence=["quote:user_message:user-1:page_or_section"],
        ),
        NamedResultEvidence(
            name="excerpt_reference",
            placement=ExactNamedResultPlacement(
                segments=("documents", "candidate_passages")
            ),
            confidence="high",
            evidence=["quote:user_message:user-1:excerpt_reference"],
        ),
    ]
    model_fields = [
        {
            "name": "root_before",
            "field_type": "string",
            "description": "Första fria roten.",
            "required": False,
        },
        {
            "name": "documents",
            "field_type": "array",
            "description": "Handlingarna.",
            "required": False,
            "children": [
                {
                    "name": "document_note",
                    "field_type": "string",
                    "description": "En fri dokumentnotering.",
                    "required": False,
                },
                {
                    "name": "candidate_passages",
                    "field_type": "array",
                    "description": "Kandidatpassagerna.",
                    "required": False,
                    "children": [
                        {
                            "name": "ordinary_a",
                            "field_type": "string",
                            "description": "Första fria fältet.",
                            "required": False,
                        },
                        {
                            "name": "excerpt_reference",
                            "field_type": "string",
                            "description": "Utdragsreferensen.",
                            "required": False,
                        },
                        {
                            "name": "page_or_section",
                            "field_type": "string",
                            "description": "Sida eller avsnitt.",
                            "required": False,
                        },
                        {
                            "name": "ordinary_b",
                            "field_type": "string",
                            "description": "Andra fria fältet.",
                            "required": False,
                        },
                    ],
                },
                {
                    "name": "document_tail",
                    "field_type": "string",
                    "description": "En andra fri dokumentnotering.",
                    "required": False,
                },
            ],
        },
        {
            "name": "unrelated_group",
            "field_type": "object",
            "description": "En orelaterad grupp.",
            "required": False,
            "children": [
                {
                    "name": "untouched_b",
                    "field_type": "string",
                    "description": "Förblir sist.",
                    "required": False,
                },
                {
                    "name": "untouched_a",
                    "field_type": "string",
                    "description": "Förblir näst sist.",
                    "required": False,
                },
            ],
        },
    ]

    spec = _compile_through_the_whole_path(
        state,
        model_output_fields=model_fields,
    )

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert list(contract["properties"]) == [
        "documents",
        "root_before",
        "unrelated_group",
    ]
    documents = contract["properties"]["documents"]
    document_names = list(documents["items"]["properties"])
    assert (
        document_names.index("candidate_passages")
        < document_names.index("document_note")
        < document_names.index("document_tail")
    )
    passages = documents["items"]["properties"]["candidate_passages"]
    assert list(passages["items"]["properties"]) == [
        "page_or_section",
        "excerpt_reference",
        "ordinary_a",
        "ordinary_b",
    ]
    assert set(passages["items"]["required"]) >= {
        "page_or_section",
        "excerpt_reference",
    }
    assert passages["items"]["properties"]["page_or_section"]["type"] == [
        "string",
        "null",
    ]
    unrelated = contract["properties"]["unrelated_group"]
    assert list(unrelated["properties"]) == ["untouched_b", "untouched_a"]
    assert "required" not in unrelated


def test_violations_shape_compiles_three_roots_and_four_nested_children_once() -> None:
    state = _state()
    state.named_result_evidence = [
        NamedResultEvidence(
            name="summary",
            confidence="high",
            evidence=["quote:user_message:user-1:summary"],
        ),
        NamedResultEvidence(
            name="violations",
            declared_shape="array",
            confidence="high",
            evidence=["quote:user_message:user-1:violations"],
        ),
        NamedResultEvidence(
            name="metadata",
            declared_shape="object",
            confidence="high",
            evidence=["quote:user_message:user-1:metadata"],
        ),
        *[
            NamedResultEvidence(
                name=name,
                placement=ExactNamedResultPlacement(segments=("violations",)),
                confidence="high",
                evidence=[f"quote:user_message:user-1:{name}"],
            )
            for name in ("code", "message", "severity", "source_reference")
        ],
    ]
    model_fields = [
        {
            "name": "metadata",
            "field_type": "object",
            "description": "Metadata.",
            "children": [
                {
                    "name": "request_id",
                    "field_type": "string",
                    "description": "Begärans id.",
                }
            ],
        },
        {
            "name": "violations",
            "field_type": "array",
            "description": "Överträdelserna.",
            "children": [
                {
                    "name": name,
                    "field_type": "string",
                    "description": f"Innehållet för {name}.",
                }
                for name in reversed(
                    ("code", "message", "severity", "source_reference")
                )
            ],
        },
        {
            "name": "summary",
            "field_type": "string",
            "description": "Sammanfattningen.",
        },
    ]

    spec = _compile_through_the_whole_path(
        state,
        model_output_fields=model_fields,
    )

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert list(contract["properties"]) == ["summary", "violations", "metadata"]
    children = contract["properties"]["violations"]["items"]["properties"]
    assert list(children) == ["code", "message", "severity", "source_reference"]
    assert not set(children) & (set(contract["properties"]) - {"violations"})


def test_an_exact_model_declaration_compiles_verified_and_canonicalized() -> None:
    # The model declares every attested name itself; verification passes and
    # the compiled contract carries exact spelling, declared shape, required
    # (nullable for primitives), with the attested roots FIRST in projection
    # order and the model's other fields after, in their declared order.
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None

    attested_fields = _attested_model_fields(projection)
    ordinary_a = {
        "name": "reading_notes",
        "field_type": "string",
        "description": "Modellens första egna fält.",
        "required": False,
    }
    ordinary_b = {
        "name": "handlaggare_kommentar",
        "field_type": "string",
        "description": "Modellens andra egna fält.",
        "required": False,
    }
    # Interleave: ordinary, attested reversed, ordinary — canonicalization
    # must pull the attested roots first IN PROJECTION ORDER while the two
    # ordinary fields keep their declared relative order after them.
    interleaved = [
        ordinary_a,
        *reversed(attested_fields),
        ordinary_b,
    ]

    spec = _compile_through_the_whole_path(
        state,
        model_output_fields=interleaved,
    )

    contract = _terminal_output_contract(spec)
    assert contract is not None
    properties = contract["properties"]
    names = list(properties)
    attested = [key.name for key in projection.keys]
    assert names[: len(attested)] == attested
    assert names.index("reading_notes") < names.index("handlaggare_kommentar")
    assert properties["documents"]["type"] == "array"
    assert properties["candidate_passages"]["type"] == "array"
    # Required-but-nullable: a primitive attested root serializes exactly as
    # ["<type>", "null"].
    assert properties["source_reference"]["type"] == ["string", "null"]


def test_a_missing_attested_root_is_rejected_with_the_exact_path() -> None:
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None
    fields = _attested_model_fields(projection)
    dropped = [f for f in fields if f["name"] != "documents"]

    with pytest.raises(ProposalIntentArgumentError) as rejected:
        _compile_through_the_whole_path(state, model_output_fields=dropped)

    issues = list(rejected.value.issues)
    assert len(issues) == 1
    assert issues[0].startswith("steps.0.output_fields: ")
    assert "`documents` must exist at the top level" in issues[0]


def test_a_folded_alias_is_a_rename_error_never_satisfaction() -> None:
    # `Documents` folds onto `documents` but the user attested to the exact
    # spelling; folding only locates the rename for an actionable message.
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None
    fields = _attested_model_fields(projection)
    for f in fields:
        if f["name"] == "documents":
            f["name"] = "Documents"

    with pytest.raises(ProposalIntentArgumentError) as rejected:
        _compile_through_the_whole_path(state, model_output_fields=fields)

    issues = list(rejected.value.issues)
    index = next(i for i, f in enumerate(fields) if f["name"] == "Documents")
    assert issues == [
        f"steps.0.output_fields.{index}.name: rename `Documents` to exactly "
        "`documents` — the user attested to that spelling [value_error]"
    ]


def test_duplicate_attested_roots_are_rejected() -> None:
    # Exactly one field per folded-identity group: an exact root plus a
    # fold-equivalent sibling is a duplicate, even though the spellings
    # differ and typed validation sees two distinct names.
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None
    fields = _attested_model_fields(projection)
    fields.append(
        {
            "name": "Documents",
            "field_type": "array",
            "description": "Vikt dubblett.",
            "required": True,
        }
    )

    with pytest.raises(ProposalIntentArgumentError) as rejected:
        _compile_through_the_whole_path(state, model_output_fields=fields)

    # Typed validation owns folded sibling uniqueness and fires first; the
    # verification predicate's duplicate arm remains as the compiled-side
    # postcondition guard (proven below on the predicate directly).
    assert any("unique among siblings" in issue for issue in rejected.value.issues)
    assert (
        attested_result_contract_violations(
            (
                AttestedResultField(name="documents", field_type="array"),
                AttestedResultField(name="Documents", field_type="array"),
            ),
            projection=ProposalObligationProjection(
                keys=(
                    ObligatedResultKey(
                        name="documents",
                        placement=ExactNamedResultPlacement(),
                        declared_shape="array",
                    ),
                )
            ),
        )[0].kind
        == "duplicate_location"
    )


def test_a_nested_only_occurrence_is_a_missing_root() -> None:
    # Verification sees terminal SIBLINGS only: wrapping an attested name
    # inside a container does not satisfy the contract, and the message says
    # where the field must live.
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None
    fields = _attested_model_fields(projection)
    fields = [f for f in fields if f["name"] != "source_reference"]
    fields.append(
        {
            "name": "wrapper",
            "field_type": "object",
            "description": "Modellens omslag.",
            "required": True,
            "children": [
                {
                    "name": "source_reference",
                    "field_type": "string",
                    "description": "Nästlad kopia.",
                    "required": True,
                }
            ],
        }
    )

    with pytest.raises(ProposalIntentArgumentError) as rejected:
        _compile_through_the_whole_path(state, model_output_fields=fields)

    issues = list(rejected.value.issues)
    assert len(issues) == 1
    assert "`source_reference` must exist at the top level" in issues[0]


def test_a_declared_shape_conflict_is_rejected() -> None:
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None

    with pytest.raises(ProposalIntentArgumentError) as rejected:
        _compile_through_the_whole_path(
            state,
            model_output_fields=_attested_model_fields(
                projection, field_types={"documents": "string"}
            ),
        )

    assert list(rejected.value.issues) == [
        "steps.0.output_fields.0.field_type: `documents[]` must be of type "
        "`array` — the user declared that shape [value_error]"
    ]


def test_an_unshaped_key_accepts_any_legal_structured_type() -> None:
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None
    assert any(
        key.name == "source_reference" and key.declared_shape is None
        for key in projection.keys
    )

    spec = _compile_through_the_whole_path(
        state,
        model_output_fields=_attested_model_fields(
            projection, field_types={"source_reference": "number"}
        ),
    )

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert contract["properties"]["source_reference"]["type"] == [
        "number",
        "null",
    ]


def test_attested_primitive_roots_compile_required_and_nullable() -> None:
    # Owner ruling 2026-08-24: required-but-nullable — the field always
    # exists; a source that lacks it yields an explicit empty value. The type
    # system allows nullable on primitives only, so declared array/object
    # shapes express absence through the empty value convention instead.
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None

    spec = _compile_through_the_whole_path(
        state,
        model_output_fields=_attested_model_fields(projection),
    )

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert set(contract["required"]) >= {key.name for key in projection.keys}
    assert contract["properties"]["source_reference"]["type"] == [
        "string",
        "null",
    ]


def test_the_tool_schema_carries_no_result_keys_sibling() -> None:
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None

    schema = _prepared_schema()
    parameters = schema["function"]["parameters"]
    assert "result_keys" not in parameters["properties"]
    assert "result_keys" not in parameters["required"]


def test_a_replayed_result_keys_argument_is_rejected_as_extra() -> None:
    # The retired sibling has no compatibility reader: typed validation's
    # extra="forbid" rejects it like any unknown argument.
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None
    arguments = _arguments(model_output_fields=_attested_model_fields(projection))
    arguments["result_keys"] = {"documents": {"field_type": "array"}}

    with pytest.raises(ProposalIntentArgumentError) as rejected:
        parse_create_flow_intent_arguments(
            arguments,
            obligation_projection=projection,
        )

    assert any(
        "result_keys" in issue and "extra_forbidden" in issue
        for issue in rejected.value.issues
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
    assert "De namngivna delarna byggs på översta nivån" in disclosure.summary
    assert "översta nivån" in disclosure.summary
    assert "utdataschema" in disclosure.summary

    spec = _compile_through_the_whole_path(
        state,
        model_output_fields=_attested_model_fields(projection),
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

    assert [
        field.label.split(" (", 1)[0] for field in disclosure.named_content_fields
    ] == [name for name, _shape in PUBLIC_RECORD_OBLIGATIONS]
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


def test_many_named_results_confirm_without_a_projection_cap() -> None:
    # The attested contract no longer occupies schema space, so no
    # projection-count refusal exists; planning state's
    # NAMED_RESULT_EVIDENCE_MAX_ITEMS is the single accumulation bound.
    state = _state(tuple((f"field_{index}", None) for index in range(30)))

    decision = _refusal_or_confirmation(state)

    assert isinstance(decision, ConfirmRequirements)


@pytest.mark.parametrize(
    "name",
    ["åtgärder", "foo[]"],
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
    assert tuple(key.name for key in projection.keys) == ("case_id",)
    assert isinstance(_refusal_or_confirmation(state), ConfirmRequirements)


def test_pending_schema_direction_asks_before_the_projection_refuses() -> None:
    # Selecting the attached schema as the output schema stands the projection
    # down entirely, so refusing before that question answers the wrong request.
    state = _state(tuple((f"field_{index}", None) for index in range(13)))

    decision = _refusal_or_confirmation(state, schema_direction_pending=True)

    assert isinstance(decision, AskCanonicalQuestion)
    assert decision.slot_name == "schema_direction"


def test_edit_mode_neither_projects_nor_refuses() -> None:
    state = _state(tuple((f"field_{index}", None) for index in range(13)))

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
def test_the_projection_stands_down_where_no_contract_applies(
    state: PlanningState,
) -> None:
    # The schema is projection-independent by design; standing down means no
    # attested contract is enforced for this turn.
    assert named_result_projection(state) is None


def test_an_exact_declared_output_schema_stands_the_projection_down() -> None:
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    state.output_schema_evidence = build_schema_evidence(
        json_schema={"type": "object", "properties": {"documents": {"type": "array"}}},
        source="declared_schema",
        confidence="high",
        evidence=("quote:user_message:user-1:schema",),
    )

    assert named_result_projection(state) is None


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
            model_output_fields=[
                *_attested_model_fields(projection),
                {
                    "name": "wrapper",
                    "field_type": "object",
                    "description": "Modellens egen behållare.",
                    "required": True,
                    "children": [
                        {
                            "name": "risks",
                            "field_type": "string",
                            "description": "Modellens egna risker.",
                            "required": True,
                        }
                    ],
                },
            ],
        ),
        obligation_projection=projection,
    )

    spec = compile_create_intent_to_spec(
        intent, context=context, obligation_projection=projection
    )

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert "risks" not in contract["properties"]
    assert "risks" in contract["properties"]["wrapper"]["properties"]


def test_named_content_is_listed_without_repeating_it_in_the_summary() -> None:
    # The structured list is the readable owner of these details. Repeating all
    # names in the lead paragraph defeats the list's progressive disclosure and
    # makes long identifier-heavy requirements difficult to scan.
    state = _state(MEETING_ACTION_OBLIGATIONS, primary_runtime_input="audio")

    disclosure = build_requirements_disclosure(state, ui_language="sv")

    assert [
        field.label.split(" (", 1)[0] for field in disclosure.named_content_fields
    ] == [name for name, _ in MEETING_ACTION_OBLIGATIONS]
    assert disclosure.named_content_fields[0].label == (
        "agenda_items (användaren skrev en lista)"
    )
    for field in disclosure.named_content_fields:
        assert field.label not in disclosure.summary


def test_naming_no_content_leaves_the_item_list_empty() -> None:
    state = _state(primary_runtime_input="audio")

    disclosure = build_requirements_disclosure(state, ui_language="sv")

    assert disclosure.named_content_fields == []
    assert "namngett innehåll" not in disclosure.summary


@pytest.mark.parametrize(
    "changed",
    [
        pytest.param((("agenda_items", "array"), ("beslut", None)), id="renamed"),
        pytest.param((("agenda_items", "object"), ("decisions", None)), id="reshaped"),
    ],
)
def test_naming_content_differently_is_a_different_disclosure(
    changed: tuple[tuple[str, NamedResultDeclaredShape | None], ...],
) -> None:
    # The names and the shapes the user wrote next to them reach the version
    # through the summary prose, so a user who confirmed one set of obligations
    # has not confirmed another. That is also why the item list does not need
    # its own place in the hash: it projects facts already inside it.
    baseline = _state(
        (("agenda_items", "array"), ("decisions", None)),
        primary_runtime_input="audio",
    )
    other = _state(changed, primary_runtime_input="audio")

    first = build_requirements_disclosure(baseline, ui_language="sv")
    second = build_requirements_disclosure(other, ui_language="sv")

    assert first.requirements_version != second.requirements_version
    assert [field.label for field in first.named_content_fields] != [
        field.label for field in second.named_content_fields
    ]


def test_named_result_placement_is_visible_and_changes_confirmation_identity() -> None:
    exact = _state(
        (
            ("documents", "array"),
            ("candidate_passages", "array"),
            ("page_or_section", None),
        )
    )
    exact.named_result_evidence = [
        exact.named_result_evidence[0],
        exact.named_result_evidence[1].model_copy(
            update={"placement": ExactNamedResultPlacement(segments=("documents",))}
        ),
        exact.named_result_evidence[2].model_copy(
            update={
                "placement": ExactNamedResultPlacement(
                    segments=("documents", "candidate_passages")
                )
            }
        ),
    ]
    unplaced = exact.model_copy(deep=True)
    unplaced.named_result_evidence = [
        *unplaced.named_result_evidence[:2],
        unplaced.named_result_evidence[2].model_copy(
            update={"placement": UnplacedNamedResultPlacement()}
        ),
    ]

    exact_disclosure = build_requirements_disclosure(exact, ui_language="sv")
    unplaced_disclosure = build_requirements_disclosure(unplaced, ui_language="sv")
    labels = [field.label for field in exact_disclosure.named_content_fields]

    assert [field.segments for field in exact_disclosure.named_content_fields] == [
        [],
        ["documents"],
        ["documents", "candidate_passages"],
    ]
    assert not any(field.unplaced for field in exact_disclosure.named_content_fields)
    assert unplaced_disclosure.named_content_fields[2].unplaced
    assert exact_disclosure.named_content_fields[2].id != "page_or_section"
    assert labels[1] == "candidate_passages (användaren skrev en lista)"
    assert labels[2] == "page_or_section"
    assert unplaced_disclosure.named_content_fields[2].label == "page_or_section"
    assert exact_disclosure.requirements_version != (
        unplaced_disclosure.requirements_version
    )


def test_unplaced_marker_is_localized_in_english() -> None:
    state = _state((("result", None),))
    state.named_result_evidence = [
        state.named_result_evidence[0].model_copy(
            update={"placement": UnplacedNamedResultPlacement()}
        )
    ]

    disclosure = build_requirements_disclosure(state, ui_language="en")

    assert disclosure.named_content_fields[0].label == "result"
    assert disclosure.named_content_fields[0].unplaced


def test_a_field_the_user_typed_into_the_card_is_marked_as_theirs() -> None:
    # The list is also an edit surface, so a reader has to be able to tell a
    # name Eneo heard from a name they added themselves.
    state = _state((("agenda_items", "array"),), primary_runtime_input="audio")
    state.named_result_evidence = [
        *state.named_result_evidence,
        NamedResultEvidence(
            name="Beslutsdatum",
            confidence="high",
            evidence=[named_content_fields_edit_evidence_reference("edit-1")],
        ),
    ]

    disclosure = build_requirements_disclosure(state, ui_language="sv")

    assert [
        (field.label.split(" (", 1)[0], field.origin)
        for field in disclosure.named_content_fields
    ] == [
        ("agenda_items", "described"),
        ("Beslutsdatum", "card_edit"),
    ]
    for field in disclosure.named_content_fields:
        assert field.label not in disclosure.summary


def test_editing_the_field_list_is_a_disclosure_the_user_has_not_confirmed() -> None:
    before = _state(
        (("agenda_items", "array"), ("farhagor", None)),
        primary_runtime_input="audio",
    )
    after = _state((("agenda_items", "array"),), primary_runtime_input="audio")

    assert (
        build_requirements_disclosure(before, ui_language="sv").requirements_version
        != build_requirements_disclosure(after, ui_language="sv").requirements_version
    )


def test_an_attested_name_takes_the_envelope_role_of_its_own_name() -> None:
    # The user named `risks` and the server's envelope wants a `risks` too.
    # The model's own declaration carries both; merging an envelope copy
    # beside it would bind the name twice.
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
    arguments = _arguments(model_output_fields=_attested_model_fields(projection))
    validate_propose_flow_tool_arguments(
        arguments=arguments,
        tool_schema=_prepared_schema(),
    )
    intent = parse_create_flow_intent_arguments(
        arguments,
        obligation_projection=projection,
    )

    spec = compile_create_intent_to_spec(
        intent, context=context, obligation_projection=projection
    )

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert contract["properties"]["risks"]["description"] == "Innehållet för risks."
    risks_count = sum(1 for name in contract["properties"] if name == "risks")
    assert risks_count == 1


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
    intent = parse_create_flow_intent_arguments(
        _arguments(
            model_output_fields=[
                *_attested_model_fields(projection),
                {
                    "name": "risks",
                    "field_type": "string",
                    "description": "Modellens egna risker.",
                    "required": True,
                },
            ]
        ),
        obligation_projection=projection,
    )

    spec = compile_create_intent_to_spec(
        intent, context=context, obligation_projection=projection
    )

    contract = _terminal_output_contract(spec)
    assert contract is not None
    assert contract["properties"]["risks"]["description"] == "Modellens egna risker."


def test_the_compiled_postcondition_fails_closed_on_a_dropped_name() -> None:
    # The SAME predicate admission ran, re-run on the compiled contract: a
    # spec whose terminal contract lost an attested root is a server defect
    # and fails closed as non-repairable, never handed to the model. The
    # retry classifier itself is asserted — the exact seam that once kept a
    # renamed code silently unclassified.
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None
    spec = _compile_through_the_whole_path(
        state,
        model_output_fields=_attested_model_fields(projection),
    )
    terminal = spec.steps[-1]
    contract = dict(terminal.output_contract or {})
    properties = dict(contract.get("properties") or {})
    properties.pop("documents", None)
    contract["properties"] = properties
    doctored = spec.model_copy(
        update={
            "steps": [
                *spec.steps[:-1],
                terminal.model_copy(update={"output_contract": contract}),
            ]
        }
    )

    with pytest.raises(AIBuilderArchitectureError) as failure:
        _spec_satisfying_attested_contract(doctored, projection=projection)

    assert failure.value.log_context["failure_code"] == (
        "attested_result_contract_broken"
    )
    assert "missing_location:documents" in failure.value.log_context["reason"]
    assert failure.value.repair_disposition == "server_defect"


def test_an_earlier_step_may_declare_an_attested_name() -> None:
    # Verification is terminal-only: a leading extraction step may produce a
    # field of the same name that a later step consumes.
    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None

    spec = _compile_through_the_whole_path(
        state,
        model_output_fields=_attested_model_fields(projection),
        leading_step_output_fields=[
            {
                "name": "documents",
                "field_type": "array",
                "description": "Ett tidigare stegs egna fält.",
                "required": True,
            }
        ],
    )

    assert _terminal_output_contract(spec) is not None


def test_the_prompt_names_the_projected_fields_concretely() -> None:
    # Models follow a concrete list far more reliably than an abstract
    # `result_keys` reference; each avoided duplicate is one avoided
    # rejection-repair round trip. The rule appears exactly when the
    # projection exists, through the same owner that admission and the
    # compiled postcondition read, so prompt and verification can never
    # disagree about the names.
    from eneo.flows.ai_builder.ai_builder_plan_proposal_task import (
        build_authoring_brief,
    )

    state = _state(PUBLIC_RECORD_OBLIGATIONS)
    projection = named_result_projection(state)
    assert projection is not None

    prompt = build_authoring_brief(
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[], available_kbs=[]
        ),
    )

    expected_rule = (
        "- The result must contain these exact named results: "
        + ", ".join(
            f"`{projection.render_key_location(key)}`"
            + (f" (type {key.declared_shape})" if key.declared_shape else "")
            for key in projection.keys
        )
        + ". Before submitting, check the FINAL step's output_fields "
        "against this list: (1) every exact result appears at its listed "
        "location in the final step — not in an earlier step or through "
        "an extra wrapper; (2) every placement-not-specified result appears "
        "exactly once anywhere in the final step; (3) spelling is exactly "
        "as written above; (4) each result is declared exactly once at its "
        "location, with an accurate description; (5) named results of "
        "type object or array are declared with nullable false. Missing, "
        "renamed, duplicated, ambiguously placed or wrongly typed results "
        "are rejected."
    )
    assert expected_rule in prompt
    assert prompt.count("The result must contain these exact named results") == 1
    assert not (
        "Only primitive fields (string, number, boolean) may be nullable; "
        "never mark object or array fields nullable." in prompt
    )
    # The prohibition era is over: the positive contract is the only prompt
    # owner of the boundary.
    assert "Never add any of them" not in prompt
    assert "One narrow exception" not in prompt

    empty_prompt = build_authoring_brief(
        planning_state=PlanningState.empty(),
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[], available_kbs=[]
        ),
    )
    assert "The backend already declares these user-named result fields" not in (
        empty_prompt
    )


def test_the_prompt_names_exact_paths_and_marks_unplaced_results() -> None:
    from eneo.flows.ai_builder.ai_builder_plan_proposal_task import (
        build_authoring_brief,
    )

    state = _state()
    state.named_result_evidence = [
        NamedResultEvidence(
            name="documents",
            declared_shape="array",
            confidence="high",
            evidence=["quote:user_message:user-1:documents"],
        ),
        NamedResultEvidence(
            name="candidate_passages",
            placement=ExactNamedResultPlacement(segments=("documents",)),
            declared_shape="array",
            confidence="high",
            evidence=["quote:user_message:user-1:candidate_passages"],
        ),
        NamedResultEvidence(
            name="page_or_section",
            placement=ExactNamedResultPlacement(
                segments=("documents", "candidate_passages")
            ),
            confidence="high",
            evidence=["quote:user_message:user-1:page_or_section"],
        ),
        NamedResultEvidence(
            name="owner",
            placement=UnplacedNamedResultPlacement(),
            confidence="high",
            evidence=["quote:user_message:user-1:owner"],
        ),
    ]

    prompt = build_authoring_brief(
        planning_state=state,
        attachment_context=None,
        flow_context=None,
        is_edit_mode=False,
        resource_catalog=build_ai_builder_resource_catalog(
            available_models=[], available_kbs=[]
        ),
    )

    assert "`documents[]` (type array)" in prompt
    assert "`documents[].candidate_passages[]` (type array)" in prompt
    assert "`documents[].candidate_passages[].page_or_section`" in prompt
    assert "`owner` (placement not specified)" in prompt
    assert "every exact result appears at its listed location" in prompt
    assert "every placement-not-specified result appears exactly once" in prompt
    assert "every attested name appears at the top level" not in prompt
