"""What each step of a draft reads and who reads it, for the flow chat.

The chat's read of a flow lists, per step, the earlier results the step
reads and the later steps that read its result, in the reference forms the
chat and the editor use, so a change to one step can reach the steps that
depend on it. The reads are those of ``step_lineage`` through the suggestion
analyzer's view of the draft (``DraftReads``): the same facts the
suggestions and the publish rules are judged on, computed once per read.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from typing import Any, cast
from uuid import UUID

from eneo.flows.application.flow_suggestion_service import suggestion_flow
from eneo.flows.domain.flow import Flow
from eneo.flows.domain.flow_suggestion_model import (
    DraftReads,
    SuggestionStep,
    describe_site,
)
from eneo.flows.flow_metadata import FlowFormSchemaParseMode, parse_flow_form_schema
from eneo.flows.infrastructure.flow_repo import StoredAssistantPrompt
from eneo.flows.step_lineage import StepRead
from eneo.main.exceptions import BadRequestException


def read_reference(read: StepRead) -> str:
    """The reference the flow resolves for ``read``: the text of the step's
    result, its whole structured value or a path into it."""
    tail = ".".join(read.selector) or "text"
    return f"{{{{step_{read.step_order}.output.{tail}}}}}"


def _read_item(read: StepRead, *, step: SuggestionStep | None, reader: SuggestionStep):
    return {
        "step_order": read.step_order,
        "name": step.user_description if step is not None else None,
        "value": read_reference(read),
        "where": describe_site(read.site, reader),
    }


def step_reads_summary(
    flow: Flow, prompts: Mapping[UUID, StoredAssistantPrompt]
) -> dict[int, dict[str, Any]]:
    """By step order: ``reads`` (the earlier results the step reads, with the
    reference and where it is written), ``readers`` (the later steps that
    read this step's result, the same way), ``form_fields`` (the run form
    fields the step reads) and, for a step whose configuration cannot be
    read, ``unreadable``."""
    draft = DraftReads.of(suggestion_flow(flow, prompts=prompts))
    by_order = {step.step_order: step for step in draft.steps}
    summary: dict[int, dict[str, Any]] = {}
    for step in draft.steps:
        reads = [
            _read_item(read, step=by_order.get(read.step_order), reader=step)
            for read in draft.reads[step.step_order]
        ]
        readers = [
            {
                "step_order": reader.step_order,
                "name": reader.user_description,
                "value": read_reference(read),
                "where": describe_site(read.site, reader),
            }
            for reader, read in draft.readers_of(step.step_order)
        ]
        form_fields = [
            {"field": read.field, "where": describe_site(read.site, step)}
            for read in draft.form_field_reads[step.step_order]
        ]
        item: dict[str, Any] = {
            "reads": reads,
            "readers": readers,
            "form_fields": form_fields,
        }
        if step.step_order in draft.unreadable:
            item["unreadable"] = True
        summary[step.step_order] = item
    return summary


def run_form_fields(metadata_json: Mapping[str, object] | None) -> list[dict[str, Any]]:
    """The run form's fields as saved, in short: name, type, label, required
    and the options of a choice. Empty when the form cannot be read."""
    try:
        schema = parse_flow_form_schema(
            metadata_json, mode=FlowFormSchemaParseMode.PERSISTED_READ
        )
    except BadRequestException:
        return []
    if schema is None:
        return []
    fields: list[dict[str, Any]] = []
    for field in schema.fields:
        item: dict[str, Any] = {
            "name": field.name,
            "type": field.type.value,
            "required": field.required,
        }
        if field.label:
            item["label"] = field.label
        if field.options:
            item["options"] = field.options
        fields.append(item)
    return fields


def _value(item: object) -> object:
    return item.value if isinstance(item, Enum) else item


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return round((end - start).total_seconds(), 1)


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


RESULT_PREVIEW_CHARS = 400


def _result_summary(result: Any) -> dict[str, Any] | None:
    """A run's final result in short: its kind and the start of its text."""
    if result is None:
        return None
    text = getattr(result, "text", None) or getattr(result, "preview", None)
    item: dict[str, Any] = {"kind": _value(getattr(result, "kind", None))}
    if isinstance(text, str):
        item["preview"] = text[:RESULT_PREVIEW_CHARS]
        item["preview_truncated"] = len(text) > RESULT_PREVIEW_CHARS
    return item


def run_summary(
    detail: Any,
    steps: Sequence[Any],
    labels: Mapping[int, str],
    checkpoints: Sequence[Any],
) -> dict[str, Any]:
    """The compact view of one run the chat reasons from: the run's status,
    timing, tokens, error and result in short, and each step in one line
    (status, duration, tokens, whether its prompt was cut, its long-material
    coverage, its diagnostics, its error, its review's latest outcome), so the
    chat can say which step costs or failed and why. ``detail`` is the run's
    audited detail, ``steps`` its step results, ``labels`` the step names of
    the run's version by order and ``checkpoints`` its review checkpoints."""
    reviews: dict[int, Any] = {}
    for checkpoint in checkpoints:
        # Ordered by step and attempt: the last one is the step's latest.
        reviews[checkpoint.step_order] = checkpoint
    tokens = getattr(detail, "token_usage", None)
    error = getattr(detail, "error", None)
    items: list[dict[str, Any]] = []
    for step in sorted(steps, key=lambda item: item.step_order):
        order = step.step_order
        diagnostics = [
            {"code": item.code, "severity": _value(item.severity)}
            for item in cast(list[Any], getattr(step, "diagnostics", None) or [])
        ]
        coverage = getattr(step, "long_material", None)
        review = reviews.get(order)
        item: dict[str, Any] = {
            "step_order": order,
            "name": labels.get(order) or f"Steg {order}",
            "status": _value(step.status),
            "attempts": getattr(step, "current_attempt_no", None),
            "duration_seconds": _seconds(step.started_at, step.finished_at),
            "tokens": {
                "input": step.num_tokens_input,
                "output": step.num_tokens_output,
            },
            "prompt_truncated": bool(
                getattr(step, "effective_prompt_truncated", False)
            ),
            "coverage": _value(coverage.coverage) if coverage is not None else None,
            "diagnostics": diagnostics,
            "error": (
                {"code": _value(step.error_code), "message": step.error_message}
                if step.error_code or step.error_message
                else None
            ),
            "review": (
                {"state": _value(review.state), "attempt": review.attempt_no}
                if review is not None
                else None
            ),
        }
        items.append(item)
    return {
        "run_id": str(detail.id),
        "status": _value(detail.status),
        "flow_version": detail.flow_version,
        "purpose": _value(getattr(detail, "purpose", None)),
        "started_at": _iso(detail.started_at),
        "finished_at": _iso(detail.finished_at),
        "duration_seconds": _seconds(detail.started_at, detail.finished_at),
        "tokens": (
            {
                "input": tokens.num_tokens_input,
                "output": tokens.num_tokens_output,
                "total": tokens.num_tokens_total,
                "complete": tokens.input_completeness == "complete"
                and tokens.output_completeness == "complete",
            }
            if tokens is not None
            else None
        ),
        "error": (
            {
                "code": _value(error.code),
                "message": error.message,
                "step_order": getattr(error, "step_order", None),
                "retryable": getattr(error, "retryable", None),
                "user_action": getattr(error, "user_action", None),
            }
            if error is not None
            else None
        ),
        "result": _result_summary(getattr(detail, "result", None)),
        "steps": items,
    }


def output_fields(output_contract: Mapping[str, object] | None) -> list[str] | None:
    """The names of the fields a JSON step's contract declares at its top
    level; None without a contract."""
    if not output_contract:
        return None
    properties = output_contract.get("properties")
    if not isinstance(properties, Mapping):
        return []
    return [str(name) for name in properties]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
