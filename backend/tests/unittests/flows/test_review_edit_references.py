"""A reviewer's edits reach a later model step as authoritative references.

The edited result is already the later step's input; these tests pin what that
step is told: which selected values the person changed, scoped to what it read,
never a value, an old value, or an undeclared removed key.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

import pytest

from eneo.flows.domain.flow import FlowStepResult, FlowStepResultStatus
from eneo.flows.domain.review_edit_references import (
    REVIEWED_EDIT_MAX_REFERENCES,
    ReviewedChange,
    reviewed_changes,
    reviewed_edit_prompt_block,
    reviewed_result_attempts,
    reviewed_results,
)
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputEdge,
    FlowResolvedInputFlowInputSource,
    FlowResolvedInputJsonPath,
    FlowResolvedInputStepResultSource,
    build_resolved_input_edge,
)
from eneo.flows.variable_resolver import FlowVariableResolver
from eneo.main.exceptions import TypedIOValidationException

_OLD_SECRET = "19481216-1596"
_NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
_STRUCTURED = ("output", "structured")


def _step(
    *,
    step_order: int = 1,
    output_mode: str = "pass_through",
    name: str | None = "Analys",
    output_contract: dict[str, Any] | None = None,
    input_config: dict[str, Any] | None = None,
) -> RuntimeStep:
    return RuntimeStep(
        step_id=uuid4(),
        step_order=step_order,
        assistant_id=uuid4(),
        user_description=name,
        input_source="flow_input",
        input_bindings=None,
        input_config=input_config,
        output_mode=output_mode,
        output_config=None,
        output_type="json",
        output_contract=output_contract,
    )


_CONSUMER = _step(step_order=9, name="Consumer")


def _payload(structured: object) -> dict[str, object]:
    return {"structured": structured, "text": "rendered"}


def _reviewed(step: RuntimeStep, original: object, current: object):
    return reviewed_results(
        [(step.step_id, 1, _payload(original), _payload(current))], steps=[step]
    )


def _edge(
    step: RuntimeStep,
    *path: str | int,
    binding_ref: str = "input_source",
    attempt_no: int = 1,
) -> FlowResolvedInputEdge:
    return build_resolved_input_edge(
        binding_ref=binding_ref,
        source=FlowResolvedInputStepResultSource(
            kind="step_result",
            source_step_id=step.step_id,
            source_attempt_no=attempt_no,
            selector=FlowResolvedInputJsonPath(kind="json_path", path=tuple(path)),
        ),
        selected_value="selected",
    )


def _block(reviewed, *edges: FlowResolvedInputEdge, consumer: RuntimeStep = _CONSUMER):
    return reviewed_edit_prompt_block(step=consumer, edges=edges, reviewed=reviewed)


# --- the structural diff -------------------------------------------------


@pytest.mark.parametrize(
    ("original", "current", "expected"),
    [
        ({"a": 1}, {"a": 1}, ()),
        ({"a": 1, "b": 2}, {"a": 1, "b": 3}, (ReviewedChange(("b",), "set"),)),
        ({"a": "x"}, {"a": ""}, (ReviewedChange(("a",), "set"),)),
        ({"a": "x"}, {"a": None}, (ReviewedChange(("a",), "set"),)),
        ({"b": 1}, {"b": 1, "a": "x"}, (ReviewedChange(("a",), "set"),)),
        (
            {"d": [{"x": {"y": 1}}, {"x": {"y": 2}}]},
            {"d": [{"x": {"y": 1}}, {"x": {"y": 9}}]},
            (ReviewedChange(("d", 1, "x", "y"), "set"),),
        ),
        ({"d": [1, 2]}, {"d": [1, 2, 3]}, (ReviewedChange(("d", 2), "set"),)),
        ({"d": [1, 2, 3]}, {"d": [1, 2]}, (ReviewedChange(("d", 2), "removed"),)),
        ({"d": [None]}, {"d": [None]}, ()),
        ({"d": [None]}, {"d": ["v"]}, (ReviewedChange(("d", 0), "set"),)),
        ({"a": {"b": 1}}, {"a": [1]}, (ReviewedChange(("a",), "set"),)),
        ({"a": 1}, {"a": True}, (ReviewedChange(("a",), "set"),)),
        ({"a": True}, {"a": 1}, (ReviewedChange(("a",), "set"),)),
        ({"a": 100.0}, {"a": 100}, ()),
        ({"a": 1}, {"a": "1"}, (ReviewedChange(("a",), "set"),)),
        ([1, {"k": "v"}], [1, {"k": "w"}], (ReviewedChange((1, "k"), "set"),)),
        ({}, [], (ReviewedChange((), "set"),)),
    ],
)
def test_reviewed_changes_are_the_paths_the_person_changed(original, current, expected):
    assert tuple(reviewed_changes(original, current)) == expected


def test_a_one_cell_edit_of_a_float_table_is_one_change_and_one_reference():
    # A browser posts 100.0 back as 100; only the edited cell changed.
    original = {"rows": [{"amount": 100.0 + i, "n": "x"} for i in range(100)]}
    posted = {"rows": [{"amount": 100 + i, "n": "x"} for i in range(100)]}
    posted["rows"][3]["n"] = "y"
    step = _step()

    assert tuple(reviewed_changes(original, posted)) == (
        ReviewedChange(("rows", 3, "n"), "set"),
    )
    block = _block(_reviewed(step, original, posted), _edge(step, *_STRUCTURED))
    assert block is not None
    assert block.count(" set by the reviewer") == 1


def test_a_removed_undeclared_key_names_only_its_container():
    person = "Anna Svensson 19800101-1234"
    original = {"people": {person: {"role": "x"}, "Bo": {"role": "y"}}}
    current = {"people": {"Bo": {"role": "y"}}}
    step = _step(
        output_contract={
            "type": "object",
            "properties": {"people": {"type": "object"}},
        }
    )
    reviewed = _reviewed(step, original, current)

    assert tuple(reviewed_changes(original, current)) == (
        ReviewedChange(("people",), "entry_removed"),
    )
    block = _block(reviewed, _edge(step, *_STRUCTURED))
    assert block is not None
    assert '["people"] had an entry removed by the reviewer' in block
    assert person not in block
    # The sibling entry a consumer still reads is not marked as changed.
    assert _block(reviewed, _edge(step, *_STRUCTURED, "people", "Bo")) is None


def test_a_renamed_key_does_not_reveal_the_old_key():
    old_key = "Anna Svensson"
    step = _step()
    reviewed = _reviewed(
        step,
        {"people": {old_key: {"role": "x"}}},
        {"people": {"[REDACTED]": {"role": "x"}}},
    )

    block = _block(reviewed, _edge(step, *_STRUCTURED))
    assert block is not None
    assert old_key not in block
    assert '["people", "[REDACTED]"] set by the reviewer' in block


def test_a_removed_declared_property_is_named():
    contract = {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"note": {"type": "string"}, "n": {"type": "string"}},
                },
            }
        },
    }
    assert tuple(
        reviewed_changes(
            {"rows": [{"note": _OLD_SECRET, "n": "x"}]},
            {"rows": [{"n": "x"}]},
            contract=contract,
        )
    ) == (ReviewedChange(("rows", 0, "note"), "removed"),)


def test_deep_nesting_is_walked_without_recursion():
    original: object = {"x": 1}
    current: object = {"x": 2}
    for _ in range(5000):
        original = {"k": [original]}
        current = {"k": [current]}

    changes = list(reviewed_changes(original, current))

    assert len(changes) == 1
    assert changes[0].path[-1] == "x"
    assert len(changes[0].path) == 10001


# --- which checkpoints count ----------------------------------------------


def _result(step: RuntimeStep, *, attempt_no: int | None = 1, completed: bool = True):
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=step.step_id,
        step_order=step.step_order,
        assistant_id=step.assistant_id,
        status=(
            FlowStepResultStatus.COMPLETED if completed else FlowStepResultStatus.FAILED
        ),
        current_attempt_no=attempt_no,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_only_current_attempts_of_completed_results_are_read():
    current = _step(step_order=1)
    failed = _step(step_order=2)
    no_attempt = _step(step_order=3)

    attempts = reviewed_result_attempts(
        [
            _result(current, attempt_no=2),
            _result(failed, completed=False),
            _result(no_attempt, attempt_no=None),
        ]
    )

    assert attempts == frozenset({(current.step_id, 2)})


@pytest.mark.parametrize(
    ("original", "current"),
    [
        (None, _payload({"a": 2})),
        (_payload({"a": 1}), None),
        ({"text": "no structured"}, _payload({"a": 2})),
        (_payload("scalar"), _payload("other")),
        ("not a mapping", _payload({"a": 2})),
    ],
)
def test_unreadable_or_unchanged_review_payloads_give_no_reviewed_result(
    original, current
):
    step = _step()
    assert reviewed_results([(step.step_id, 1, original, current)], steps=[step]) == {}


# --- what a consumer is told ----------------------------------------------


def test_a_consumer_of_the_whole_result_is_told_the_set_path_and_never_the_old_value():
    step = _step(step_order=2, name="Analys och bedömning")
    reviewed = _reviewed(
        step,
        {"utfall": "Avslag", "personnummer": _OLD_SECRET},
        {"utfall": "Bifall", "personnummer": ""},
    )

    block = _block(reviewed, _edge(step, *_STRUCTURED))

    assert block is not None
    assert 'step 2 "Analys och bedömning"' in block
    assert 'binding "input_source"' in block
    assert 'selection ["output", "structured"]' in block
    assert '["utfall"] set by the reviewer' in block
    assert '["personnummer"] set by the reviewer' in block
    assert "Avslag" not in block
    assert _OLD_SECRET not in block
    # References only: the reviewed values are in the step's input already.
    assert "Bifall" not in block


def test_an_edited_sibling_the_consumer_did_not_select_is_never_mentioned():
    step = _step()
    reviewed = _reviewed(
        step,
        {"public_summary": "same", "private_note": "old"},
        {"public_summary": "same", "private_note": "new"},
    )

    assert (
        _block(
            reviewed,
            _edge(
                step,
                *_STRUCTURED,
                "public_summary",
                binding_ref="input_bindings.source_refs[0]",
            ),
        )
        is None
    )


def test_each_mapped_item_is_told_only_its_own_item_relative_to_its_selection():
    step = _step()
    reviewed = _reviewed(
        step,
        {"documents": [{"lagrum": "a"}, {"lagrum": "b"}, {"lagrum": "c"}]},
        {"documents": [{"lagrum": "a"}, {"lagrum": "B"}, {"lagrum": "c"}]},
    )

    first = _block(
        reviewed, _edge(step, *_STRUCTURED, "documents", 0, binding_ref="input")
    )
    second = _block(
        reviewed, _edge(step, *_STRUCTURED, "documents", 1, binding_ref="input")
    )

    assert first is None
    assert second is not None
    assert (
        'selection ["output", "structured", "documents", 1]: ["lagrum"] set by the reviewer'
        in second
    )


def test_an_array_length_change_names_only_the_items_that_changed():
    step = _step()
    reviewed = _reviewed(
        step,
        {"rows": [{"a": 1}, {"a": 2}]},
        {"rows": [{"a": 1}, {"a": 2}, {"a": 3}]},
    )

    assert _block(reviewed, _edge(step, *_STRUCTURED, "rows", 0)) is None
    appended = _block(reviewed, _edge(step, *_STRUCTURED, "rows", 2))
    assert appended is not None
    assert ": [] set by the reviewer" in appended


def test_a_container_whose_type_changed_above_the_selection_is_the_whole_selection():
    step = _step()
    reviewed = _reviewed(step, {"d": {"x": 1}}, {"d": [{"x": 1}]})

    block = _block(reviewed, _edge(step, *_STRUCTURED, "d", 0))

    assert block is not None
    assert "[] set by the reviewer" in block


@pytest.mark.parametrize(
    ("selector", "reference"),
    [
        (("output", "text"), '["utfall"]'),
        (("output",), '["structured", "utfall"]'),
        ((), '["output", "structured", "utfall"]'),
    ],
)
def test_a_whole_output_selection_is_referenced_inside_the_object_it_selects(
    selector, reference
):
    step = _step()
    reviewed = _reviewed(step, {"utfall": "Avslag"}, {"utfall": "Bifall"})

    block = _block(reviewed, _edge(step, *selector, binding_ref="assistant_prompt:x"))

    assert block is not None
    assert 'binding "assistant_prompt:x"' in block
    assert f"{reference} set by the reviewer" in block


def test_a_speaker_mapping_result_has_no_text_shortcut():
    step = _step(output_mode="speaker_mapping")
    reviewed = _reviewed(
        step, {"speakers": [{"name": "A"}]}, {"speakers": [{"name": "Anna"}]}
    )

    assert _block(reviewed, _edge(step, "output", "text")) is None
    structured = _block(reviewed, _edge(step, *_STRUCTURED))
    assert structured is not None
    assert '["speakers", 0, "name"] set by the reviewer' in structured


@pytest.mark.parametrize(
    "consumer",
    [
        _step(output_mode="speaker_mapping"),
        _step(input_config={"text_processing": {"mode": "process_each_section"}}),
        _step(input_config={"text_processing": {"mode": "summarize"}}),
    ],
    ids=["speaker_naming_call", "section_call", "summarize_fold_call"],
)
def test_section_fold_and_speaker_naming_calls_are_not_told(consumer):
    step = _step()
    reviewed = _reviewed(step, {"a": 1}, {"a": 2})

    assert _block(reviewed, _edge(step, *_STRUCTURED), consumer=consumer) is None


def test_other_sources_attempts_and_input_selections_get_no_block():
    step = _step()
    reviewed = _reviewed(step, {"a": 1}, {"a": 2})
    flow_input_edge = build_resolved_input_edge(
        binding_ref="input_source",
        source=FlowResolvedInputFlowInputSource(
            kind="flow_input",
            selector=FlowResolvedInputJsonPath(kind="json_path", path=("text",)),
        ),
        selected_value="x",
    )

    for edge in (
        flow_input_edge,
        _edge(_step(), *_STRUCTURED),
        _edge(step, *_STRUCTURED, attempt_no=2),
        _edge(step, "input", "text"),
        _edge(step, "status"),
    ):
        assert _block(reviewed, edge) is None


def test_two_bindings_of_one_change_keep_their_own_binding_identity():
    step = _step()
    reviewed = _reviewed(step, {"a": 1}, {"a": 2})

    block = _block(
        reviewed,
        _edge(step, *_STRUCTURED),
        _edge(step, *_STRUCTURED, "a", binding_ref="assistant_prompt:x"),
    )

    assert block is not None
    assert 'binding "input_source", selection ["output", "structured"]: ["a"]' in block
    assert (
        'binding "assistant_prompt:x", selection ["output", "structured", "a"]: []'
        in block
    )


class _CountingRow(dict[str, Any]):
    """A row that counts how often the comparison opens it."""

    opened = 0

    def items(self):  # type: ignore[override]
        type(self).opened += 1
        return super().items()


def _counting_rows(count: int, *, offset: int) -> list[_CountingRow]:
    return [_CountingRow(a=index + offset) for index in range(count)]


def test_a_mapped_item_call_compares_only_its_own_item():
    step = _step()
    reviewed = _reviewed(
        step,
        {"rows": _counting_rows(2000, offset=0)},
        {"rows": _counting_rows(2000, offset=1)},
    )
    _CountingRow.opened = 0

    block = _block(reviewed, _edge(step, *_STRUCTURED, "rows", 7))

    assert block is not None
    assert block.count("set by the reviewer") == 1
    assert _CountingRow.opened == 1


def test_comparison_stops_at_the_reference_limit():
    step = _step()
    reviewed = _reviewed(
        step,
        {"rows": _counting_rows(100_000, offset=0)},
        {"rows": _counting_rows(100_000, offset=1)},
    )
    _CountingRow.opened = 0

    with pytest.raises(TypedIOValidationException):
        _block(reviewed, _edge(step, *_STRUCTURED))

    assert _CountingRow.opened == REVIEWED_EDIT_MAX_REFERENCES + 1


def _navigate(value: object, path: list[Any] | tuple[Any, ...]) -> object:
    for segment in path:
        value = value[segment]  # type: ignore[index]
    return value


@pytest.mark.parametrize(
    "template",
    [
        "{{ step_1 }}",
        "{{ step_1.output }}",
        "{{ step_1.output.text }}",
        "{{ step_1.output.structured }}",
        "{{ step_1.output.structured.rows }}",
        "{{ step_1.output.structured.rows.1 }}",
        "{{ step_1.output.structured.rows.1.price }}",
    ],
)
def test_each_reference_resolves_in_the_object_the_resolver_selected(template):
    step = _step(step_order=1)
    original = {"rows": [{"price": "1"}, {"price": "2"}], "note": "n"}
    current = {"rows": [{"price": "1"}, {"price": "9"}], "note": "n"}
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step_id=step.step_id,
        step_order=1,
        status=FlowStepResultStatus.COMPLETED,
        current_attempt_no=1,
        output_payload_json={"structured": current, "text": json.dumps(current)},
        created_at=_NOW,
        updated_at=_NOW,
    )
    resolver = FlowVariableResolver()
    context = resolver.build_context_with_evidence({}, [result], current_step_order=2)
    interpolation = resolver.interpolate_with_evidence(
        template, context, binding_ref="assistant_prompt"
    )

    block = _block(_reviewed(step, original, current), *interpolation.edges)

    assert block is not None
    (reference,) = [line for line in block.splitlines() if line.startswith("- ")]
    matched = re.search(r"selection (\[[^\]]*\]): (\[[^\]]*\]) set by", reference)
    assert matched is not None
    selector = json.loads(matched.group(1))
    selected = _navigate(context["step_1"], selector)
    if selector == ["output", "text"]:
        selected = json.loads(cast(str, selected))
    assert _navigate(selected, json.loads(matched.group(2))) == "9"


def test_too_many_references_fail_typed_instead_of_broadening_authority():
    step = _step()
    count = REVIEWED_EDIT_MAX_REFERENCES + 1
    reviewed = _reviewed(
        step,
        {f"k{index}": 0 for index in range(count)},
        {f"k{index}": 1 for index in range(count)},
    )

    with pytest.raises(TypedIOValidationException) as raised:
        _block(reviewed, _edge(step, *_STRUCTURED))

    assert raised.value.code == FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value


def test_too_many_reference_bytes_fail_typed():
    step = _step()
    long_key = "k" * 4096
    reviewed = _reviewed(
        step,
        {f"{long_key}{index}": 0 for index in range(3)},
        {f"{long_key}{index}": 1 for index in range(3)},
    )

    with pytest.raises(TypedIOValidationException) as raised:
        _block(reviewed, _edge(step, *_STRUCTURED))

    assert raised.value.code == FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value


def test_an_approval_without_a_change_gives_no_block():
    step = _step()
    assert (
        _block(_reviewed(step, {"a": 1.0}, {"a": 1}), _edge(step, *_STRUCTURED)) is None
    )


def test_no_reviewed_results_means_no_block():
    assert _block({}, _edge(_step(), *_STRUCTURED)) is None
