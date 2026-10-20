# pyright: basic
# FastMCP's Context surface is largely untyped; this module is a thin adapter
# over it, so strict unknown-type checking adds noise without safety here.
"""Internal MCP server through which the model authors and runs flows.

A flow is a deterministic, ordered list of typed steps that a space runs
unattended (:mod:`eneo.flows.definition`). The model never executes a flow;
it writes the definition through these tools from the flow's chat,
publishes it, and starts runs that the worker executes. A flow is created
from the flows page (REST ``POST /flows/``) as an empty draft and bound to
the chat that authors it, so there is no tool to create one: ``flow_id``
is optional everywhere and defaults to the chat's own flow. The bearer
token's ``assistant_id`` claim names the hidden flows assistant of exactly
one space, so every tool is scoped to that space without taking it as an
argument, and a flow or run of another space reads as not found.

Each tool answers with a short text for the model (what was saved, the
validation problems verbatim, where a run stands) and with structured
content for the flow panel in the clients: top-level ``flow_id`` and
``run_id`` (nullable) plus the flow or the run state when the call produced
one. Problems the model can repair (validation errors, a missing flow, a
bad attachment link) come back as text that starts with "Could not", never
as a protocol error, so the model fixes the call and tries again. The write
tools also refuse that way while the user views the flow without having
entered edit mode in the panel. The transaction of a failed call rolls
back; the services record the audit entries of the successful ones.

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
from eneo.flows.flow_functions import list_flow_functions
from eneo.flows.flow_models import (
    FlowPublic,
    FlowRevisionSummaryPublic,
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
    FlowNotEditingException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.mcp_servers.domain.entities.mcp_server import MCPServer

logger = logging.getLogger(__name__)

__all__ = [
    "FLOWS_SERVER_NAME",
    "FLOW_NOT_FOUND_MESSAGE",
    "NOT_AUTHORING_ASSISTANT_MESSAGE",
    "NOT_BOUND_MESSAGE",
    "RUN_NOT_FOUND_MESSAGE",
    "build_flows_mcp_server",
    "cancel_run",
    "delete_flow",
    "get_flow",
    "get_run",
    "list_flows",
    "list_functions",
    "list_revisions",
    "mcp",
    "publish_flow",
    "restore_revision",
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
NOT_BOUND_MESSAGE = "This chat is not bound to a flow yet."
REVISIONS_SHOWN = 10

INSTRUCTIONS = """\
Tools for authoring and running the flows of this space. A flow is a
deterministic, ordered list of typed steps that runs unattended once a person
starts it with the run inputs (form fields). The step kind decides what runs;
nothing is decided at run time, and you never execute a flow yourself: you
write its definition, publish it, start runs and report on them.

This chat belongs to one flow, created empty from the flows page before the
chat started. Omit flow_id to work on it (the usual case); get_flow shows
where it stands. There is no tool to create a flow: the user starts another
one from the flows page.

Step kinds: llm (one completion with a fixed prompt; output is text or JSON
checked against a schema), compose (text assembled from a template, no model),
document (a Word or PDF file Eneo's document engine renders from a Markdown
template, or a form attached in this chat filled with values), function (one
call to one of Eneo's functions: web search, image generation, charts,
compute, file analysis, file creation; list_functions shows the tools and
their arguments), transcribe (the audio of a form field transcribed, with
speaker labels and names when asked), review (pauses the run until a person
approves or edits an earlier step's output).

Templates read run inputs and earlier steps with {{form.<key>}},
{{steps.<key>}}, {{steps.<key>.json.<path>}} and {{previous}}. A step can
only read form fields and steps that come before it.

A saved flow is a draft until publish_flow; run_flow runs the published
version, or with draft=true a test run of the draft while the user is still
building it. run_flow only queues the run and returns at once; get_run is how
to follow its progress. Validation problems come back as text starting with
"Could not": fix the definition and call again.

Every save (update_flow) is kept as a numbered revision the user can read in
the flow's history and restore; nothing is lost by changing a flow. Give update_flow a one-line note on what changed and why. list_revisions
shows the history and restore_revision brings an earlier revision back as the
draft (itself a new revision).

Changing a flow (update_flow, restore_revision, publish_flow, delete_flow)
needs the user to have pressed Redigera in the flow panel; when one of these
tools refuses because the flow is shown in view mode, ask the user to press
Redigera and then try again. Reading and running are always available.
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
    FlowNotEditingException,
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


async def _resolve_flow(
    tool_ctx: ToolContext, flow_id: UUID | None, space_id: UUID
) -> FlowPublic:
    """The flow a tool acts on: the given one, else the chat's own flow."""
    if flow_id is not None:
        return await _flow_in_space(tool_ctx.container, flow_id, space_id)
    bound = (
        await tool_ctx.container.flow_service().flow_for_conversation(
            tool_ctx.session_id
        )
        if tool_ctx.session_id is not None
        else None
    )
    if bound is None or bound.space_id != space_id:
        raise _ToolRefused(NOT_BOUND_MESSAGE)
    return bound


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
        f"Flow '{flow.name}' (flow_id {flow.id}; revision {flow.revision}; {state}).",
        _form_fields_text(flow.definition.form_fields),
        "Steps:",
        definition_summary(flow.definition) or "(none)",
    ]
    return "\n".join(lines)


def _flows_list_text(flows: list[FlowSparsePublic]) -> str:
    if not flows:
        return "No flows in this space yet. Flows are created from the flows page."
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


def _changes_text(revision: FlowRevisionSummaryPublic) -> str:
    changes = revision.changes
    if changes.is_initial:
        return "first revision"
    parts: list[str] = []
    if changes.name_changed:
        parts.append("name changed")
    if changes.description_changed:
        parts.append("description changed")
    if changes.form_fields_changed:
        parts.append("run inputs changed")
    if changes.steps_added:
        parts.append("steps added: " + ", ".join(changes.steps_added))
    if changes.steps_removed:
        parts.append("steps removed: " + ", ".join(changes.steps_removed))
    if changes.steps_changed:
        parts.append("steps changed: " + ", ".join(changes.steps_changed))
    return "; ".join(parts) or "no visible change"


def _revisions_text(
    flow: FlowPublic, revisions: list[FlowRevisionSummaryPublic], total: int
) -> str:
    lines = [
        f"History of '{flow.name}' (flow_id {flow.id}): {total} revision(s), "
        f"current is {flow.revision}. Newest first"
        + (f", last {len(revisions)} shown" if total > len(revisions) else "")
        + ":"
    ]
    for revision in revisions:
        line = (
            f"- revision {revision.revision} ({revision.created_at:%Y-%m-%d %H:%M}, "
            f"via {'chat' if revision.channel == 'mcp' else 'API'}): "
            + _changes_text(revision)
        )
        if revision.note:
            line += f'. Note: "{revision.note}"'
        if revision.published_version is not None:
            line += f" [published as version {revision.published_version}]"
        lines.append(line)
    lines.append(
        "restore_revision brings any of them back as the draft (as a new revision)."
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


def _version_text(state: FlowRunStatePublic) -> str:
    if state.is_test:
        return "test run of the draft"
    return f"version {state.flow_version}"


def _run_text(state: FlowRunStatePublic, lead: str | None = None) -> str:
    lines = [
        lead
        or f"Run {state.run_id} of flow {state.flow_id} "
        f"({_version_text(state)}): {state.status.value}."
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


@mcp.tool(title="List functions")
async def list_functions(ctx: Context) -> CallToolResult:
    """The functions (web search, image generation, charts, compute, file
    analysis, file creation) a function step can call in this space, with
    each tool's name, what it does and its arguments as a JSON Schema.

    Call it before writing a function step: a step names a purpose, a tool
    and arguments that must fit the schema. A function that is not enabled
    in the space is listed as unavailable; the user enables it in the
    space settings.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            functions = await _available_functions(tool_ctx, space_id)
    except _REPAIRABLE as exc:
        return _failure("list functions", exc)
    return _result(_functions_text(functions), functions=functions)


async def _available_functions(
    tool_ctx: ToolContext, space_id: UUID
) -> list[dict[str, Any]]:
    """Each purpose with its provider's tools, as the panel's editor lists them too."""
    container = tool_ctx.container
    space = await container.space_repo().one(space_id)
    functions = await list_flow_functions(
        space, container.assistant_service().capability_server
    )
    return [function.model_dump(mode="json") for function in functions]


def _functions_text(functions: list[dict[str, Any]]) -> str:
    lines: list[str] = ["Functions a function step can call in this space:"]
    for function in functions:
        purpose = function["purpose"]
        if not function["enabled_in_space"]:
            lines.append(f"- {purpose}: not enabled in this space.")
            continue
        if not function["available"]:
            lines.append(f"- {purpose}: enabled but no provider is available.")
            continue
        lines.append(f"- {purpose} (provider '{function['provider']}'):")
        for tool in function["tools"]:
            description = (tool.get("description") or "").strip().split("\n")[0]
            lines.append(f"  - {tool['name']}: {description[:200]}")
            schema = tool.get("input_schema") or {}
            properties = schema.get("properties") if isinstance(schema, dict) else None
            if isinstance(properties, dict):
                required = set(schema.get("required") or [])
                lines.append(
                    "    arguments: "
                    + ", ".join(
                        f"{name}{'*' if name in required else ''}"
                        for name in properties
                    )
                )
    lines.append(
        "Arguments marked * are required; the structured result carries each "
        "tool's full JSON Schema."
    )
    return "\n".join(lines)


@mcp.tool(title="List flows")
async def list_flows(ctx: Context) -> CallToolResult:
    """List the flows of this space, published or draft, for reference.

    The chat's own flow needs no id (omit flow_id in the other tools); use
    this to find another flow's id when the user names one.
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
async def get_flow(ctx: Context, flow_id: UUID | None = None) -> CallToolResult:
    """Read a flow's current draft definition, revision and publication state.

    Omit flow_id to work on this chat's flow (the usual case). Read a flow
    before changing it: update_flow replaces the given lists whole, so send
    every form field or step you want to keep. A new flow is empty (no
    inputs, no steps) until update_flow gives it some.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            flow = await _resolve_flow(tool_ctx, flow_id, space_id)
    except _REPAIRABLE as exc:
        return _failure("get flow", exc, flow_id=flow_id)
    return _result(_flow_text(flow, "Current definition."), flow=flow)


@mcp.tool(title="Update flow")
async def update_flow(
    ctx: Context,
    flow_id: UUID | None = None,
    name: str | None = None,
    description: str | None = None,
    form_fields: list[FormField] | None = None,
    steps: list[Step] | None = None,
    note: str | None = None,
) -> CallToolResult:
    """Change a flow's name, description, run inputs or steps.

    Omit flow_id to work on this chat's flow (the usual case). Only the
    arguments given change. A given form_fields or steps list replaces the
    whole list, so include every item to keep; a step keeps its identity
    (and its run history) when its key stays the same. Changes land in the
    draft: publish_flow again for runs to use them.

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
    - document: a file Eneo's document engine produces, always, with the
      values bound. Either content (a Markdown template for the body; title
      and filename are templates too; format docx or pdf; the organisation's
      document template applies) or template_file_id (a .docx, .txt or .md
      form the user attached in this chat, named by its file_ref such as
      eneo-file:<id>; values maps each of the form's fields, a content
      control tag or {{placeholder}}, to a template; format stays docx). The
      file is the step's output; {{steps.<key>}} is its filename.
    - function: one call to a tool of one of Eneo's functions (purpose
      web_search, image_generation, charts, compute, file_analysis or
      file_creation) with arguments fixed here; call list_functions first to
      see the tools and the exact argument names. Every string in arguments
      is a template; {{files.<key>}} (with files_from naming the field) and
      {{steps.<key>.file}} give a tool a file link. The step's output is the
      tool's text, its structured value ({{steps.<key>.json.<path>}}) and
      the files or images it made ({{steps.<key>.file}}).
    - transcribe: transcribes the audio of form field source (type audio or
      file) with the space's transcription model; language is an ISO code or
      null. speaker_labels true labels who speaks (needs the speaker service
      this Eneo is configured with) and speaker_mapping names the labels:
      participants_field names a text form field listing the participants,
      infer_names lets the conversation itself name them. The output is the
      transcript text; a reviewer can correct it afterwards through the API.
    - review: pauses the run until a person approves (mode view) or edits
      and approves (mode edit) the output of step `of` (default the previous
      step). Cannot be the first step, cannot review another review.

    Keys are short lower-case identifiers (letters, digits, underscore) that
    stay stable across edits; templates read {{form.<key>}}, {{steps.<key>}},
    {{steps.<key>.json.<path>}} and {{previous}}, and a step only reads what
    comes before it. Do not send step ids; Eneo assigns them. Validation
    problems come back as text starting with "Could not update flow": fix
    them and call again.

    Every save is kept as a revision the user can read and restore later,
    so changing a flow never loses anything. note is one line on what
    changed and why ("Shortened the summary prompt at the user's request");
    it is shown in the flow's history, so give one with every change.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            current = await _resolve_flow(tool_ctx, flow_id, space_id)
            flow_id = current.id
            await tool_ctx.container.flow_service().require_editing(current.id)
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
                current.id,
                name=name,
                description=description,
                definition=definition,
                conversation_id=tool_ctx.session_id,
                channel=CHANNEL,
                note=note,
            )
    except _REPAIRABLE as exc:
        return _failure("update flow", exc, flow_id=flow_id)
    logger.info("[FLOWS] updated flow %s", flow.id)
    lead = (
        f"Draft updated as revision {flow.revision}. Publish it with publish_flow "
        "to run it."
        if flow.revision != current.revision
        else "Nothing changed: the draft already looked like this."
    )
    return _result(_flow_text(flow, lead), flow=flow)


@mcp.tool(title="List revisions")
async def list_revisions(ctx: Context, flow_id: UUID | None = None) -> CallToolResult:
    """Read a flow's history: every save as a numbered revision, newest first.

    Omit flow_id to work on this chat's flow (the usual case). Each revision says when it was made, from the chat or the API, the note
    given with it, what it changed (name, description, run inputs, steps
    added, removed or changed) and whether a published version froze it.
    Use it when the user asks what changed, wants to go back, or compares
    with how the flow was; restore_revision brings one back.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            flow = await _resolve_flow(tool_ctx, flow_id, space_id)
            flow_id = flow.id
            revisions, total = await tool_ctx.container.flow_service().list_revisions(
                flow.id, limit=REVISIONS_SHOWN
            )
    except _REPAIRABLE as exc:
        return _failure("list revisions", exc, flow_id=flow_id)
    return _result(
        _revisions_text(flow, revisions, total),
        flow_id=flow.id,
        revisions=[revision.model_dump(mode="json") for revision in revisions],
    )


@mcp.tool(title="Restore revision")
async def restore_revision(
    revision: int, ctx: Context, flow_id: UUID | None = None
) -> CallToolResult:
    """Make an earlier revision the flow's draft again.

    Omit flow_id to work on this chat's flow (the usual case). The restore is itself a new revision (noted "Restored revision N"), so
    nothing is lost and it can be undone the same way. Steps keep their
    identity. Use it on the user's request, after list_revisions showed
    which revision they mean. Changes land in the draft: publish_flow again
    for runs to use them.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            current = await _resolve_flow(tool_ctx, flow_id, space_id)
            flow_id = current.id
            flow_service = tool_ctx.container.flow_service()
            await flow_service.require_editing(current.id)
            flow = await flow_service.restore_revision(
                current.id, revision, channel=CHANNEL
            )
    except _REPAIRABLE as exc:
        return _failure("restore revision", exc, flow_id=flow_id)
    logger.info("[FLOWS] restored flow %s to revision %s", flow.id, revision)
    return _result(
        _flow_text(
            flow,
            f"Restored revision {revision} as the draft (now revision "
            f"{flow.revision}). Publish it with publish_flow to run it.",
        ),
        flow=flow,
        restored_from=revision,
    )


@mcp.tool(title="Publish flow")
async def publish_flow(ctx: Context, flow_id: UUID | None = None) -> CallToolResult:
    """Publish the flow's draft as its next version.

    Omit flow_id to work on this chat's flow (the usual case). Runs always use the published version; a draft, or a draft edited since
    the last publish, cannot run until it is published. The result tells
    what a run needs: the run inputs, where a review pauses it and what the
    final output is.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            current = await _resolve_flow(tool_ctx, flow_id, space_id)
            flow_id = current.id
            flow_service = tool_ctx.container.flow_service()
            await flow_service.require_editing(current.id)
            flow = await flow_service.publish_flow(current.id, channel=CHANNEL)
            contract = await flow_service.get_run_contract(current.id)
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
async def delete_flow(ctx: Context, flow_id: UUID | None = None) -> CallToolResult:
    """Delete a flow of this space.

    Omit flow_id to work on this chat's flow (the usual case). Only on the
    user's explicit request. The flow leaves the space's list;
    its run history stays readable to API consumers that reference it.
    """
    try:
        async with internal_tool_context(ctx) as tool_ctx:
            space_id = await _authoring_space_id(tool_ctx)
            flow = await _resolve_flow(tool_ctx, flow_id, space_id)
            flow_id = flow.id
            flow_service = tool_ctx.container.flow_service()
            await flow_service.require_editing(flow.id)
            await flow_service.delete_flow(flow.id, channel=CHANNEL)
    except _REPAIRABLE as exc:
        return _failure("delete flow", exc, flow_id=flow_id)
    logger.info("[FLOWS] deleted flow %s", flow_id)
    return _result(f"Deleted flow '{flow.name}'.", flow_id=flow_id, deleted=True)


@mcp.tool(title="Run flow")
async def run_flow(
    inputs: dict[str, InputValue],
    ctx: Context,
    flow_id: UUID | None = None,
    files: dict[str, list[str]] | None = None,
    run_label: str | None = None,
    draft: bool = False,
) -> CallToolResult:
    """Start a run of the flow's published version with the given inputs,
    or with draft=true a test run of the draft as it is now.

    Omit flow_id to work on this chat's flow (the usual case). inputs maps text, number and select form field keys to their values;
    files maps file and audio form field keys to the attachment reference
    URLs from this conversation (the exact "url" values of the file
    reference entries, never constructed). Every required field needs a
    value or a file. draft=true is how the user tries a flow out while
    building it: nothing is published, the run is marked as a test, and
    the draft must be complete enough to publish.

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
            flow = await _resolve_flow(tool_ctx, flow_id, space_id)
            flow_id = flow.id
            file_ids: dict[str, list[UUID]] = {}
            for key, urls in (files or {}).items():
                file_ids[key] = [
                    await _referenced_file_id(url, tool_ctx) for url in urls
                ]
            run_service = tool_ctx.container.flow_run_service()
            run = await run_service.create_run(
                flow.id,
                values=dict(inputs),
                files=file_ids,
                run_label=run_label,
                draft=draft,
                channel=CHANNEL,
            )
            state = await run_service.get_run_state(run.id)
    except _REPAIRABLE as exc:
        return _failure("run flow", exc, flow_id=flow_id)
    logger.info("[FLOWS] queued run %s of flow %s", state.run_id, flow.id)
    lead = (
        f"Run {state.run_id} of '{flow.name}' ({_version_text(state)}) is "
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
