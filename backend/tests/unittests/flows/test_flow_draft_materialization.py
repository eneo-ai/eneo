from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple, get_type_hints
from uuid import UUID, uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_form_fields import (
    extract_form_fields_from_metadata,
)
from eneo.flows.application.flow_draft_materialization import (
    FlowDraftStepChangeKind,
    InvalidExistingStepRefReason,
    _invalid_existing_step_ref,
    compile_flow_draft_changeset,
    invalid_existing_step_ref_reason,
    validate_existing_step_ref_coverage,
)
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.enums import FlowInputSource
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    FormFieldSpec,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from eneo.flows.flow_metadata import normalize_flow_metadata_for_write
from eneo.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy
from eneo.main.exceptions import BadRequestException
from tests.unittests.flows.source_ref_runtime_test_support import (
    runtime_source_ref_text,
)


def _step_spec(
    *,
    plan_step_ref: str = "step_a",
    existing_step_ref: str | None = None,
    name: str = "Draft step",
    instructions: str = "Use {{ step_a.output.text }}.",
    input_source: InputSource = InputSource.FLOW_INPUT,
    input_type: InputType = InputType.TEXT,
    output_mode: OutputMode = OutputMode.PASS_THROUGH,
    output_type: OutputType = OutputType.TEXT,
    input_bindings: dict | None = None,
    output_config: dict | None = None,
) -> StepSpec:
    return StepSpec(
        plan_step_ref=plan_step_ref,
        existing_step_ref=existing_step_ref,
        name=name,
        assistant_spec=AssistantSpec(instructions=instructions),
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        input_bindings=input_bindings,
        output_config=output_config,
    )


def _flow_step(
    *,
    step_order: int,
    assistant_id: UUID | None = None,
    output_mode: str = "pass_through",
    output_config: dict | None = None,
) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=assistant_id or uuid4(),
        step_order=step_order,
        user_description=f"Existing {step_order}",
        input_source="flow_input",
        input_type="text",
        output_mode=output_mode,
        output_type="text",
        output_config=output_config,
    )


def _flow(*steps: FlowStep, metadata_json: dict | None = None) -> Flow:
    return Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Existing flow",
        description="Existing description",
        steps=list(steps),
        metadata_json=metadata_json,
    )


def test_shared_compile_does_not_stamp_ai_builder_metadata() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Audio flow",
        flow_description="Transcribes audio",
        form_fields=[
            FormFieldSpec(
                name="case_id",
                type="text",
                label="Case id",
                required=True,
            )
        ],
        steps=[
            _step_spec(
                input_type=InputType.AUDIO,
                instructions="Transcribe this.",
            )
        ],
    )

    changeset = compile_flow_draft_changeset(
        spec,
        current_flow=None,
        default_transcription_model_id=uuid4(),
    )

    assert changeset.metadata_json is not None
    assert changeset.metadata_json["form_schema"]["fields"][0]["name"] == "case_id"
    assert changeset.metadata_json["wizard"]["transcription_enabled"] is True
    assert "ai_builder" not in changeset.metadata_json


def test_shared_compile_distinguishes_absent_and_empty_form_fields() -> None:
    existing_form_schema = {
        "fields": [
            {
                "name": "case_id",
                "type": "text",
                "label": "Case id",
                "required": True,
            }
        ]
    }
    current_flow = _flow(metadata_json={"form_schema": existing_form_schema})

    absent_fields = compile_flow_draft_changeset(
        FlowDraftSpecCore(flow_name="Updated flow", steps=[], form_fields=None),
        current_flow=current_flow,
    )
    empty_fields = compile_flow_draft_changeset(
        FlowDraftSpecCore(flow_name="Updated flow", steps=[], form_fields=[]),
        current_flow=current_flow,
    )

    assert absent_fields.metadata_json is not None
    assert absent_fields.metadata_json["form_schema"] == existing_form_schema
    assert empty_fields.metadata_json is not None
    assert empty_fields.metadata_json["form_schema"] == {"fields": []}


# The editor saves `order` and may keep keys the authoring view does not model.
_SAVED_FIELDS = [
    {
        "name": "case_id",
        "type": "text",
        "label": "Case id",
        "required": True,
        "order": 1,
        "placeholder": "BAB-2026-0417",
    },
    {
        "name": "amount",
        "type": "number",
        "label": "Amount",
        "required": True,
        "order": 2,
    },
]


def _authored(*fields: tuple[str, str, str]) -> list[FormFieldSpec]:
    return [
        FormFieldSpec(name=name, type=type_, label=label, required=True)
        for name, type_, label in fields
    ]


def _form_fields_after(authored: list[FormFieldSpec], saved: list[dict]) -> list[dict]:
    changeset = compile_flow_draft_changeset(
        FlowDraftSpecCore(flow_name="Flow", steps=[], form_fields=authored),
        current_flow=_flow(metadata_json={"form_schema": {"fields": saved}}),
    )
    assert changeset.metadata_json is not None
    return changeset.metadata_json["form_schema"]["fields"]


def test_an_edit_that_leaves_the_form_alone_keeps_every_saved_field_key() -> None:
    authored = _authored(("case_id", "text", "Case id"), ("amount", "number", "Amount"))

    assert _form_fields_after(authored, _SAVED_FIELDS) == _SAVED_FIELDS


def test_an_edited_field_keeps_the_keys_the_edit_did_not_author() -> None:
    authored = _authored(
        ("case_id", "text", "Diarienummer"), ("amount", "number", "Amount")
    )

    fields = _form_fields_after(authored, _SAVED_FIELDS)

    assert fields[0] == {**_SAVED_FIELDS[0], "label": "Diarienummer"}
    assert fields[1] == _SAVED_FIELDS[1]


def test_added_and_reordered_fields_follow_the_authored_order() -> None:
    authored = _authored(
        ("amount", "number", "Amount"),
        ("applicant", "text", "Applicant"),
        ("case_id", "text", "Case id"),
    )

    fields = _form_fields_after(authored, _SAVED_FIELDS)

    assert [(field["name"], field.get("order")) for field in fields] == [
        ("amount", 1),
        ("applicant", 2),
        ("case_id", 3),
    ]
    assert fields[2]["placeholder"] == "BAB-2026-0417"
    assert "placeholder" not in fields[1]


def test_a_form_saved_without_order_gets_none_added() -> None:
    saved = [
        {key: value for key, value in field.items() if key != "order"}
        for field in _SAVED_FIELDS
    ]
    authored = _authored(("case_id", "text", "Case id"), ("amount", "number", "Amount"))

    assert _form_fields_after(authored, saved) == saved


@pytest.mark.parametrize(
    "saved",
    [
        # Valid and shown first-then-second: the runtime sorts by order.
        [
            {"name": "second", "type": "text", "label": "Second", "order": 2},
            {"name": "first", "type": "text", "label": "First", "order": 1},
        ],
        # The editor shows an unlabelled field by its name.
        [{"name": "case_id", "type": "text", "label": None, "required": True}],
        # An absent order is valid beside a present one.
        [
            {"name": "explicit", "type": "text", "label": "Explicit", "order": 2},
            {"name": "implicit", "type": "text", "label": "Implicit"},
        ],
    ],
    ids=["order-differs-from-array", "unlabelled", "mixed-order"],
)
def test_an_edit_that_reads_the_form_back_unchanged_keeps_it_as_saved(
    saved: list[dict],
) -> None:
    authored = extract_form_fields_from_metadata({"form_schema": {"fields": saved}})
    assert authored is not None

    assert _form_fields_after(authored, saved) == saved


def test_a_field_added_to_a_mixed_order_form_keeps_what_the_run_form_showed() -> None:
    saved = [
        {"name": "explicit", "type": "text", "label": "Explicit", "order": 2},
        {"name": "implicit", "type": "text", "label": "Implicit"},
    ]
    read_back = extract_form_fields_from_metadata({"form_schema": {"fields": saved}})
    assert read_back is not None

    fields = _form_fields_after(
        [*read_back, *_authored(("added", "text", "Added"))], saved
    )

    assert [(field["name"], field["order"]) for field in fields] == [
        ("explicit", 1),
        ("implicit", 2),
        ("added", 3),
    ]


@pytest.mark.parametrize("legacy", [0, "2", None], ids=["zero", "text", "null"])
def test_an_unrelated_edit_makes_tolerated_legacy_orders_writable(
    legacy: object,
) -> None:
    saved = [
        {"name": "case_id", "type": "text", "label": "Case id", "order": legacy},
        {"name": "amount", "type": "number", "label": "Amount", "order": 2},
    ]
    read_back = extract_form_fields_from_metadata({"form_schema": {"fields": saved}})
    assert read_back is not None

    fields = _form_fields_after(read_back, saved)

    assert normalize_flow_metadata_for_write({"form_schema": {"fields": fields}})
    assert [(field["name"], field["order"]) for field in fields] == [
        ("case_id", 1),
        ("amount", 2),
    ]


def test_shared_compile_preserves_output_config_when_output_mode_is_unchanged() -> None:
    existing_config = {"template_asset_id": "template-a"}
    existing_step = _flow_step(
        step_order=1,
        output_mode="pass_through",
        output_config=existing_config,
    )
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(
                existing_step_ref="existing_step_1",
                output_mode=OutputMode.PASS_THROUGH,
                output_config=None,
            )
        ],
    )

    changeset = compile_flow_draft_changeset(spec, current_flow=_flow(existing_step))

    assert changeset.compiled_steps[0].output_config == existing_config


def test_shared_compile_drops_output_config_when_output_mode_changes() -> None:
    existing_step = _flow_step(
        step_order=1,
        output_mode="pass_through",
        output_config={"template_asset_id": "template-a"},
    )
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(
                existing_step_ref="existing_step_1",
                output_mode=OutputMode.TEMPLATE_FILL,
                output_type=OutputType.DOCX,
                output_config=None,
            )
        ],
    )

    changeset = compile_flow_draft_changeset(spec, current_flow=_flow(existing_step))

    assert changeset.compiled_steps[0].output_config is None


def test_shared_compile_preserves_every_existing_step_without_removals() -> None:
    current_flow = _flow(_flow_step(step_order=1), _flow_step(step_order=2))
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
            _step_spec(plan_step_ref="step_b", existing_step_ref="existing_step_2"),
        ],
    )

    changeset = compile_flow_draft_changeset(spec, current_flow=current_flow)

    assert changeset.removed_existing_step_refs == frozenset()
    assert [step.change_kind for step in changeset.compiled_steps] == [
        FlowDraftStepChangeKind.MODIFIED,
        FlowDraftStepChangeKind.MODIFIED,
    ]


def test_shared_compile_only_updates_explicitly_modified_existing_steps() -> None:
    first = _flow_step(step_order=1)
    second = _flow_step(step_order=2)
    third = _flow_step(step_order=3)
    current_flow = _flow(first, second, third)
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
            _step_spec(plan_step_ref="step_b", existing_step_ref="existing_step_2"),
            _step_spec(
                plan_step_ref="step_c",
                existing_step_ref="existing_step_3",
                instructions="Updated conclusion instructions.",
            ),
        ],
    )

    changeset = compile_flow_draft_changeset(
        spec,
        current_flow=current_flow,
        updated_existing_step_refs=frozenset({"existing_step_3"}),
    )

    assert [
        update.existing_assistant_id for update in changeset.assistants_to_update
    ] == [third.assistant_id]
    assert [step.change_kind for step in changeset.compiled_steps] == [
        FlowDraftStepChangeKind.UNCHANGED,
        FlowDraftStepChangeKind.UNCHANGED,
        FlowDraftStepChangeKind.MODIFIED,
    ]


def test_shared_compile_removes_only_explicit_removed_existing_step() -> None:
    removed_assistant_id = uuid4()
    current_flow = _flow(
        _flow_step(step_order=1),
        _flow_step(step_order=2, assistant_id=removed_assistant_id),
    )
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
        ],
    )

    changeset = compile_flow_draft_changeset(
        spec,
        current_flow=current_flow,
        removed_existing_step_refs=frozenset({"existing_step_2"}),
    )

    assert changeset.removed_existing_step_refs == frozenset({"existing_step_2"})
    assert removed_assistant_id not in {
        step.assistant_id for step in changeset.compiled_steps
    }


def test_shared_compile_rejects_omitted_existing_step_without_explicit_removal() -> (
    None
):
    current_flow = _flow(_flow_step(step_order=1), _flow_step(step_order=2))
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(spec, current_flow=current_flow)

    assert exc_info.value.code == "invalid_existing_step_ref"
    assert exc_info.value.context == {
        "reason": "missing_existing_step_ref",
        "missing_refs": ["existing_step_2"],
    }


def test_an_invalid_existing_step_ref_reason_is_one_of_a_closed_set() -> None:
    # Pyright holds every producer to this Literal: an undeclared reason, or a
    # plain str, does not type-check. This keeps the parameter from widening.
    assert (
        get_type_hints(_invalid_existing_step_ref)["reason"]
        is InvalidExistingStepRefReason
    )


def test_the_reason_reader_returns_only_a_declared_reason() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        validate_existing_step_ref_coverage(
            current_refs={"existing_step_1", "existing_step_2"},
            preserved_refs=["existing_step_1"],
            removed_existing_step_refs=frozenset(),
        )
    undeclared = [
        BadRequestException(
            "Undeclared.",
            code="invalid_existing_step_ref",
            context={"reason": "not_a_declared_reason"},
        ),
        BadRequestException("No reason.", code="invalid_existing_step_ref"),
        BadRequestException(
            "Other code.",
            code="bad_request",
            context={"reason": "missing_existing_step_ref"},
        ),
    ]

    assert invalid_existing_step_ref_reason(exc_info.value) == (
        "missing_existing_step_ref"
    )
    assert [invalid_existing_step_ref_reason(error) for error in undeclared] == [
        None,
        None,
        None,
    ]


def test_shared_compile_rejects_unknown_removed_existing_step_ref() -> None:
    current_flow = _flow(_flow_step(step_order=1))
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(
            spec,
            current_flow=current_flow,
            removed_existing_step_refs=frozenset({"existing_step_99"}),
        )

    assert exc_info.value.code == "invalid_existing_step_ref"
    assert exc_info.value.context == {
        "reason": "unknown_removed_existing_step_ref",
        "unknown_refs": ["existing_step_99"],
    }


def test_shared_compile_rejects_unknown_preserved_existing_step_ref() -> None:
    current_flow = _flow(_flow_step(step_order=1))
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_99"),
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(
            spec,
            current_flow=current_flow,
            removed_existing_step_refs=frozenset({"existing_step_1"}),
        )

    assert exc_info.value.code == "invalid_existing_step_ref"
    assert exc_info.value.context == {
        "reason": "unknown_existing_step_ref",
        "unknown_refs": ["existing_step_99"],
        "valid_refs": ["existing_step_1"],
    }


def test_shared_compile_rejects_preserved_and_removed_existing_ref_overlap() -> None:
    current_flow = _flow(_flow_step(step_order=1))
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(
            spec,
            current_flow=current_flow,
            removed_existing_step_refs=frozenset({"existing_step_1"}),
        )

    assert exc_info.value.code == "invalid_existing_step_ref"
    assert exc_info.value.context == {
        "reason": "preserved_and_removed_existing_step_ref",
        "overlap_refs": ["existing_step_1"],
    }


def test_shared_compile_rejects_duplicate_existing_step_ref() -> None:
    current_flow = _flow(_flow_step(step_order=1))
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
            _step_spec(plan_step_ref="step_b", existing_step_ref="existing_step_1"),
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(spec, current_flow=current_flow)

    assert exc_info.value.code == "invalid_existing_step_ref"
    assert exc_info.value.context == {
        "reason": "duplicate_existing_step_ref",
        "duplicate_refs": ["existing_step_1"],
    }


def test_shared_compile_reorder_preserves_existing_step_identity() -> None:
    first_assistant_id = uuid4()
    second_assistant_id = uuid4()
    current_flow = _flow(
        _flow_step(step_order=1, assistant_id=first_assistant_id),
        _flow_step(step_order=2, assistant_id=second_assistant_id),
    )
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="step_b", existing_step_ref="existing_step_2"),
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
        ],
    )

    changeset = compile_flow_draft_changeset(spec, current_flow=current_flow)

    assert [step.assistant_id for step in changeset.compiled_steps] == [
        second_assistant_id,
        first_assistant_id,
    ]
    assert changeset.removed_existing_step_refs == frozenset()


def test_shared_compile_rejects_create_spec_with_existing_step_ref() -> None:
    spec = FlowDraftSpecCore(
        flow_name="New flow",
        steps=[
            _step_spec(plan_step_ref="step_a", existing_step_ref="existing_step_1"),
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(spec, current_flow=None)

    assert exc_info.value.code == "invalid_existing_step_ref"
    assert exc_info.value.context == {
        "reason": "create_cannot_use_existing_step_ref",
        "existing_step_ref": "existing_step_1",
    }


def test_shared_compile_rejects_create_with_removed_existing_step_refs() -> None:
    spec = FlowDraftSpecCore(
        flow_name="New flow",
        steps=[_step_spec(plan_step_ref="step_a")],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(
            spec,
            current_flow=None,
            removed_existing_step_refs=frozenset({"existing_step_1"}),
        )

    assert exc_info.value.code == "invalid_existing_step_ref"
    assert exc_info.value.context == {
        "reason": "create_cannot_remove_existing_step_refs",
        "removed_refs": ["existing_step_1"],
    }


def test_shared_compile_compiles_generic_edit_changeset_shape() -> None:
    existing_assistant_id = uuid4()
    removed_assistant_id = uuid4()
    current_flow = _flow(
        _flow_step(
            step_order=1,
            assistant_id=existing_assistant_id,
            output_config={"template_asset_id": "template-a"},
        ),
        _flow_step(step_order=2, assistant_id=removed_assistant_id),
    )
    spec = FlowDraftSpecCore(
        flow_name="Updated flow",
        flow_description="Updated description",
        form_fields=[FormFieldSpec(name="case_id", type="text", label="Case id")],
        steps=[
            _step_spec(
                plan_step_ref="collect",
                existing_step_ref="existing_step_1",
                name="Collect",
                input_bindings={"question": "Use {{ collect.output.text }}"},
            ),
            _step_spec(
                plan_step_ref="summarize",
                name="Summarize",
                instructions="Summarize {{ collect.output.text }}.",
                input_source=InputSource.PREVIOUS_STEP,
            ),
        ],
    )

    removed_refs = frozenset({"existing_step_2"})
    shared = compile_flow_draft_changeset(
        spec,
        current_flow=current_flow,
        removed_existing_step_refs=removed_refs,
    )
    assert shared.metadata_json is not None
    assert shared.metadata_json["form_schema"]["fields"][0]["name"] == "case_id"
    assert shared.compiled_steps[0].change_kind is FlowDraftStepChangeKind.MODIFIED
    assert shared.compiled_steps[1].change_kind is FlowDraftStepChangeKind.ADDED
    assert shared.removed_existing_step_refs == removed_refs


def test_shared_compile_preserves_source_refs_with_runtime_step_refs() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Source material flow",
        steps=[
            _step_spec(plan_step_ref="step_a", name="Collect"),
            _step_spec(
                plan_step_ref="step_b",
                name="Summarize",
                input_source=InputSource.PREVIOUS_STEP,
                input_bindings={
                    "question": "Write the final memo.",
                    "source_refs": [
                        {
                            "step_ref": "step_a",
                            "output": "text",
                            "label": "Transcript",
                        },
                        {
                            "step_ref": "step_a",
                            "output": "structured",
                            "field_path": "decisions",
                            "label": "Decisions",
                        },
                    ],
                },
            ),
        ],
    )

    shared = compile_flow_draft_changeset(spec, current_flow=None)

    assert shared.compiled_steps[1].input_bindings == {
        "question": "Write the final memo.",
        "source_refs": [
            {
                "step_ref": "step_1",
                "output": "text",
                "label": "Transcript",
            },
            {
                "step_ref": "step_1",
                "output": "structured",
                "field_path": "decisions",
                "label": "Decisions",
            },
        ],
    }


def test_shared_compile_leaves_unmapped_source_ref_unchanged() -> None:
    spec = FlowDraftSpecCore(
        flow_name="Source material flow",
        steps=[
            _step_spec(
                plan_step_ref="step_b",
                name="Summarize",
                input_source=InputSource.PREVIOUS_STEP,
                input_bindings={
                    "source_refs": [{"step_ref": "existing_step_1", "output": "text"}],
                },
            ),
        ],
    )

    shared = compile_flow_draft_changeset(spec, current_flow=None)

    assert shared.compiled_steps[0].input_bindings == {
        "source_refs": [{"step_ref": "existing_step_1", "output": "text"}]
    }


def test_shared_compile_ignores_document_body_writer_refs() -> None:
    steps = [
        _step_spec(plan_step_ref="step_a"),
        _step_spec(plan_step_ref="step_b", input_source=InputSource.PREVIOUS_STEP),
    ]
    base = FlowDraftSpecCore(flow_name="Updated flow", steps=steps)
    with_refs = FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=steps,
        document_body_writer_step_refs=("step_b",),
    )

    assert compile_flow_draft_changeset(
        with_refs,
        current_flow=None,
    ) == compile_flow_draft_changeset(base, current_flow=None)


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(
    "input_config",
    [None, {"runtime_input": False}, {"runtime_input": {"enabled": False}}],
)
def test_shared_compile_preserves_authored_disabled_upload(
    existing: bool, input_config: dict | None
) -> None:
    step = _step_spec(
        input_type=InputType.DOCUMENT,
        existing_step_ref="existing_step_1" if existing else None,
    ).model_copy(update={"input_config": input_config})
    changeset = compile_flow_draft_changeset(
        FlowDraftSpecCore(flow_name="Authored flow", steps=[step]),
        current_flow=_flow(_flow_step(step_order=1)) if existing else None,
    )

    assert changeset.compiled_steps[0].input_config == input_config


def test_a_saved_column_the_edit_did_not_change_is_carried_as_saved() -> None:
    """The spec shows a padded question stripped. The edit did not change it,
    so the compiled step keeps the saved text; a column the edit did change
    takes the spec's value."""

    saved = _flow_step(step_order=1).model_copy(
        update={
            "input_bindings": {"question": "  Läs {{ x }}\n"},
            "output_config": {"citation_mode": "off"},
        }
    )
    changeset = compile_flow_draft_changeset(
        FlowDraftSpecCore(
            flow_name="Flow",
            steps=[
                _step_spec(
                    plan_step_ref="a",
                    existing_step_ref="existing_step_1",
                    name="Existing 1",
                    input_bindings={"question": "Läs {{ x }}"},
                    output_config={"citation_mode": "inline_inref_sidecar"},
                )
            ],
        ),
        current_flow=_flow(saved),
    )

    (compiled,) = changeset.compiled_steps
    assert compiled.input_bindings == {"question": "  Läs {{ x }}\n"}
    assert compiled.output_config == {"citation_mode": "inline_inref_sidecar"}
    assert compiled.user_description == "Existing 1"


def test_a_saved_reference_to_a_step_that_moved_is_written_at_its_new_position() -> (
    None
):
    """Carrying what was saved must not carry a position the producer left:
    the reference differs from the saved one, so the spec's is used."""

    producer = _flow_step(step_order=1)
    consumer = _flow_step(step_order=2).model_copy(
        update={"input_bindings": {"question": "Skriv {{ step_1.output.text }}"}}
    )
    changeset = compile_flow_draft_changeset(
        FlowDraftSpecCore(
            flow_name="Flow",
            steps=[
                _step_spec(plan_step_ref="new", name="Ny"),
                _step_spec(
                    plan_step_ref="p1",
                    existing_step_ref="existing_step_1",
                    name="Existing 1",
                ),
                _step_spec(
                    plan_step_ref="p2",
                    existing_step_ref="existing_step_2",
                    name="Existing 2",
                    input_source=InputSource.PREVIOUS_STEP,
                    input_bindings={"question": "Skriv {{ p1.output.text }}"},
                ),
            ],
        ),
        current_flow=_flow(producer, consumer),
    )

    assert changeset.compiled_steps[2].input_bindings == {
        "question": "Skriv {{ step_2.output.text }}"
    }


def _compile_pair(
    saved_consumer: dict,
    *,
    consumer_spec: dict,
    updated: frozenset[str] | None,
    saved_producer: dict | None = None,
    producer_first: bool = False,
):
    """A saved producer and consumer compiled with the consumer's spec given,
    optionally with a new step added in front of both."""

    producer = _flow_step(step_order=1).model_copy(update=saved_producer or {})
    consumer = FlowStep.model_validate(
        {
            **_flow_step(step_order=2).model_dump(),
            "input_source": "previous_step",
            **saved_consumer,
        }
    )
    steps = [
        _step_spec(
            plan_step_ref="p1", existing_step_ref="existing_step_1", name="Existing 1"
        ),
        _step_spec(
            plan_step_ref="p2",
            existing_step_ref="existing_step_2",
            input_source=InputSource.PREVIOUS_STEP,
            **consumer_spec,
        ),
    ]
    if producer_first:
        steps.insert(0, _step_spec(plan_step_ref="new", name="Ny"))
    return compile_flow_draft_changeset(
        FlowDraftSpecCore(flow_name="Flow", steps=steps),
        current_flow=_flow(producer, consumer),
        updated_existing_step_refs=updated,
    )


def test_a_step_no_change_names_is_its_saved_row_whatever_the_spec_says() -> None:
    """The spec carries the validators' form of every step, and the origin's
    policy its own derivations. A step no admitted change names takes none of
    it: description NULL, `{}` configs and the author's spacing stay."""

    changeset = _compile_pair(
        {
            "user_description": None,
            "input_bindings": {"question": "  Skriv {{step_1.output.text}}\n"},
            "input_config": {},
            "output_config": {},
        },
        consumer_spec={
            "name": "Ett annat namn",
            "input_bindings": {"question": "Skriv {{ p1.output.text }}"},
            "output_config": {"citation_mode": "off"},
        },
        updated=frozenset(),
    )

    consumer = changeset.compiled_steps[1]
    assert consumer.change_kind is FlowDraftStepChangeKind.UNCHANGED
    assert consumer.user_description is None
    assert consumer.input_bindings == {"question": "  Skriv {{step_1.output.text}}\n"}
    assert consumer.input_config == {}
    assert consumer.output_config == {}
    assert changeset.assistants_to_update == []


def test_a_step_no_change_names_keeps_every_saved_column_the_spec_shows_otherwise() -> (
    None
):
    """Its input and output modes, contracts and review policy are the saved
    ones, though the spec gives other values for each."""

    saved = {
        "input_source": "all_previous_steps",
        "input_type": "json",
        "output_mode": "render_verbatim",
        "output_type": "json",
        "input_contract": {"type": "object", "properties": {"a": {"type": "string"}}},
        "output_contract": {"type": "object", "properties": {"b": {"type": "number"}}},
        "review_policy": FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW),
    }
    changeset = _compile_pair(saved, consumer_spec={}, updated=frozenset())

    consumer = changeset.compiled_steps[1]
    assert {column: getattr(consumer, column) for column in saved} == saved


def test_a_step_no_change_names_has_only_the_alias_of_a_moved_step_renumbered() -> None:
    changeset = _compile_pair(
        {
            "input_bindings": {
                "question": "Skriv {{step_1.output.text}} och {{ step_1 }}, "
                "inte step_1 eller {{ step_10.x }}",
                "source_refs": [{"step_ref": "step_1", "field": "svar"}],
            },
            "output_mode": "template_fill",
            "output_config": {
                "bindings": {"footer": "{{step_1.output.text}}"},
                "note": "{{step_1.output.text}}",
            },
        },
        consumer_spec={"input_bindings": {"question": "Skriv {{ p1.output.text }}"}},
        updated=frozenset(),
        producer_first=True,
    )

    consumer = changeset.compiled_steps[2]
    assert consumer.input_bindings == {
        "question": "Skriv {{step_2.output.text}} och {{ step_2 }}, "
        "inte step_1 eller {{ step_10.x }}",
        "source_refs": [{"step_ref": "step_2", "field": "svar"}],
    }
    # Only the bindings of a template fill are read; the other key is data.
    assert consumer.output_config == {
        "bindings": {"footer": "{{step_2.output.text}}"},
        "note": "{{step_1.output.text}}",
    }


def test_a_step_the_edit_names_keeps_no_description_until_it_is_renamed() -> None:
    kept = _compile_pair(
        {"user_description": None},
        consumer_spec={"name": "Step 2"},
        updated=frozenset({"existing_step_2"}),
    )
    renamed = _compile_pair(
        {"user_description": None},
        consumer_spec={"name": "Granska"},
        updated=frozenset({"existing_step_2"}),
    )

    assert kept.compiled_steps[1].user_description is None
    assert renamed.compiled_steps[1].user_description == "Granska"


def test_a_step_the_edit_names_keeps_the_saved_spacing_of_bindings_it_did_not_change() -> (
    None
):
    changeset = _compile_pair(
        {"input_bindings": {"question": "Skriv {{step_1.output.text}}"}},
        consumer_spec={"input_bindings": {"question": "Skriv {{ p1.output.text }}"}},
        updated=frozenset({"existing_step_2"}),
    )

    assert changeset.compiled_steps[1].input_bindings == {
        "question": "Skriv {{step_1.output.text}}"
    }


def test_a_binding_that_differs_from_the_saved_one_only_in_json_type_is_the_specs() -> (
    None
):
    """`True` is not `1` in a saved value: the edit changed it, so the step is
    written with what the spec says, not with what was saved."""

    changeset = _compile_pair(
        {"input_bindings": {"flag": 1, "ratio": 1.0}},
        consumer_spec={"input_bindings": {"flag": True, "ratio": 1}},
        updated=frozenset({"existing_step_2"}),
    )

    bindings = changeset.compiled_steps[1].input_bindings
    assert bindings is not None
    assert bindings["flag"] is True
    assert isinstance(bindings["ratio"], int)
    assert not isinstance(bindings["ratio"], float)


def test_a_step_the_edit_names_has_the_alias_of_a_moved_step_renumbered_in_what_it_keeps() -> (
    None
):
    changeset = _compile_pair(
        {"input_bindings": {"question": "Skriv {{step_1.output.text}}"}},
        consumer_spec={"input_bindings": {"question": "Skriv {{ p1.output.text }}"}},
        updated=frozenset({"existing_step_2"}),
        producer_first=True,
    )

    assert changeset.compiled_steps[2].input_bindings == {
        "question": "Skriv {{step_2.output.text}}"
    }


def test_a_named_step_keeping_its_saved_output_config_reads_moved_steps_where_they_are() -> (
    None
):
    """The spec gives the step no output config, so it keeps the saved one; a
    template binding in it that reads a step that moved reads its new place."""

    changeset = _compile_pair(
        {
            "output_mode": "template_fill",
            "output_config": {"bindings": {"sammanfattning": "{{step_1.output.text}}"}},
        },
        consumer_spec={"output_mode": OutputMode.TEMPLATE_FILL},
        updated=frozenset({"existing_step_2"}),
        producer_first=True,
    )

    assert changeset.compiled_steps[2].output_config == {
        "bindings": {"sammanfattning": "{{step_2.output.text}}"}
    }


def _two_step_flow() -> Flow:
    return _flow(_flow_step(step_order=1), _flow_step(step_order=2))


def _two_step_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Updated flow",
        steps=[
            _step_spec(plan_step_ref="a", existing_step_ref="existing_step_1"),
            _step_spec(plan_step_ref="b", existing_step_ref="existing_step_2"),
        ],
    )


def test_a_modified_step_updates_its_assistant_only_in_the_fields_the_edit_names() -> (
    None
):
    changeset = compile_flow_draft_changeset(
        _two_step_spec(),
        current_flow=_two_step_flow(),
        updated_existing_step_refs=frozenset({"existing_step_1", "existing_step_2"}),
        updated_assistant_fields={"existing_step_2": frozenset({"instructions"})},
    )

    # Step 1 is modified but names no assistant field: its assistant is not
    # written. Step 2 names instructions and nothing more.
    assert [step.change_kind for step in changeset.compiled_steps] == [
        FlowDraftStepChangeKind.MODIFIED
    ] * 2
    assert [
        (update.existing_step_ref, update.fields)
        for update in changeset.assistants_to_update
    ] == [("existing_step_2", frozenset({"instructions"}))]


def test_an_update_without_a_field_map_writes_every_assistant_field() -> None:
    changeset = compile_flow_draft_changeset(
        _two_step_spec(), current_flow=_two_step_flow()
    )

    assert [update.fields for update in changeset.assistants_to_update] == [
        frozenset({"instructions", "model_ref", "knowledge_refs"})
    ] * 2


def test_assistant_fields_naming_a_step_that_is_not_updated_are_refused() -> None:
    with pytest.raises(BadRequestException) as refused:
        compile_flow_draft_changeset(
            _two_step_spec(),
            current_flow=_two_step_flow(),
            updated_existing_step_refs=frozenset({"existing_step_1"}),
            updated_assistant_fields={"existing_step_2": frozenset({"instructions"})},
        )

    assert invalid_existing_step_ref_reason(refused.value) == (
        "invalid_updated_existing_step_refs"
    )


def _consumer_flow_and_spec(*, producer_first: bool) -> tuple[Flow, FlowDraftSpecCore]:
    """Saved: a producer at 2 and a consumer at 3 whose prompt reads it. The
    edit adds a step before the producer (or not), and lists the consumer."""

    saved = _flow(
        _flow_step(step_order=1),
        _flow_step(step_order=2),
        _flow_step(step_order=3),
    )
    steps = [
        _step_spec(
            plan_step_ref="p1",
            existing_step_ref="existing_step_1",
            name="One",
            instructions="Read.",
        ),
        _step_spec(
            plan_step_ref="p2",
            existing_step_ref="existing_step_2",
            name="Two",
            instructions="Analyze.",
        ),
        _step_spec(
            plan_step_ref="p3",
            existing_step_ref="existing_step_3",
            name="Three",
            instructions="Summarize {{ p2.output.text }} briefly.",
        ),
    ]
    if producer_first:
        steps.insert(
            1,
            _step_spec(plan_step_ref="new", name="Prep", instructions="Prepare."),
        )
    return saved, FlowDraftSpecCore(flow_name="Flow", steps=steps)


def _updates(changeset) -> list[tuple[str | None, frozenset[str], dict[int, int]]]:
    return [
        (update.existing_step_ref, update.fields, update.prompt_alias_renumbering)
        for update in changeset.assistants_to_update
    ]


def test_when_a_step_moves_every_kept_prompt_is_renumbered_never_replaced() -> None:
    """No step is listed. Steps 2 and 3 moved down one, so each kept step's
    prompt is renumbered at apply from what its assistant holds then; the
    plan's copy of the prompt is written for none of them."""

    saved, spec = _consumer_flow_and_spec(producer_first=True)

    changeset = compile_flow_draft_changeset(
        spec,
        current_flow=saved,
        updated_existing_step_refs=frozenset(),
        updated_assistant_fields={},
    )

    moved = {2: 3, 3: 4}
    assert _updates(changeset) == [
        ("existing_step_1", frozenset(), moved),
        ("existing_step_2", frozenset(), moved),
        ("existing_step_3", frozenset(), moved),
    ]
    assert changeset.compiled_steps[3].change_kind is FlowDraftStepChangeKind.UNCHANGED


def test_when_no_step_moves_a_step_that_names_no_assistant_field_is_not_written() -> (
    None
):
    saved, spec = _consumer_flow_and_spec(producer_first=False)

    changeset = compile_flow_draft_changeset(
        spec,
        current_flow=saved,
        updated_existing_step_refs=frozenset({"existing_step_3"}),
        updated_assistant_fields={},
    )

    assert changeset.assistants_to_update == []


def test_a_step_whose_instructions_the_edit_writes_takes_the_plans_text() -> None:
    """The approval names the instructions: the plan's text, at the steps'
    new positions, is what the edit writes, so nothing is renumbered."""

    saved, spec = _consumer_flow_and_spec(producer_first=True)

    changeset = compile_flow_draft_changeset(
        spec,
        current_flow=saved,
        updated_existing_step_refs=frozenset({"existing_step_3"}),
        updated_assistant_fields={
            "existing_step_3": frozenset({"instructions", "knowledge_refs"})
        },
    )

    update = changeset.assistants_to_update[-1]
    assert (update.existing_step_ref, update.fields) == (
        "existing_step_3",
        frozenset({"instructions", "knowledge_refs"}),
    )
    assert update.prompt_alias_renumbering == {}
    assert update.assistant_spec.instructions == (
        "Summarize {{ step_3.output.text }} briefly."
    )


def test_a_named_field_and_a_move_are_one_update_that_renumbers_the_prompt() -> None:
    saved, spec = _consumer_flow_and_spec(producer_first=True)

    changeset = compile_flow_draft_changeset(
        spec,
        current_flow=saved,
        updated_existing_step_refs=frozenset({"existing_step_3"}),
        updated_assistant_fields={"existing_step_3": frozenset({"knowledge_refs"})},
    )

    assert _updates(changeset)[-1] == (
        "existing_step_3",
        frozenset({"knowledge_refs"}),
        {2: 3, 3: 4},
    )


def _shared_assistant_flow_and_spec(
    *, step_first: bool
) -> tuple[Flow, FlowDraftSpecCore]:
    """Saved: steps 1 and 2 use one assistant, step 3 its own; the edit can
    add a step first."""

    shared = uuid4()
    saved = _flow(
        _flow_step(step_order=1, assistant_id=shared),
        _flow_step(step_order=2, assistant_id=shared),
        _flow_step(step_order=3),
    )
    steps = [
        _step_spec(
            plan_step_ref=f"p{order}",
            existing_step_ref=f"existing_step_{order}",
            name=f"Existing {order}",
            instructions="Read.",
            input_source=InputSource.FLOW_INPUT
            if order == 1
            else InputSource.PREVIOUS_STEP,
        )
        for order in (1, 2, 3)
    ]
    if step_first:
        steps[0] = steps[0].model_copy(
            update={"input_source": InputSource.PREVIOUS_STEP}
        )
        steps.insert(0, _step_spec(plan_step_ref="new", name="Ny", instructions="Ny."))
    return saved, FlowDraftSpecCore(flow_name="Flow", steps=steps)


def test_an_assistant_change_asked_for_one_of_the_steps_sharing_it_is_refused() -> None:
    saved, spec = _shared_assistant_flow_and_spec(step_first=False)

    with pytest.raises(BadRequestException, match="Ask the Builder again"):
        compile_flow_draft_changeset(
            spec,
            current_flow=saved,
            updated_existing_step_refs=frozenset({"existing_step_2"}),
            updated_assistant_fields={"existing_step_2": frozenset({"instructions"})},
        )


def test_the_same_change_asked_for_every_step_sharing_an_assistant_is_one_update() -> (
    None
):
    saved, spec = _shared_assistant_flow_and_spec(step_first=False)

    changeset = compile_flow_draft_changeset(
        spec,
        current_flow=saved,
        updated_existing_step_refs=frozenset({"existing_step_1", "existing_step_2"}),
        updated_assistant_fields={
            "existing_step_1": frozenset({"instructions"}),
            "existing_step_2": frozenset({"instructions"}),
        },
    )

    assert [u.existing_step_ref for u in changeset.assistants_to_update] == [
        "existing_step_1"
    ]


def test_a_move_renumbers_a_shared_assistants_prompt_once() -> None:
    saved, spec = _shared_assistant_flow_and_spec(step_first=True)

    changeset = compile_flow_draft_changeset(
        spec,
        current_flow=saved,
        updated_existing_step_refs=frozenset({"existing_step_1"}),
        updated_assistant_fields={},
    )

    shared = saved.steps[0].assistant_id
    assert [u.existing_assistant_id for u in changeset.assistants_to_update].count(
        shared
    ) == 1


def test_a_rename_of_a_step_sharing_an_assistant_updates_no_assistant() -> None:
    saved, spec = _shared_assistant_flow_and_spec(step_first=False)

    changeset = compile_flow_draft_changeset(
        spec,
        current_flow=saved,
        updated_existing_step_refs=frozenset({"existing_step_2"}),
        updated_assistant_fields={},
    )

    assert changeset.assistants_to_update == []


# A step the edit keeps reads the steps it read, or the edit is refused.
#
# Saved: 1 is the producer, 2 a step nothing reads, 3 the reader. The matrix
# crosses what an edit does to the order with where the reader holds its read
# and how it writes it. Its oracle is written here and reads no product code:
# the alias is judged by the saved step it stands at after the edit.

_TOPOLOGIES: dict[str, tuple[list[int | str], set[int]]] = {
    "insert before the producer": (["new", 1, 2, 3], set()),
    "insert between": ([1, "new", 2, 3], set()),
    "move the producer later, still before the reader": ([2, 1, 3], set()),
    "move the producer after the reader": ([2, 3, 1], set()),
    "remove the producer": ([2, 3], {1}),
    "remove an unrelated step": ([1, 3], {2}),
}
_FORMS = {
    "tight": "x{{STEP.output.text}}y",
    "spaced": "x{{ STEP.output.text }}y",
    "bare": "x{{ STEP }}y",
}


def _http_config(**fields: object) -> dict[str, object]:
    return {"url": "https://example.test/", "auth": {"mode": "none"}, **fields}


class _Site(NamedTuple):
    fields: Callable[[str], dict[str, Any]]
    column: str
    read_at: Callable[[dict[str, Any]], str]
    producer: int = 1
    sees_own_result: bool = False


_SITES: dict[str, _Site] = {
    "http_get url": _Site(
        lambda text: {
            "input_source": "http_get",
            "input_config": _http_config(url=f"https://example.test/{text}"),
        },
        "input_config",
        lambda column: column["url"],
    ),
    "http_get header": _Site(
        lambda text: {
            "input_source": "http_get",
            "input_config": _http_config(
                custom_headers=[{"name": "X-A", "value": text, "secret": False}]
            ),
        },
        "input_config",
        lambda column: column["custom_headers"][0]["value"],
    ),
    "http_get body template": _Site(
        lambda text: {
            "input_source": "http_get",
            "input_config": _http_config(
                body={"mode": "text_template", "template": text}
            ),
        },
        "input_config",
        lambda column: column["body"]["template"],
    ),
    "http_post url": _Site(
        lambda text: {
            "output_mode": "http_post",
            "output_config": _http_config(url=f"https://example.test/{text}"),
        },
        "output_config",
        lambda column: column["url"],
    ),
    "http_post own result": _Site(
        lambda text: {
            "output_mode": "http_post",
            "output_config": _http_config(url=f"https://example.test/{text}"),
        },
        "output_config",
        lambda column: column["url"],
        producer=3,
        sees_own_result=True,
    ),
    "template_fill binding": _Site(
        lambda text: {
            "output_mode": "template_fill",
            "output_config": {"bindings": {"a": text}, "note": "{{ step_1 }}"},
        },
        "output_config",
        lambda column: column["bindings"]["a"],
    ),
    "question": _Site(
        lambda text: {"input_bindings": {"question": text}},
        "input_bindings",
        lambda column: column["question"],
    ),
    "source_ref": _Site(
        lambda text: {"input_bindings": {"source_refs": [{"step_ref": text}]}},
        "input_bindings",
        lambda column: column["source_refs"][0]["step_ref"],
    ),
}


def _text(form: str, order: int) -> str:
    return _FORMS[form].replace("STEP", f"step_{order}")


def _saved_with_reader(site: _Site, text: str) -> Flow:
    reader = _flow_step(step_order=3).model_copy(update=site.fields(text))
    return _flow(_flow_step(step_order=1), _flow_step(step_order=2), reader)


def _keep_all(order: list[int | str]) -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Flow",
        steps=[
            _step_spec(plan_step_ref="new", name="Ny")
            if kept == "new"
            else _step_spec(
                plan_step_ref=f"p{kept}",
                existing_step_ref=f"existing_step_{kept}",
                name=f"Existing {kept}",
            )
            for kept in order
        ],
    )


def _compile_topology(flow: Flow, order: list[int | str], removed: set[int]):
    return compile_flow_draft_changeset(
        _keep_all(order),
        current_flow=flow,
        removed_existing_step_refs=frozenset(f"existing_step_{n}" for n in removed),
        updated_existing_step_refs=frozenset(),
    )


@pytest.mark.parametrize("topology", list(_TOPOLOGIES))
@pytest.mark.parametrize("form", list(_FORMS))
@pytest.mark.parametrize("site_name", list(_SITES))
def test_a_kept_read_follows_its_producer_or_the_edit_is_refused(
    site_name: str, form: str, topology: str
) -> None:
    site = _SITES[site_name]
    if site_name == "source_ref" and form != "tight":
        pytest.skip("a source ref holds an alias, not a template")
    order, removed = _TOPOLOGIES[topology]
    text = _text(form, site.producer)
    if site_name == "source_ref":
        text = f"step_{site.producer}"
    reader_position = order.index(3) + 1
    producer_position = (
        order.index(site.producer) + 1 if site.producer not in removed else None
    )
    readable = producer_position is not None and (
        producer_position < reader_position
        or (site.sees_own_result and producer_position == reader_position)
    )
    flow = _saved_with_reader(site, text)

    if not readable:
        with pytest.raises(BadRequestException) as exc_info:
            _compile_topology(flow, order, removed)
        assert exc_info.value.code == "invalid_existing_step_ref"
        context = exc_info.value.context or {}
        assert context["reason"] == "kept_read_lost_its_producer"
        assert context["reader_ref"] == "existing_step_3"
        assert context["producer_ref"] == f"existing_step_{site.producer}"
        assert str(context["site"]).startswith(site.column)
        return

    changeset = _compile_topology(flow, order, removed)

    reader = changeset.compiled_steps[reader_position - 1]
    assert reader.saved_step is not None and reader.saved_step.step_order == 3
    producer = changeset.compiled_steps[producer_position - 1]
    assert producer.saved_step is not None
    assert producer.saved_step.step_order == site.producer
    followed = text.replace(f"step_{site.producer}", f"step_{producer_position}")
    expected = flow.steps[2].model_copy(update=site.fields(followed))
    assert getattr(reader, site.column) == getattr(expected, site.column)
    assert followed in site.read_at(getattr(reader, site.column))


# The runtime reads a source ref's step number in any script and with leading
# zeros, so each of these is saved step 1; its oracle is the runtime's own
# input resolution over what each step completed with.
_SOURCE_REF_FORMS = [
    "step_1",
    "step_01",
    "step_\u0661",
    "step_\u0660\u0661",
    "step_\uff11",
]


@pytest.mark.parametrize("topology", list(_TOPOLOGIES))
@pytest.mark.parametrize("form", _SOURCE_REF_FORMS)
def test_a_source_ref_in_any_form_the_runtime_reads_follows_its_producer_or_the_edit_is_refused(
    form: str, topology: str
) -> None:
    order, removed = _TOPOLOGIES[topology]
    flow = _flow(
        _flow_step(step_order=1),
        _flow_step(step_order=2),
        _reader(
            3,
            output_mode="compose_text",
            input_bindings={"source_refs": [{"step_ref": form, "output": "text"}]},
        ),
    )
    reader_position = order.index(3) + 1

    if 1 in removed or order.index(1) + 1 > reader_position:
        with pytest.raises(BadRequestException) as exc_info:
            _compile_topology(flow, order, removed)
        assert (exc_info.value.context or {})["reason"] == (
            "kept_read_lost_its_producer"
        )
        return

    changeset = _compile_topology(flow, order, removed)

    text_by_order = {
        position: f"saved {step.saved_step.step_order}"
        if step.saved_step is not None
        else "new"
        for position, step in enumerate(changeset.compiled_steps, 1)
    }
    reader = changeset.compiled_steps[reader_position - 1]
    assert runtime_source_ref_text(
        reader.input_bindings, reader_order=reader_position, text_by_order=text_by_order
    ) == ("saved 1")


def _reader(order: int, **fields: Any) -> FlowStep:
    return _flow_step(step_order=order).model_copy(update=fields)


def _http_get(url: str, **fields: object) -> dict[str, Any]:
    return {
        "input_source": "http_get",
        "input_config": _http_config(url=url, **fields),
    }


def test_two_readers_that_trade_places_each_keep_reading_the_producer() -> None:
    flow = _flow(
        _flow_step(step_order=1),
        _reader(2, **_http_get("https://a.test/{{ step_1 }}")),
        _reader(3, **_http_get("https://b.test/{{step_1.output.text}}")),
    )

    changeset = _compile_topology(flow, [1, 3, 2], set())

    assert [step.input_config["url"] for step in changeset.compiled_steps[1:]] == [
        "https://b.test/{{step_1.output.text}}",
        "https://a.test/{{ step_1 }}",
    ]


def test_a_read_that_was_not_valid_where_it_was_saved_is_not_judged() -> None:
    # Step 2 reads step 3 (a forward read) and step 9 (none): both were
    # refused by the validators already, and the flow stays editable.
    flow = _flow(
        _flow_step(step_order=1),
        _reader(2, **_http_get("https://a.test/{{ step_3 }}{{ step_9 }}")),
        _flow_step(step_order=3),
    )

    renamed = _compile_topology(flow, [1, 2, 3], set())
    removed = _compile_topology(flow, [1, 2], {3})

    for changeset in (renamed, removed):
        assert changeset.compiled_steps[1].input_config == (
            _http_config(url="https://a.test/{{ step_3 }}{{ step_9 }}")
        )


@pytest.mark.parametrize("site_name", list(_SITES))
def test_a_read_that_named_no_step_when_saved_is_refused_once_the_edit_makes_it_name_one(
    site_name: str,
) -> None:
    # Saved with three steps, the reader reads step 5: none. Three added steps
    # before it make step 5 a real step the author never chose.
    site = _SITES[site_name]
    text = "step_5" if site_name == "source_ref" else "{{ step_5.output.text }}"
    flow = _saved_with_reader(site, text)

    with pytest.raises(BadRequestException) as exc_info:
        _compile_topology(flow, ["new", "new", "new", 1, 2, 3], set())

    assert exc_info.value.code == "invalid_existing_step_ref"
    context = exc_info.value.context or {}
    assert context["reason"] == "dangling_read_now_bound"
    assert context["reader_ref"] == "existing_step_3"
    assert str(context["site"]).startswith(site.column)

    for order in ([1, 2, 3], ["new", 1, 2, 3]):
        changeset = _compile_topology(flow, order, set())
        assert text in site.read_at(getattr(changeset.compiled_steps[-1], site.column))


def test_a_forward_read_of_a_step_the_edit_removes_is_refused_when_a_new_step_takes_its_place() -> (
    None
):
    flow = _flow(
        _flow_step(step_order=1),
        _reader(2, **_http_get("https://a.test/{{ step_3 }}")),
        _flow_step(step_order=3),
    )

    with pytest.raises(BadRequestException) as exc_info:
        _compile_topology(flow, [1, "new", "new", 2], {3})

    context = exc_info.value.context or {}
    assert context["reason"] == "dangling_read_now_bound"
    assert context["producer_ref"] == "existing_step_3"


def test_a_forward_read_of_a_step_the_edit_moves_before_it_follows_that_step() -> None:
    flow = _flow(
        _flow_step(step_order=1),
        _reader(2, **_http_get("https://a.test/{{ step_3 }}")),
        _flow_step(step_order=3),
    )

    changeset = _compile_topology(flow, [1, 3, 2], set())

    assert changeset.compiled_steps[2].input_config == _http_config(
        url="https://a.test/{{ step_2 }}"
    )


def test_a_template_the_runtime_does_not_fill_is_not_a_read() -> None:
    inactive = _http_config(
        url="https://a.test/", body={"mode": "none", "template": "{{ step_1 }}"}
    )
    flow = _flow(
        _flow_step(step_order=1),
        _flow_step(step_order=2),
        _reader(3, input_source="http_get", input_config=inactive),
    )

    for order, removed in ([2, 3], {1}), (["new", 1, 2, 3], set()):
        changeset = _compile_topology(flow, order, removed)
        assert changeset.compiled_steps[-1].input_config == inactive


def test_metadata_that_only_looks_like_a_read_stays_as_saved() -> None:
    literal = {"citation_mode": "off", "note": "{{ step_1.output.text }}"}
    flow = _flow(
        _flow_step(step_order=1),
        _reader(2, output_mode="compose_text", output_config=literal),
    )

    removed = _compile_topology(flow, [2], {1})
    moved = _compile_topology(flow, ["new", 1, 2], set())

    assert removed.compiled_steps[0].output_config == literal
    assert moved.compiled_steps[2].output_config == literal


def test_only_the_alias_the_runtime_resolves_moves_with_its_producer() -> None:
    url = (
        "https://a.test/{{ step_10.output }}{{ step_01 }}{{ föregående_steg }}"
        "{{ step_1x }}/{{step_1 .output.text}}"
    )
    flow = _flow(
        _flow_step(step_order=1),
        _flow_step(step_order=2),
        _reader(3, **_http_get(url)),
    )

    changeset = _compile_topology(flow, ["new", 1, 2, 3], set())

    assert changeset.compiled_steps[3].input_config == _http_config(
        url=url.replace("{{step_1 .output", "{{step_2 .output")
    )


def test_a_positional_read_stays_positional_when_its_producer_moves() -> None:
    question = "{{ föregående_steg }}"
    flow = _flow(
        _flow_step(step_order=1),
        _reader(2, input_source="previous_step", input_bindings={"question": question}),
    )

    changeset = _compile_topology(flow, ["new", 1, 2], set())

    assert changeset.compiled_steps[2].input_bindings == {"question": question}
    assert changeset.compiled_steps[2].input_source is FlowInputSource.PREVIOUS_STEP


def test_a_named_step_that_keeps_its_saved_read_is_judged_like_an_untouched_one() -> (
    None
):
    saved = _flow(
        _flow_step(step_order=1),
        _reader(
            2,
            input_source="previous_step",
            input_bindings={"question": "Skriv {{step_1.output.text}}"},
        ),
    )
    spec = FlowDraftSpecCore(
        flow_name="Flow",
        steps=[
            _step_spec(
                plan_step_ref="p2",
                existing_step_ref="existing_step_2",
                name="Existing 2",
                input_source=InputSource.PREVIOUS_STEP,
                input_bindings={"question": "Skriv {{ p1.output.text }}"},
            ),
            _step_spec(
                plan_step_ref="p1",
                existing_step_ref="existing_step_1",
                name="Existing 1",
            ),
        ],
    )

    with pytest.raises(BadRequestException) as exc_info:
        compile_flow_draft_changeset(
            spec,
            current_flow=saved,
            updated_existing_step_refs=frozenset({"existing_step_2"}),
        )

    assert invalid_existing_step_ref_reason(exc_info.value) == (
        "kept_read_lost_its_producer"
    )
    assert (exc_info.value.context or {})["site"] == "input_bindings.question"


def test_a_step_the_edit_adds_is_never_judged() -> None:
    flow = _flow(_flow_step(step_order=1))
    spec = FlowDraftSpecCore(
        flow_name="Flow",
        steps=[
            _step_spec(
                plan_step_ref="new",
                name="Ny",
                input_bindings={"question": "{{ step_7.output.text }}"},
            ),
            _step_spec(
                plan_step_ref="p1",
                existing_step_ref="existing_step_1",
                name="Existing 1",
            ),
        ],
    )

    changeset = compile_flow_draft_changeset(
        spec, current_flow=flow, updated_existing_step_refs=frozenset()
    )

    assert changeset.compiled_steps[0].carried_columns == frozenset()


@pytest.mark.parametrize(
    "saved_type", ["password", None, 7], ids=["password", "null", "number"]
)
def test_every_reader_of_a_saved_unsupported_field_type_raises_the_persisted_read_error(
    saved_type: object,
) -> None:
    saved = [
        {"name": "ok", "type": "text", "label": "Ok", "order": 2},
        {"name": "bad", "type": saved_type, "label": "Bad", "order": 1},
    ]

    with pytest.raises(BadRequestException) as from_builder:
        extract_form_fields_from_metadata({"form_schema": {"fields": saved}})
    with pytest.raises(BadRequestException) as from_compile:
        _form_fields_after(_authored(("ok", "text", "Ok")), saved)

    # The index names the saved array position, as the persisted read does.
    assert "fields[1].type" in str(from_builder.value)
    assert "fields[1].type" in str(from_compile.value)


def test_a_saved_unsupported_field_type_is_reported_at_its_raw_array_index() -> None:
    # Non-object entries are skipped but still occupy their saved array position.
    saved = [
        None,
        {"name": "ok", "type": "text", "label": "Ok"},
        {"name": "bad", "type": "password", "label": "Bad"},
    ]

    with pytest.raises(BadRequestException) as from_builder:
        extract_form_fields_from_metadata({"form_schema": {"fields": saved}})
    with pytest.raises(BadRequestException) as from_compile:
        _form_fields_after(_authored(("ok", "text", "Ok")), saved)

    assert "fields[2].type" in str(from_builder.value)
    assert "fields[2].type" in str(from_compile.value)
