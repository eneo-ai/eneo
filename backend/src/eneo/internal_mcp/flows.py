# pyright: basic
# FastMCP's Context surface is largely untyped; this module is a thin adapter
# over it, so strict unknown-type checking adds noise without safety here.
"""Internal MCP server through which the model authors and runs flows.

A flow is a deterministic, ordered list of typed steps that a space runs
unattended (:mod:`eneo.flows.definition`). The model never executes a flow;
it writes the definition through these tools from the flows chat of a space,
publishes it, and starts runs that the worker executes. The bearer token's
``assistant_id`` claim names the hidden flows assistant of exactly one space,
so every tool is scoped to that space without taking it as an argument, and
a flow or run of another space reads as not found.

Each tool answers with a short text for the model (what was saved, the
validation problems verbatim, where a run stands) and with structured
content for the flow panel in the clients: top-level ``flow_id`` and
``run_id`` (nullable) plus the flow or the run state when the call produced
one. Problems the model can repair (validation errors, a missing flow, a
bad attachment link) come back as text that starts with "Could not", never
as a protocol error, so the model fixes the call and tries again. The
transaction of a failed call rolls back; the services record the audit
entries of the successful ones.

See :mod:`eneo.internal_mcp.foundation` for the hosting and authentication
model shared by all internal servers.
"""

from __future__ import annotations

import logging
from typing import Any, Literal
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from eneo.flows.definition import (
    FlowDefinition,
    FormField,
    Step,
    definition_summary,
)
from eneo.flows.flow_models import (
    FlowPublic,
    FlowRunContractPublic,
    FlowRunStatePublic,
    FlowSparsePublic,
)
from eneo.internal_mcp.constants import FLOWS_SERVER_NAME
from eneo.internal_mcp.file_references import (
    FileReferenceRejected,
    referenced_file_metadata,
    verify_reference_url,
)
from eneo.internal_mcp.foundation import (
    ToolContext,
    build_ephemeral_server,
    internal_tool_context,
)
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer

logger = logging.getLogger(__name__)

__all__ = [
    "FLOWS_SERVER_NAME",
    "FLOW_NOT_FOUND_MESSAGE",
    "NOT_AUTHORING_ASSISTANT_MESSAGE",
    "RUN_NOT_FOUND_MESSAGE",
    "build_flows_mcp_server",
    "cancel_run",
    "create_flow",
    "delete_flow",
    "get_flow",
    "get_run",
    "list_flows",
    "mcp",
    "publish_flow",
    "review_run",
    "run_flow",
    "update_flow",
]

# Audit channel the services record for everything these tools do.
CHANNEL = "mcp"

# Missing and out-of-space are indistinguishable: constants, never
# interpolated with what was asked for.
FLOW_NOT_FOUND_MESSAGE = "No flow with that id in this space."
RUN_NOT_FOUND_MESSAGE = "No run with that id in this space."
NOT_AUTHORING_ASSISTANT_MESSAGE = (
    "Flows can only be authored from the flows chat of a space."
)
NO_REVIEW_WAITING_MESSAGE = "This run has no review waiting."
NOTHING_TO_CHANGE_MESSAGE = (
    "Nothing to change: pass a new name, description, form_fields or steps."
)

INSTRUCTIONS = """\
Tools for authoring and running the flows of this space. A flow is a
deterministic, ordered list of typed steps that runs unattended once a person
starts it with the run inputs (form fields). The step kind decides what runs;
nothing is decided at run time, and you never execute a flow yourself: you
write its definition, publish it, start runs and report on them.

Step kinds: llm (one completion with a fixed prompt; output is text or JSON
checked against a schema), compose (text assembled from a template, no model),
review (pauses the run until a person approves or edits an earlier step's
output). document and transcribe steps exist in the schema but cannot be
published yet; say so instead of using them.

Templates read run inputs and earlier steps with {{form.<key>}},
{{steps.<key>}}, {{steps.<key>.json.<path>}} and {{previous}}. A step can
only read form fields and steps that come before it.

A saved flow is a draft until publish_flow; run_flow runs the published
version. run_flow only queues the run and returns at once; get_run is how to
follow its progress. Validation problems come back as text starting with
"Could not": fix the definition and call again.
"""

mcp = FastMCP(
    name="Eneo Flows",
    stateless_http=True,
    instructions=INSTRUCTIONS,
)

ReviewDecision = Literal["approve", "reject"]
InputValue = str | int | float | bool


class _ToolRefused(Exception):
    """Carries the exact model-facing text a tool returns instead of acting."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# Problems the model can repair in the next call. Anything else is a bug or
# an outage and propagates as a protocol error like in every other server.
_REPAIRABLE = (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
    FileReferenceRejected,
    ValidationError,
    _ToolRefused,
)


def _problem_text(exc: BaseException) -> str:
    if isinstance(exc, _ToolRefused):
        return exc.message
    if isinstance(exc, ValidationError):
        return "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            if error.get("loc")
            else str(error["msg"])
            for error in exc.errors()
        )
    if isinstance(exc, NotFoundException) and not str(exc):
        return "not found"
    return str(exc) or exc.__class__.__name__


def _result(
    text: str,
    *,
    flow_id: UUID | None = None,
    run_id: UUID | None = None,
    flow: FlowPublic | None = None,
    run: FlowRunStatePublic | None = None,
    **extra: Any,
) -> CallToolResult:
    """Text for the model plus the structured payload the panel binds on.

    ``flow_id`` and ``run_id`` are always present (null when the call has
    none) so a client binds without reading the rest. The text is the model's
    whole view of the result; the structured payload is not repeated in it.
    """
    if flow is not None:
        flow_id = flow.id
    if run is not None:
        flow_id = flow_id or run.flow_id
        run_id = run.run_id
    structured: dict[str, Any] = {
        "flow_id": str(flow_id) if flow_id else None,
        "run_id": str(run_id) if run_id else None,
        "flow": flow.model_dump(mode="json") if flow is not None else None,
        "run": run.model_dump(mode="json") if run is not None else None,
        **extra,
    }
    return CallToolResult(
        content=[TextContent(type="text", text=text)], structuredContent=structured
    )


def _failure(
    action: str,
    exc: BaseException,
    *,
    flow_id: UUID | None = None,
    run_id: UUID | None = None,
) -> CallToolResult:
    message = _problem_text(exc)
    logger.info("[FLOWS] could not %s: %s", action, message)
    return _result(
        f"Could not {action}: {message}", flow_id=flow_id, run_id=run_id, error=message
    )


# --- Scope ---


async def _authoring_space_id(tool_ctx: ToolContext) -> UUID:
    """The space the token's assistant authors for.

    Only the hidden flows assistant of a space carries ``purpose == "flows"``;
    a token minted for any other assistant is refused even though the server
    could in principle be reached with it.
    """
    assistant, _ = await tool_ctx.container.assistant_service().get_assistant(
        tool_ctx.assistant_id
    )
    if getattr(assistant, "purpose", None) != "flows":
        raise _ToolRefused(NOT_AUTHORING_ASSISTANT_MESSAGE)
    return assistant.space_id


async def _flow_in_space(container: Any, flow_id: UUID, space_id: UUID) -> FlowPublic:
    try:
        flow = await container.flow_service().get_flow(flow_id)
    except NotFoundException:
        raise _ToolRefused(FLOW_NOT_FOUND_MESSAGE) from None
    if flow.space_id != space_id:
        raise _ToolRefused(FLOW_NOT_FOUND_MESSAGE)
    return flow


async def _run_in_space(
    container: Any, run_id: UUID, space_id: UUID
) -> FlowRunStatePublic:
    try:
        state = await container.flow_run_service().get_run_state(run_id)
    except NotFoundException:
        raise _ToolRefused(RUN_NOT_FOUND_MESSAGE) from None
    try:
        await _flow_in_space(container, state.flow_id, space_id)
    except _ToolRefused:
        raise _ToolRefused(RUN_NOT_FOUND_MESSAGE) from None
    return state


async def _referenced_file_id(url: str, tool_ctx: ToolContext) -> UUID:
    """The id of the attached file behind a reference url, tenant-checked.

    Only the file's metadata is read: the worker loads the bytes when the run
    reaches the step that needs them.
    """
    file_id, payload = verify_reference_url(url)
    metadata = await referenced_file_metadata(
        file_id, payload, tool_ctx, log_tag="[FLOWS] run_flow"
    )
    return metadata.id


# --- Text summaries ---


def _form_fields_text(fields: list[FormField]) -> str:
    if not fields:
        return "Run inputs: none."
    parts = [
        f"{field.key} ({field.type.value}{', required' if field.required else ''})"
        for field in fields
    ]
    return "Run inputs: " + ", ".join(parts) + "."


def _flow_text(flow: FlowPublic, lead: str) -> str:
    if flow.published_version is None:
        state = "not published yet"
    elif flow.has_unpublished_changes:
        state = (
            f"published version {flow.published_version}, draft has unpublished changes"
        )
    else:
        state = f"published version {flow.published_version}"
    lines = [
        lead,
        f"Flow '{flow.name}' (flow_id {flow.id}; {state}).",
        _form_fields_text(flow.definition.form_fields),
        "Steps:",
        definition_summary(flow.definition) or "(none)",
    ]
    return "\n".join(lines)


def _flows_list_text(flows: list[FlowSparsePublic]) -> str:
    if not flows:
        return "No flows in this space yet. Create one with create_flow."
    lines = [f"{len(flows)} flow(s) in this space:"]
    for flow in flows:
        published = (
            f"published v{flow.published_version}"
            if flow.published_version is not None
            else "draft"
        )
        kinds = ", ".join(kind.value for kind in flow.step_kinds)
        lines.append(
            f"- '{flow.name}' (flow_id {flow.id}; {published}; "
            f"{flow.step_count} step(s): {kinds or 'none'})"
        )
    return "\n".join(lines)


def _run_contract_text(contract: FlowRunContractPublic) -> str:
    lines = [_form_fields_text(contract.form_fields)]
    if contract.steps_requiring_review:
        names = ", ".join(f"'{step.name}'" for step in contract.steps_requiring_review)
        lines.append(f"Review pauses at: {names}.")
    if contract.final_output is not None:
        lines.append(f"Final output: {contract.final_output.output_type}.")
    return "\n".join(lines)


def _run_text(state: FlowRunStatePublic, lead: str | None = None) -> str:
    lines = [
        lead
        or f"Run {state.run_id} of flow {state.flow_id} "
        f"(version {state.flow_version}): {state.status.value}."
    ]
    if state.run_label:
        lines.append(f"Label: {state.run_label}")
    if state.steps:
        lines.append("Steps:")
    for index, step in enumerate(state.steps, start=1):
        line = f"{index}. [{step.kind.value}] {step.name}: {step.status.value}"
        if step.error_message:
            line += f" ({step.error_message})"
        elif step.preview:
            line += f" - {step.preview}"
        lines.append(line)
    checkpoint = state.review_checkpoint
    if checkpoint is not None and checkpoint.state.value == "awaiting_review":
        lines.append(
            f"A review is waiting ({checkpoint.review_mode}, revision "
            f"{checkpoint.revision}): the person can decide it in the run panel, "
            "or call review_run with their decision."
        )
    if state.output_files:
        names = ", ".join(file.name for file in state.output_files)
        lines.append(f"Output files: {names}")
    if state.error is not None:
        lines.append(f"Error: {state.error.code}: {state.error.message}")
    if state.status.is_active:
        lines.append("Call get_run again to follow its progress.")
    return "\n".join(lines)


# --- Tools ---


@mcp.tool(title="List flows")
async def list_flows(ctx: Context) -> CallToolResult:
    """List the flows of this space, published or draft.

    Use it to find a flow's id before get_flow, update_flow, publish_flow,
    run_flow or delete_flow when the user names a flow rather than its id.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            flows = await tool_ctx.container.flow_service().list_flows(space_id)
    except _REPAIRABLE as exc:
        return _failure("list flows", exc)
    return _result(
        _flows_list_text(flows),
        flows=[flow.model_dump(mode="json") for flow in flows],
    )


@mcp.tool(title="Get flow")
async def get_flow(flow_id: UUID, ctx: Context) -> CallToolResult:
    """Read a flow's current draft definition and publication state.

    Read a flow before changing it: update_flow replaces the given lists
    whole, so send every form field or step you want to keep.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            flow = await _flow_in_space(tool_ctx.container, flow_id, space_id)
    except _REPAIRABLE as exc:
        return _failure("get flow", exc, flow_id=flow_id)
    return _result(_flow_text(flow, "Current definition."), flow=flow)


@mcp.tool(title="Create flow")
async def create_flow(
    name: str,
    description: str,
    steps: list[Step],
    ctx: Context,
    form_fields: list[FormField] | None = None,
) -> CallToolResult:
    """Create a flow in this space from its run inputs and ordered steps.

    A flow is deterministic: every step runs in order, each time, with the
    inputs and the earlier outputs it names. form_fields are the run inputs a
    person fills in when starting a run (text, number, select, file, audio).
    steps are typed by kind:

    - llm: one completion with a fixed prompt. input (default {{previous}})
      is the text the model reads, prompt the instructions. output is
      {"type": "text"} or {"type": "json", "schema": <JSON Schema>}; a JSON
      output lets later steps read fields with {{steps.<key>.json.<path>}}.
      model_id null means the space default. files_from names file or audio
      form fields the model also sees; knowledge names collections and
      websites whose matching passages are injected.
    - compose: text assembled from template, no model call.
    - review: pauses the run until a person approves (mode view) or edits
      and approves (mode edit) the output of step `of` (default the previous
      step). Cannot be the first step, cannot review another review.
    - document and transcribe: in the schema but cannot be published yet.

    Keys are short lower-case identifiers (letters, digits, underscore) that
    stay stable across edits; templates read {{form.<key>}}, {{steps.<key>}},
    {{steps.<key>.json.<path>}} and {{previous}}, and a step only reads what
    comes before it. Do not send step ids; Eneo assigns them.

    The flow is saved as a draft bound to this conversation. Publish it with
    publish_flow before running it. Validation problems come back as text
    starting with "Could not create flow": fix them and call again.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            definition = FlowDefinition(form_fields=form_fields or [], steps=steps)
            flow = await tool_ctx.container.flow_service().create_flow(
                space_id=space_id,
                name=name,
                description=description,
                definition=definition,
                conversation_id=tool_ctx.session_id,
                channel=CHANNEL,
            )
    except _REPAIRABLE as exc:
        return _failure("create flow", exc)
    logger.info("[FLOWS] created flow %s in space %s", flow.id, flow.space_id)
    return _result(
        _flow_text(
            flow, "Flow created as a draft. Publish it with publish_flow to run it."
        ),
        flow=flow,
    )


@mcp.tool(title="Update flow")
async def update_flow(
    flow_id: UUID,
    ctx: Context,
    name: str | None = None,
    description: str | None = None,
    form_fields: list[FormField] | None = None,
    steps: list[Step] | None = None,
) -> CallToolResult:
    """Change a flow's name, description, run inputs or steps.

    Only the arguments given change. A given form_fields or steps list
    replaces the whole list, so include every item to keep; a step keeps
    its identity (and its run history) when its key stays the same. The
    kinds, template references and rules are those of create_flow. Changes
    land in the draft: publish_flow again for runs to use them.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            current = await _flow_in_space(tool_ctx.container, flow_id, space_id)
            if (
                name is None
                and description is None
                and form_fields is None
                and steps is None
            ):
                raise _ToolRefused(NOTHING_TO_CHANGE_MESSAGE)
            definition = None
            if form_fields is not None or steps is not None:
                definition = FlowDefinition(
                    form_fields=(
                        current.definition.form_fields
                        if form_fields is None
                        else form_fields
                    ),
                    steps=current.definition.steps if steps is None else steps,
                )
            flow = await tool_ctx.container.flow_service().update_flow(
                flow_id,
                name=name,
                description=description,
                definition=definition,
                conversation_id=tool_ctx.session_id,
                channel=CHANNEL,
            )
    except _REPAIRABLE as exc:
        return _failure("update flow", exc, flow_id=flow_id)
    logger.info("[FLOWS] updated flow %s", flow.id)
    return _result(
        _flow_text(flow, "Draft updated. Publish it with publish_flow to run it."),
        flow=flow,
    )


@mcp.tool(title="Publish flow")
async def publish_flow(flow_id: UUID, ctx: Context) -> CallToolResult:
    """Publish the flow's draft as its next version.

    Runs always use the published version; a draft, or a draft edited since
    the last publish, cannot run until it is published. The result tells
    what a run needs: the run inputs, where a review pauses it and what the
    final output is.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            await _flow_in_space(tool_ctx.container, flow_id, space_id)
            flow_service = tool_ctx.container.flow_service()
            flow = await flow_service.publish_flow(flow_id, channel=CHANNEL)
            contract = await flow_service.get_run_contract(flow_id)
    except _REPAIRABLE as exc:
        return _failure("publish flow", exc, flow_id=flow_id)
    logger.info("[FLOWS] published flow %s v%s", flow.id, flow.published_version)
    text = (
        f"Published '{flow.name}' as version {flow.published_version}. "
        "It can now be run with run_flow.\n" + _run_contract_text(contract)
    )
    return _result(
        text,
        flow=flow,
        published_version=flow.published_version,
        run_contract=contract.model_dump(mode="json"),
    )


@mcp.tool(title="Delete flow")
async def delete_flow(flow_id: UUID, ctx: Context) -> CallToolResult:
    """Delete a flow of this space.

    Only on the user's explicit request. The flow leaves the space's list;
    its run history stays readable to API consumers that reference it.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            flow = await _flow_in_space(tool_ctx.container, flow_id, space_id)
            await tool_ctx.container.flow_service().delete_flow(
                flow_id, channel=CHANNEL
            )
    except _REPAIRABLE as exc:
        return _failure("delete flow", exc, flow_id=flow_id)
    logger.info("[FLOWS] deleted flow %s", flow_id)
    return _result(f"Deleted flow '{flow.name}'.", flow_id=flow_id, deleted=True)


@mcp.tool(title="Run flow")
async def run_flow(
    flow_id: UUID,
    inputs: dict[str, InputValue],
    ctx: Context,
    files: dict[str, list[str]] | None = None,
    run_label: str | None = None,
) -> CallToolResult:
    """Start a run of the flow's published version with the given inputs.

    inputs maps text, number and select form field keys to their values;
    files maps file and audio form field keys to the attachment reference
    URLs from this conversation (the exact "url" values of the file
    reference entries, never constructed). Every required field needs a
    value or a file.

    The run is queued and this returns at once with its id and initial
    state; it then executes in the background and may take minutes. The
    user watches its progress in the flow panel, so answer in a sentence
    right after this call and stop: never poll get_run in a loop, and call
    it only when the user asks where a run stands. Do not call run_flow
    again to check on it. A flow with a review step pauses at that step
    until a person decides.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            flow = await _flow_in_space(tool_ctx.container, flow_id, space_id)
            file_ids: dict[str, list[UUID]] = {}
            for key, urls in (files or {}).items():
                file_ids[key] = [
                    await _referenced_file_id(url, tool_ctx) for url in urls
                ]
            run_service = tool_ctx.container.flow_run_service()
            run = await run_service.create_run(
                flow_id,
                values=dict(inputs),
                files=file_ids,
                run_label=run_label,
                channel=CHANNEL,
            )
            state = await run_service.get_run_state(run.id)
    except _REPAIRABLE as exc:
        return _failure("run flow", exc, flow_id=flow_id)
    logger.info("[FLOWS] queued run %s of flow %s", state.run_id, flow.id)
    lead = (
        f"Run {state.run_id} of '{flow.name}' (version {state.flow_version}) is "
        f"{state.status.value}. It executes in the background; call get_run "
        "with this run_id to follow it."
    )
    return _result(_run_text(state, lead), run=state)


@mcp.tool(title="Get run")
async def get_run(run_id: UUID, ctx: Context) -> CallToolResult:
    """Read where a run stands: its status, every step's status and preview,
    a waiting review, output files and the error of a failed run.

    This is the only way to follow a run after run_flow. A run that is
    queued or running has not finished; report its state and offer to check
    again rather than waiting in a loop.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            state = await _run_in_space(tool_ctx.container, run_id, space_id)
    except _REPAIRABLE as exc:
        return _failure("get run", exc, run_id=run_id)
    return _result(_run_text(state), run=state)


@mcp.tool(title="Cancel run")
async def cancel_run(run_id: UUID, ctx: Context) -> CallToolResult:
    """Cancel a queued, running or review-paused run.

    Only on the user's request. The worker stops at the next step boundary;
    a step already executing finishes first. A finished run cannot be
    cancelled.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            state = await _run_in_space(tool_ctx.container, run_id, space_id)
            run_service = tool_ctx.container.flow_run_service()
            await run_service.cancel_run(run_id, flow_id=state.flow_id, channel=CHANNEL)
            state = await run_service.get_run_state(run_id)
    except _REPAIRABLE as exc:
        return _failure("cancel run", exc, run_id=run_id)
    logger.info("[FLOWS] cancelled run %s", run_id)
    return _result(
        _run_text(state, f"Run {run_id} is {state.status.value}."), run=state
    )


@mcp.tool(title="Review run")
async def review_run(
    run_id: UUID,
    decision: ReviewDecision,
    ctx: Context,
    edited_text: str | None = None,
    edited_value: dict[str, Any] | None = None,
    reason: str | None = None,
) -> CallToolResult:
    """Decide the review a run is paused on, on the user's behalf.

    Use it only when the user states their decision in the chat; the run
    panel offers the same buttons. approve continues the run; with
    edited_text (a text output) or edited_value (a JSON output) the
    reviewed output is replaced first, which an edit-mode review allows.
    reject fails the run, with reason recorded. A run without a waiting
    review cannot be reviewed.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            await _run_in_space(tool_ctx.container, run_id, space_id)
            run_service = tool_ctx.container.flow_run_service()
            checkpoint = await run_service.get_active_checkpoint(run_id)
            if checkpoint is None:
                raise _ToolRefused(NO_REVIEW_WAITING_MESSAGE)
            revision = checkpoint.revision
            if decision == "approve":
                payload = _edited_payload(
                    checkpoint.output_type, edited_text, edited_value
                )
                if payload is not None:
                    checkpoint = await run_service.edit_checkpoint(
                        run_id,
                        checkpoint.id,
                        expected_revision=revision,
                        current_payload_json=payload,
                    )
                    revision = checkpoint.revision
                await run_service.approve_checkpoint(
                    run_id,
                    checkpoint.id,
                    expected_revision=revision,
                    resume=True,
                    channel=CHANNEL,
                )
            else:
                await run_service.reject_checkpoint(
                    run_id,
                    checkpoint.id,
                    expected_revision=revision,
                    reason=reason,
                    channel=CHANNEL,
                )
            state = await run_service.get_run_state(run_id)
    except _REPAIRABLE as exc:
        return _failure("review run", exc, run_id=run_id)
    logger.info("[FLOWS] review %s on run %s", decision, run_id)
    lead = (
        f"Review {'approved' if decision == 'approve' else 'rejected'}; "
        f"run {run_id} is {state.status.value}."
    )
    return _result(_run_text(state, lead), run=state)


def _edited_payload(
    output_type: str, edited_text: str | None, edited_value: dict[str, Any] | None
) -> dict[str, Any] | None:
    """The checkpoint payload an edit replaces, matching the reviewed output."""
    if output_type == "json" and edited_value is not None:
        return {"value": edited_value}
    if edited_text is not None:
        return {"text": edited_text}
    if edited_value is not None:
        return {"value": edited_value}
    return None


async def build_flows_mcp_server(*, token: str, tenant_id: UUID) -> MCPServer:
    """Build the ephemeral MCP server eneo attaches to a space's flows chat."""
    return await build_ephemeral_server(
        mcp,
        name=FLOWS_SERVER_NAME,
        description="Loopback server through which the model authors and runs flows.",
        token=token,
        tenant_id=tenant_id,
    )
