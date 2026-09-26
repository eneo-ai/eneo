from __future__ import annotations

from typing import get_type_hints
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
from eneo.main.exceptions import BadRequestException


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
