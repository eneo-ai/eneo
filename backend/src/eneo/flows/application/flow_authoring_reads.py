"""What each step of a draft reads and who reads it, for the flow chat.

The chat's read of a flow lists, per step, the earlier results the step
reads and the later steps that read its result, in the reference forms the
chat and the editor use, so a change to one step can reach the steps that
depend on it. The reads are those of ``step_lineage`` through the suggestion
analyzer's view of the draft (``DraftReads``): the same facts the
suggestions and the publish rules are judged on, computed once per read.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
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


def output_fields(output_contract: Mapping[str, object] | None) -> list[str] | None:
    """The names of the fields a JSON step's contract declares at its top
    level; None without a contract."""
    if not output_contract:
        return None
    properties = output_contract.get("properties")
    if not isinstance(properties, Mapping):
        return []
    return [str(name) for name in properties]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
