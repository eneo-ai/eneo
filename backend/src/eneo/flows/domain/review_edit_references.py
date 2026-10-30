"""Name a reviewer's edits to the model steps that read the edited result.

A later model step reads the whole edited payload and can re-derive an edited
value from an unedited sibling. A completion call that reads a resumed, edited
JSON result is instructed which of the values it selected the person set or
removed, and to keep them. References only: source step, binding, selection
and the path inside the selected object - never a value, an old value, or a
removed key the output contract does not declare (keys can be data). Only the
consumed selection is compared, lazily, and comparison stops at the limit.

Unmeasured: a speaker-mapping result read as text (a rebuilt transcript); a
model step that reads a later, transformed result; section, fold and
speaker-naming calls, which read a part or a transcript of the input.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from eneo.flows.domain.flow import FlowStepResult, FlowStepResultStatus
from eneo.flows.domain.text_processing import text_processing_config
from eneo.flows.enums import FlowOutputMode
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputEdge,
    FlowResolvedInputStepResultSource,
)
from eneo.main.exceptions import TypedIOValidationException

if TYPE_CHECKING:
    from eneo.flows.domain.runtime import RuntimeStep

REVIEWED_EDIT_MAX_REFERENCES = 64
REVIEWED_EDIT_MAX_BLOCK_BYTES = 8 * 1024
REVIEWED_EDIT_READ_MAX_ROWS = 64
REVIEWED_EDIT_READ_MAX_LOGICAL_BYTES = 16 * 1024 * 1024

ReviewedPath = tuple[str | int, ...]
# `entry_removed`: a key the contract does not declare was removed; only the
# container is named.
ReviewedChangeKind = Literal["set", "removed", "entry_removed"]
ReviewedResultKey = tuple[UUID, int]
# (step_id, attempt_no, original_payload_json, current_payload_json)
ResumedReviewPayload = tuple[UUID, int, object, object]

# Where the structured value sits in the object a step-result selector reads
# (the resolver's step envelope: {input, output: {text, structured}, ...}).
_STRUCTURED_AT = ("output", "structured")
_TEXT_AT = ("output", "text")
_ACTIONS: dict[ReviewedChangeKind, str] = {
    "set": "set by the reviewer",
    "removed": "removed by the reviewer",
    "entry_removed": "had an entry removed by the reviewer",
}
_BLOCK_HEADER = (
    "Reviewed values: a person reviewed and corrected an earlier step's result. "
    "The values referenced below are authoritative: use them as they appear in "
    "your input, and do not restore, recalculate or replace them from other parts "
    "of the input. Each path is inside the selected value; [] is the whole "
    "selected value."
)
_MISSING = object()


@dataclass(frozen=True, slots=True)
class ReviewedChange:
    path: ReviewedPath
    kind: ReviewedChangeKind


@dataclass(frozen=True, slots=True)
class ReviewedResult:
    """A resumed, edited JSON result; compared only where a step selects it."""

    step_order: int
    step_name: str | None
    original: dict[str, object] | list[object]
    current: dict[str, object] | list[object]
    contract: object
    text_is_structured_json: bool


def reviewed_result_attempts(
    persisted_results: Sequence[FlowStepResult],
) -> frozenset[ReviewedResultKey]:
    """The (step_id, current attempt) of each completed step result."""

    return frozenset(
        (result.step_id, result.current_attempt_no)
        for result in persisted_results
        if result.status == FlowStepResultStatus.COMPLETED
        and result.current_attempt_no is not None
    )


def reviewed_results(
    payloads: Iterable[ResumedReviewPayload],
    *,
    steps: Sequence[RuntimeStep],
) -> dict[ReviewedResultKey, ReviewedResult]:
    """The readable reviewed results; nothing is compared here."""

    steps_by_id = {step.step_id: step for step in steps}
    results: dict[ReviewedResultKey, ReviewedResult] = {}
    for step_id, attempt_no, original_payload, current_payload in payloads:
        step = steps_by_id[step_id]
        original = _structured(original_payload)
        current = _structured(current_payload)
        if original is None or current is None:
            continue
        results[(step_id, attempt_no)] = ReviewedResult(
            step_order=step.step_order,
            step_name=(step.user_description or "").strip() or None,
            original=original,
            current=current,
            contract=step.output_contract,
            text_is_structured_json=step.output_mode
            != FlowOutputMode.SPEAKER_MAPPING.value,
        )
    return results


def reviewed_changes(
    original: object,
    current: object,
    *,
    contract: object = None,
    contract_root: ReviewedPath = (),
) -> Iterator[ReviewedChange]:
    """The paths a person changed, lazily and without recursion (memory grows
    with depth only): a changed leaf, an added or removed array item, a
    container whose type changed, a removed key (named only when `contract`
    declares it at `contract_root` + path)."""

    stack = [_compare((), original, current, contract, contract_root)]
    while stack:
        step = next(stack[-1], None)
        if step is None:
            stack.pop()
        elif isinstance(step, ReviewedChange):
            yield step
        else:
            stack.append(_compare(*step, contract, contract_root))


def reviewed_edit_prompt_block(
    *,
    step: RuntimeStep,
    edges: Iterable[FlowResolvedInputEdge],
    reviewed: Mapping[ReviewedResultKey, ReviewedResult],
) -> str | None:
    """The instruction for a step's consumed reviewed selections, if any.

    Raises TYPED_IO_INPUT_TOO_LARGE, before any provider call, as soon as the
    references do not fit; authority is never broadened to unchanged values.
    """

    if (
        not reviewed
        or step.output_mode == FlowOutputMode.SPEAKER_MAPPING.value
        or text_processing_config(step.input_config) is not None
    ):
        return None
    lines: dict[str, None] = {}
    block_bytes = len(_BLOCK_HEADER.encode("utf-8"))
    for edge in edges:
        source = edge.source
        if not isinstance(source, FlowResolvedInputStepResultSource):
            continue
        result = reviewed.get((source.source_step_id, source.source_attempt_no))
        if result is None:
            continue
        selector = tuple(source.selector.path)
        for relative, kind in _selected_changes(result, selector):
            line = (
                f"- in {_step_label(result)}, binding "
                f"{json.dumps(edge.binding_ref, ensure_ascii=False)}, selection "
                f"{json.dumps(list(selector), ensure_ascii=False)}: "
                f"{json.dumps(list(relative), ensure_ascii=False)} {_ACTIONS[kind]}"
            )
            if line in lines:
                continue
            lines[line] = None
            block_bytes += len(line.encode("utf-8")) + 1
            if (
                len(lines) > REVIEWED_EDIT_MAX_REFERENCES
                or block_bytes > REVIEWED_EDIT_MAX_BLOCK_BYTES
            ):
                raise TypedIOValidationException(
                    "Reviewed edits read by this step exceed the reference limit.",
                    code=FlowApiErrorCode.TYPED_IO_INPUT_TOO_LARGE.value,
                    context={
                        "max_references": REVIEWED_EDIT_MAX_REFERENCES,
                        "max_reference_bytes": REVIEWED_EDIT_MAX_BLOCK_BYTES,
                    },
                )
    if not lines:
        return None
    return "\n".join((_BLOCK_HEADER, *lines))


def _selected_changes(
    result: ReviewedResult, selector: ReviewedPath
) -> Iterator[tuple[ReviewedPath, ReviewedChangeKind]]:
    """The changes inside what `selector` reads, as paths in that object."""

    if selector[: len(_STRUCTURED_AT)] == _STRUCTURED_AT:
        prefix: ReviewedPath = ()
        selection = selector[len(_STRUCTURED_AT) :]
    elif selector == _TEXT_AT and result.text_is_structured_json:
        # The text is the structured value serialised: the same coordinates.
        prefix, selection = (), ()
    elif _STRUCTURED_AT[: len(selector)] == selector:
        # The step envelope or its output: the structured value sits inside it.
        prefix, selection = _STRUCTURED_AT[len(selector) :], ()
    else:
        return
    before, after = result.original, result.current
    for segment in selection:
        after = _child(after, segment)
        if after is _MISSING:
            return
        before = _child(before, segment)
        if before is _MISSING:
            # The container above the selection was replaced or added.
            yield prefix, "set"
            return
    for change in reviewed_changes(
        before, after, contract=result.contract, contract_root=selection
    ):
        yield (*prefix, *change.path), change.kind


def _compare(
    path: ReviewedPath,
    before: object,
    after: object,
    contract: object,
    contract_root: ReviewedPath,
) -> Iterator[ReviewedChange | tuple[ReviewedPath, object, object]]:
    """One node: its own changes, and its children still to compare."""

    if isinstance(before, dict) and isinstance(after, dict):
        old_map = cast(dict[str, object], before)
        new_map = cast(dict[str, object], after)
        for key, value in new_map.items():
            if key in old_map:
                yield (*path, key), old_map[key], value
            else:
                yield ReviewedChange((*path, key), "set")
        undeclared_removed = False
        for key in old_map:
            if key in new_map:
                continue
            if _declares_property(contract, (*contract_root, *path), key):
                yield ReviewedChange((*path, key), "removed")
            else:
                undeclared_removed = True
        if undeclared_removed:
            yield ReviewedChange(path, "entry_removed")
    elif isinstance(before, list) and isinstance(after, list):
        old_items = cast(list[object], before)
        new_items = cast(list[object], after)
        for index, (old, new) in enumerate(zip(old_items, new_items)):
            yield (*path, index), old, new
        for index in range(len(old_items), len(new_items)):
            yield ReviewedChange((*path, index), "set")
        for index in range(len(new_items), len(old_items)):
            yield ReviewedChange((*path, index), "removed")
    # The failed `and` narrowing leaves unknown members on `before`.
    elif _leaf_differs(cast(object, before), after):
        yield ReviewedChange(path, "set")


def _child(value: object, segment: str | int) -> object:
    if isinstance(value, dict) and isinstance(segment, str):
        return cast(dict[str, object], value).get(segment, _MISSING)
    if isinstance(value, list) and isinstance(segment, int):
        items = cast(list[object], value)
        return items[segment] if 0 <= segment < len(items) else _MISSING
    return _MISSING


def _leaf_differs(original: object, current: object) -> bool:
    # A number is compared by value (a browser cannot send 100.0 back as a
    # float); a boolean is never equal to a number.
    if isinstance(original, bool) or isinstance(current, bool):
        return original is not current
    if isinstance(original, int | float) and isinstance(current, int | float):
        return original != current
    return type(original) is not type(current) or original != current


def _declares_property(contract: object, parent: ReviewedPath, key: str) -> bool:
    """Whether the output contract declares `key` at `parent`; only `properties`
    and `items` are followed, anything else declares nothing."""

    node = contract
    for segment in parent:
        if not isinstance(node, dict):
            return False
        schema = cast(dict[str, object], node)
        if isinstance(segment, int):
            node = schema.get("items")
        else:
            properties = schema.get("properties")
            node = (
                cast(dict[str, object], properties).get(segment)
                if isinstance(properties, dict)
                else None
            )
    if not isinstance(node, dict):
        return False
    properties = cast(dict[str, object], node).get("properties")
    return isinstance(properties, dict) and key in properties


def _structured(payload: object) -> dict[str, object] | list[object] | None:
    structured = (
        cast(dict[str, object], payload).get("structured")
        if isinstance(payload, dict)
        else None
    )
    if isinstance(structured, dict):
        return cast(dict[str, object], structured)
    if isinstance(structured, list):
        return cast(list[object], structured)
    return None


def _step_label(result: ReviewedResult) -> str:
    label = f"step {result.step_order}"
    if result.step_name is None:
        return label
    return f"{label} {json.dumps(result.step_name, ensure_ascii=False)}"
