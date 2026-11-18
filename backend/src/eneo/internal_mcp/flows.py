# pyright: basic
"""Thin session-bound tools over the adopted flow core's authorized operations."""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal, cast
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import (
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    WithJsonSchema,
    with_config,
)
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import Annotated, Required, TypedDict

from eneo.flows.domain.step_kinds import (
    STEP_KIND_DESCRIPTIONS,
    FlowStepKind,
    StepKindValues,
    step_kind_takes,
    step_kind_value_names,
)
from eneo.internal_mcp.constants import FLOWS_SERVER_NAME
from eneo.internal_mcp.foundation import (
    build_ephemeral_server,
    default_page_cap,
    internal_tool_context,
)
from eneo.main.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
    UnauthorizedException,
)

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="Eneo Flows",
    stateless_http=True,
    instructions="Configure the flow bound to this chat.",
)

# The MCP annotations of the tools. Reading tools change nothing. Draft edits
# change only the draft, gated by edit mode. A tool that acts beyond the
# draft (starts, retries or cancels a run, decides a review, publishes)
# declares destructiveHint, and the chat asks the person before each call.
_READS = ToolAnnotations(readOnlyHint=True)
_EDITS_DRAFT = ToolAnnotations(readOnlyHint=False, destructiveHint=False)
_ACTS = ToolAnnotations(readOnlyHint=False, destructiveHint=True)


def _tool(annotations: ToolAnnotations, *, appendix: str = "", closed: bool = False):
    """Register a flow tool. Its description is its docstring without the
    source's indentation, then ``appendix``: the model reads every
    description in every round.

    The tool server checks the arguments before the tool runs, and its
    refusal would repeat each value it rejects; a credential sent in a wrongly
    shaped argument would be written back into the conversation. The check
    here names the argument and leaves its value out, as the tools' own
    refusals do. ``closed`` refuses an argument the tool does not have instead
    of dropping it."""

    def register(fn):
        registered = mcp.tool(
            annotations=annotations,
            description=inspect.cleandoc(fn.__doc__ or "") + appendix,
        )(fn)
        # The SDK hands out no registered tool but through its manager.
        tool = mcp._tool_manager.get_tool(fn.__name__)
        assert tool is not None
        checked = tool.fn_metadata.arg_model
        config = ConfigDict(checked.model_config)
        config["hide_input_in_errors"] = True
        if closed:
            config["extra"] = "forbid"
            tool.parameters["additionalProperties"] = False
        tool.fn_metadata = tool.fn_metadata.model_copy(
            update={
                "arg_model": type(
                    checked.__name__, (checked,), {"model_config": config}
                )
            }
        )
        return registered

    return register


# The two reads update_step shows the model; the tests hold them to the step
# rules (save and publish), so the chat never learns a shape the flow refuses.
INPUT_BINDINGS_EXAMPLES: dict[str, dict[str, Any]] = {
    "fields": {
        "source_refs": [
            {
                "step_ref": "step_1",
                "output": "structured",
                "field_path": "beslut",
                "label": "Beslut",
            },
            {
                "step_ref": "step_1",
                "output": "structured",
                "field_path": "datum",
                "label": "Datum",
            },
        ]
    },
    "text": {"source_refs": [{"step_ref": "step_1", "output": "text"}]},
}
# A json step whose input is exactly two fields of step 1's json result, with
# the input_contract the step rules derive for them.
JSON_READ_EXAMPLE: dict[str, Any] = {
    "input_type": "json",
    "input_bindings": INPUT_BINDINGS_EXAMPLES["fields"],
    "input_contract": {
        "type": "object",
        "properties": {"beslut": {"type": "string"}, "datum": {"type": "string"}},
        "additionalProperties": False,
        "required": ["beslut", "datum"],
    },
}


def _closed_schema(shape: Any) -> dict[str, Any]:
    """The JSON schema of ``shape`` with its definitions inlined, for an
    argument the tool validates itself: the model reads the closed shape in
    the tool's schema, and a refusal names a wrong key without repeating the
    value sent with it, as the arguments' own validation would."""
    schema = TypeAdapter(shape).json_schema()
    definitions = schema.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return inline(definitions[node["$ref"].rsplit("/", 1)[-1]])
            return {key: inline(value) for key, value in node.items()}
        if isinstance(node, list):
            return [inline(value) for value in node]
        return node

    return inline(schema)


def _example(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


# What a step reads, said once, where a change to a step is described
# (input_binding_contract_rules owns the keys; step_definition_parser the
# input_contract rule).
_INPUT_BINDINGS_SHAPE = (
    "\ninput_bindings sets what the step reads; its input_source is then not"
    " read. It takes question (the input as text with {{ }} references)"
    " and/or source_refs, a list of reads. A source_ref has step_ref"
    ' ("step_N"), output ("text": the step\'s whole text; "structured":'
    " its json result, with field_path naming one field of its"
    ' output_contract, dotted for a nested field: "sak.diarienummer"),'
    " label (written before the value) and, in a compose_text step,"
    ' item_template ("{titel}: {text}" for each item of a list field).'
    " A step that reads two fields of step 1's json result: "
    + _example(INPUT_BINDINGS_EXAMPLES["fields"])
    + ". A step that reads the whole text of step 1: "
    + _example(INPUT_BINDINGS_EXAMPLES["text"])
    + ". With input_type json and only structured refs (each with field_path;"
    " no question and no item_template), the step's input is exactly those"
    " fields and needs an input_contract equal to them: "
    + _example(JSON_READ_EXAMPLE)
    + ". With other input_bindings send no input_contract; a json step without"
    " input_bindings may keep its own."
)


# How the audit entries of a change made through the chat name their origin.
AUTHORING_CHAT_ORIGIN = "authoring_chat"
_CHAT_AUDIT = {"origin": AUTHORING_CHAT_ORIGIN}

_STALE_REVISION_MESSAGE = (
    "The draft changed since you read it. Read the flow again with read_flow "
    "and reapply only your own change on top of what is there."
)


def _page_size() -> int:
    """The characters of a value one page carries."""
    return max(1, min(4000, default_page_cap() // 4))


def _serialized(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def page_result(
    value: Any, *, flow_id: UUID, offset: int = 0, revision: int | None = None
) -> CallToolResult:
    if offset < 0:
        raise BadRequestException("offset must be non-negative.")
    serialized = _serialized(value)
    if offset > len(serialized):
        raise BadRequestException(
            "offset is beyond this value; read again from offset 0 after a change."
        )
    end = min(len(serialized), offset + _page_size())
    page = {
        "flow_id": str(flow_id),
        "draft_revision": revision,
        "offset": offset,
        "total_chars": len(serialized),
        "next_offset": end if end < len(serialized) else None,
        "content": serialized[offset:end],
    }
    while (
        len(json.dumps(page, ensure_ascii=False)) > default_page_cap() and end > offset
    ):
        end = offset + (end - offset) // 2
        page.update(content=serialized[offset:end], next_offset=end)
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(page, ensure_ascii=False))],
        structuredContent={"flow_id": str(flow_id), "draft_revision": revision},
    )


async def _call(
    ctx: Context,
    operation: Callable[..., Awaitable[CallToolResult]],
    *,
    editing: bool = False,
    changes_draft: bool = False,
) -> CallToolResult:
    """Run ``operation`` for the chat's flow in one authoring transaction.
    ``editing`` requires edit mode; ``changes_draft`` (which implies it)
    also reports the suggestions the change introduced (``_with_introduced``)
    and what stands between the draft and publishing
    (``_with_publish_blockers``).
    """
    from eneo.flows.application.flow_authoring_chat import (
        load_authoring_chat,
        require_authoring_edit,
        scoped_request,
    )
    from eneo.flows.application.flow_authoring_operations import (
        authoring_transaction,
    )
    from eneo.flows.flow_api_error_code import FlowApiErrorCode

    try:
        # Refusals are caught outside the transaction so failed writes roll
        # back; the change's audit entries are logged once it has committed.
        async with internal_tool_context(ctx, transactional=False) as scope:
            if scope.session_id is None:
                raise NotFoundException("Flow authoring chat not found.")
            try:
                async with authoring_transaction(scope.container):
                    chat = await load_authoring_chat(
                        scope.container,
                        session_id=scope.session_id,
                        assistant_id=scope.assistant_id,
                        lock=editing or changes_draft,
                    )
                    if editing or changes_draft:
                        await require_authoring_edit(
                            scope.container, chat, draft=changes_draft
                        )
                    request = scoped_request(chat.space_id)
                    if not changes_draft:
                        return await operation(scope.container, chat, request)
                    before = await _draft_suggestions(scope.container, chat.flow_id)
                    result = await operation(scope.container, chat, request)
                    result = await _with_introduced(
                        result, scope.container, chat.flow_id, before
                    )
                    result = await _with_publish_blockers(
                        result, scope.container, chat.flow_id
                    )
                    return _within_page_cap(result)
            except BadRequestException as exc:
                if exc.code != FlowApiErrorCode.STALE_REVISION:
                    raise
                # The editor's refusal tells a person to reload the page; the
                # model gets the revision to read the draft again at.
                return _refusal(
                    _STALE_REVISION_MESSAGE,
                    code=FlowApiErrorCode.STALE_REVISION.value,
                    current_revision=await _current_revision(scope),
                )
    except (
        BadRequestException,
        ConflictException,
        NotFoundException,
        UnauthorizedException,
        ValidationError,
    ) as exc:
        return _error_result(exc)


def _refusal(
    message: str, *, code: str | None, errors: Any = None, **fields: Any
) -> CallToolResult:
    """A refusal the model reads: its message, its code, the fields the core's
    models reject (``errors``) and any further ``fields``."""
    return CallToolResult(
        isError=True,
        content=[
            TextContent(
                type="text",
                text=json.dumps(
                    {"message": message, "code": code, "errors": errors, **fields},
                    default=str,
                ),
            )
        ],
    )


class _Refused(BadRequestException):
    """A tool's own refusal that tells the model more than its message:
    ``fields`` stand beside the message and the code, as ``_refusal`` takes
    them. Raised, so the call's transaction rolls back like any refusal."""

    def __init__(self, message: str, *, code: str, **fields: Any):
        super().__init__(message, code=code)
        self.fields = fields


# The most rejected fields, or templates of the flow, a refusal lists.
MAX_LISTED = 10


def _error_result(
    exc: BadRequestException
    | ConflictException
    | NotFoundException
    | UnauthorizedException
    | ValidationError,
) -> CallToolResult:
    """The refusal of a tool call that raised ``exc``. A refused read
    (``input_bindings``) also names the keys the step rules take, as
    ``invalid_message`` names a step's fields."""
    from eneo.flows.input_binding_contract_rules import (
        FLOW_INPUT_BINDING_UNSUPPORTED_KEY,
        SOURCE_REF_KEYS,
        SUPPORTED_INPUT_BINDING_KEYS,
    )

    if isinstance(exc, ValidationError):
        errors = exc.errors(include_input=False, include_context=False)
        return _refusal(invalid_message(errors), code=None, errors=errors)
    if isinstance(exc, _Refused):
        return _refusal(str(exc), code=exc.code, **exc.fields)
    code = getattr(exc, "code", None)
    message = str(exc)
    # The code also covers reads the rules cannot resolve; only a refusal
    # that names an unsupported key is about the shape.
    if code == FLOW_INPUT_BINDING_UNSUPPORTED_KEY and (
        "unsupported key" in message.lower()
        or "unsupported input_bindings key" in message.lower()
    ):
        message += (
            " input_bindings takes "
            + " and ".join(sorted(SUPPORTED_INPUT_BINDING_KEYS))
            + "; a source_ref takes "
            + ", ".join(sorted(SOURCE_REF_KEYS))
            + ", as update_step describes them. Correct the read and make the"
            " call again."
        )
    return _refusal(message, code=code)


async def _current_revision(scope: Any) -> int | None:
    """The draft revision of the chat's flow now, read in a transaction of
    its own after a refused change has rolled back; None when it cannot be
    read, which is logged by its kind only."""
    from eneo.flows.application.flow_authoring_chat import (
        load_authoring_chat,
        scoped_request,
    )
    from eneo.flows.application.flow_authoring_operations import get_flow

    try:
        async with cast(AsyncSession, scope.container.session()).begin():
            chat = await load_authoring_chat(
                scope.container,
                session_id=scope.session_id,
                assistant_id=scope.assistant_id,
            )
            flow = await get_flow(
                chat.flow_id, scoped_request(chat.space_id), scope.container
            )
            return flow.draft_revision
    except Exception as exc:  # noqa: BLE001 - the refusal is reported either way
        logger.warning(
            "The draft revision could not be read after a stale change",
            extra={"error_type": type(exc).__name__},
        )
        return None


# What a step's own fields are not: the core gives a step its identity and place.
_STEP_IDENTITY_FIELDS = frozenset({"id", "assistant_id", "step_order"})


def _step_fields() -> list[str]:
    """The fields a step's configuration takes, as the core's model has them."""
    from eneo.flows.api.flow_models import FlowEditorStepPatch

    return [
        name
        for name in FlowEditorStepPatch.model_fields
        if name not in _STEP_IDENTITY_FIELDS
    ]


def invalid_message(errors: Any) -> str:
    """The refusal of a configuration the core's models reject. A field the
    core does not have is named, with the fields a step takes when it stood
    in a step and the shape of an assistant when it stood in one, so the
    model corrects the call and makes it again."""
    message = "The submitted configuration is invalid."
    unknown = [
        tuple(error.get("loc", ()))
        for error in errors
        if error.get("type") == "extra_forbidden"
    ]
    if not unknown:
        return message
    names = ", ".join(dict.fromkeys(str(loc[-1]) for loc in unknown if loc))
    message += (
        f" It names {names}, which is not a field here: leave it out and make"
        " the call again."
    )
    if any({"configuration", "changes"} & set(loc) for loc in unknown):
        message += (
            " A step is described by these fields and no other: "
            + ", ".join(_step_fields())
            + "."
        )
    if any({"assistant", "assistants"} & set(loc) for loc in unknown):
        message += (
            " An assistant takes only its own fields: its instruction is"
            ' {"prompt": {"text": "..."}}.'
        )
    return message


async def _draft_suggestions(container, flow_id: UUID):
    """The draft's static suggestions and its steps, read in a savepoint of
    the change's transaction, without those the flow's editors dismissed;
    None when they cannot be computed. A failure is logged by its kind only
    and never fails the change."""
    from eneo.flows.application.flow_suggestion_dismissals import (
        shown_flow_suggestions,
    )
    from eneo.flows.application.flow_suggestion_service import (
        list_flow_suggestions,
    )

    try:
        async with cast(AsyncSession, container.session()).begin_nested():
            flow = await container.flow_service().get_flow(flow_id)
            suggestions = await list_flow_suggestions(container=container, flow=flow)
            return flow.steps, await shown_flow_suggestions(
                container, flow, suggestions
            )
    except Exception as exc:  # noqa: BLE001 - the change must not depend on it
        logger.warning(
            "Flow suggestions could not be computed around a chat change",
            extra={"flow_id": str(flow_id), "error_type": type(exc).__name__},
        )
        return None


async def _with_introduced(
    result: CallToolResult, container, flow_id: UUID, before
) -> CallToolResult:
    """``result`` with the suggestions the change introduced
    (``introduced_suggestions``, in short) and the draft's
    ``suggestion_count`` added to its page, dismissed suggestions left out
    of both; ``result`` unchanged when either side could not be computed."""
    from eneo.flows.application.flow_suggestion_service import (
        MAX_REPORTED_INTRODUCED,
        introduced_suggestions,
        suggestion_summary,
    )

    if before is None or result.isError or not result.content:
        return result
    after = await _draft_suggestions(container, flow_id)
    if after is None:
        return result
    steps, suggestions = after
    content = result.content[0]
    if not isinstance(content, TextContent):
        return result
    page = json.loads(content.text)
    introduced = [
        suggestion_summary(suggestion, steps)
        for suggestion in introduced_suggestions(before[1], suggestions)
    ]
    page["introduced_suggestions"] = introduced[:MAX_REPORTED_INTRODUCED]
    page["suggestion_count"] = len(suggestions)
    result.content = [
        TextContent(type="text", text=json.dumps(page, ensure_ascii=False))
    ]
    return result


# The most publish blockers one change result lists; the count says how many
# there are.
MAX_REPORTED_PUBLISH_BLOCKERS = 10
_CUT_BLOCKERS_NOTE = (
    'Only the first publish blockers are listed; read_flow section "blockers" '
    "lists them all."
)
_UNREAD_BLOCKERS_NOTE = (
    "The change is saved, but its publish blockers could not be read now; "
    'read_flow section "blockers" reads them again.'
)


async def _publish_blockers(container, flow_id: UUID) -> list[dict[str, Any]] | None:
    """What publish would refuse the draft for now (``FlowService
    .publish_blockers``), each in short with its step by order and name, read
    in a savepoint of the caller's transaction, the same refusal met twice
    listed once; None when it cannot be computed. A failure is logged by its
    kind only and never fails the change."""
    try:
        async with cast(AsyncSession, container.session()).begin_nested():
            service = container.flow_service()
            flow = await service.get_flow(flow_id)
            refusals = await service.publish_blockers(flow)
    except Exception as exc:  # noqa: BLE001 - the change must not depend on it
        logger.warning(
            "Publish blockers could not be computed after a chat change",
            extra={"flow_id": str(flow_id), "error_type": type(exc).__name__},
        )
        return None
    names = {step.step_order: step.user_description for step in flow.steps}
    blockers: list[dict[str, Any]] = []
    for refusal in refusals:
        context = refusal.context or {}
        blocker: dict[str, Any] = {
            "code": context.get("issue_code") or refusal.code,
            "message": str(refusal),
        }
        order = getattr(refusal, "step_order", None) or context.get("step_order")
        if isinstance(order, int):
            blocker["step"] = {"step_order": order, "name": names.get(order)}
        if blocker not in blockers:
            blockers.append(blocker)
    return blockers


async def _with_publish_blockers(
    result: CallToolResult, container, flow_id: UUID
) -> CallToolResult:
    """``result`` with what stands between the draft, as the change left it,
    and publishing added to its page: ``publish_blockers`` (the first
    ``MAX_REPORTED_PUBLISH_BLOCKERS``; ``_within_page_cap`` may list fewer),
    ``publish_blocker_count`` (all of them) and ``publish_blockers_complete``;
    when the list could not be read (both null then), ``publish_blockers_note``
    says so; ``_within_page_cap`` notes a cut list."""
    if result.isError or not result.content:
        return result
    content = result.content[0]
    if not isinstance(content, TextContent):
        return result
    blockers = await _publish_blockers(container, flow_id)
    page = json.loads(content.text)
    if blockers is None:
        page["publish_blockers"] = page["publish_blocker_count"] = None
        page["publish_blockers_complete"] = False
        page["publish_blockers_note"] = _UNREAD_BLOCKERS_NOTE
    else:
        page["publish_blockers"] = blockers[:MAX_REPORTED_PUBLISH_BLOCKERS]
        page["publish_blocker_count"] = len(blockers)
    result.content = [
        TextContent(type="text", text=json.dumps(page, ensure_ascii=False))
    ]
    return result


def _within_page_cap(result: CallToolResult) -> CallToolResult:
    """The one owner of a change result's page budget, run once both the
    introduced suggestions and the publish blockers are on the page. Optional
    content gives way, last item first, until the serialised page fits: the
    introduced suggestions, then the listed blockers, then the blockers note.
    suggestion_count, publish_blocker_count and publish_blockers_complete
    always stay, and the flag and note always describe the list as cut.

    The introduced suggestions are a hint and carry no completeness flag of
    their own: suggestion_count says how many the draft has, and
    read_flow_suggestions returns them all. A page whose mandatory part alone
    exceeds the cap is page_result's matter, not handled here."""
    if result.isError or not result.content:
        return result
    content = result.content[0]
    if not isinstance(content, TextContent):
        return result
    page = json.loads(content.text)
    cap = default_page_cap()

    def over() -> bool:
        return len(json.dumps(page, ensure_ascii=False)) > cap

    def describe_blockers() -> None:
        listed = page.get("publish_blockers")
        if listed is None:
            return  # unread: the flag and its note are set where it was read
        complete = len(listed) == page["publish_blocker_count"]
        page["publish_blockers_complete"] = complete
        if complete:
            page.pop("publish_blockers_note", None)
        else:
            page["publish_blockers_note"] = _CUT_BLOCKERS_NOTE

    describe_blockers()
    while over() and page.get("introduced_suggestions"):
        page["introduced_suggestions"] = page["introduced_suggestions"][:-1]
    while over() and page.get("publish_blockers"):
        page["publish_blockers"] = page["publish_blockers"][:-1]
        describe_blockers()
    if over():
        page.pop("publish_blockers_note", None)
    result.content = [
        TextContent(type="text", text=json.dumps(page, ensure_ascii=False))
    ]
    return result


async def _call_runtime(
    ctx: Context, operation: Callable[..., Awaitable[CallToolResult]]
) -> CallToolResult:
    from eneo.flows.application.flow_authoring_chat import (
        FlowAuthoringChatPublic,
        load_authoring_chat,
        scoped_request,
    )

    try:
        async with internal_tool_context(
            ctx, transactional=False, with_upload_admission=True
        ) as scope:
            if scope.session_id is None:
                raise NotFoundException("Flow authoring chat not found.")
            async with cast(AsyncSession, scope.container.session()).begin():
                chat = await load_authoring_chat(
                    scope.container,
                    session_id=scope.session_id,
                    assistant_id=scope.assistant_id,
                )
                binding = FlowAuthoringChatPublic.model_validate(chat)
                request = scoped_request(chat.space_id)
            return await operation(scope.container, binding, request)
    except (
        BadRequestException,
        ConflictException,
        NotFoundException,
        UnauthorizedException,
        ValidationError,
    ) as exc:
        return _error_result(exc)


def _runtime_result(value: Any, *, flow_id: UUID, offset: int = 0) -> CallToolResult:
    from starlette.responses import Response

    if isinstance(value, Response):
        payload = json.loads(bytes(value.body))
        result = page_result(payload, flow_id=flow_id, offset=offset)
        result.isError = value.status_code >= 400
        return result
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    result = page_result(payload, flow_id=flow_id, offset=offset)
    if isinstance(payload, dict) and "id" in payload:
        result.structuredContent = {"flow_id": str(flow_id), "run_id": payload["id"]}
    return result


FlowSection = Literal["overview", "steps", "settings", "blockers", "all"]


async def _transcription_offer(container, space_id: UUID) -> dict[str, Any] | None:
    """What the flow's space offers for transcription
    (``flow_authoring_reads.transcription_offer``); None when it cannot be
    read, which is logged by its kind only and never fails the read."""
    from eneo.flows.application.flow_authoring_reads import transcription_offer

    try:
        async with cast(AsyncSession, container.session()).begin_nested():
            space = await container.space_service().get_space(space_id)
        return transcription_offer(space)
    except Exception as exc:  # noqa: BLE001 - the flow is read either way
        logger.warning(
            "The space's transcription offer could not be read for the flow chat",
            extra={"space_id": str(space_id), "error_type": type(exc).__name__},
        )
        return None


# What the overview says of a step besides its reads.
_OVERVIEW_STEP_FIELDS = frozenset(
    {
        "id",
        "step_order",
        "assistant_id",
        "user_description",
        "input_source",
        "input_type",
        "output_mode",
        "output_type",
    }
)


def _step_overview(step: Any) -> dict[str, Any]:
    """A step in short, as the overview gives it: what it reads and gives,
    the fields its result declares and whether a person reviews it."""
    from eneo.flows.application.flow_authoring_reads import output_fields

    item = {
        key: value
        for key, value in step.model_dump(mode="json").items()
        if key in _OVERVIEW_STEP_FIELDS
    }
    item["output_fields"] = output_fields(step.output_contract)
    item["review"] = step.review_policy is not None
    return item


async def _saved_reads(container, flow_id: UUID) -> tuple[dict[int, Any], Any]:
    """What each step of the saved draft reads, by step order, and the
    prompts of its assistants."""
    from eneo.flows.application.flow_authoring_reads import step_reads_summary

    saved = await container.flow_service().get_flow(flow_id)
    prompts = await container.flow_service().get_flow_assistant_prompts(saved)
    return step_reads_summary(saved, prompts), prompts


def _cut(text: str | None, limit: int = 80) -> str | None:
    """Display text in an answer that must stay small; read_flow gives it whole."""
    return text if text is None or len(text) <= limit else text[:limit] + "…"


def _template_id(output_config: Any) -> str:
    """The template a Word step's output_config names; "" when it names none."""
    if not isinstance(output_config, dict):
        return ""
    return str(output_config.get("template_asset_id") or "").strip()


async def _flow_templates(
    container, flow_id: UUID, *, whole_names: bool = False
) -> dict[str, str]:
    """The Word templates the flow has, the last changed first: each id with
    its file name, cut short unless ``whole_names``. A refusal and the answer
    to an addition must stay small; read_flow pages."""
    assets = await container.flow_template_asset_service().list_assets(flow_id=flow_id)
    return {
        str(asset.id): asset.name if whole_names else cast(str, _cut(asset.name))
        for asset in assets
    }


async def _readable_templates(container, chat: Any) -> dict[str, str]:
    """The flow's templates for a read, each with its whole file name: none
    unless the chat is in edit mode, since the editor lists a flow's
    templates for those who may edit it."""
    from eneo.flows.application.flow_authoring_chat import require_authoring_edit

    try:
        await require_authoring_edit(container, chat)
    except (BadRequestException, UnauthorizedException):
        return {}
    return await _flow_templates(container, chat.flow_id, whole_names=True)


def _listed_templates(templates: dict[str, str]) -> list[dict[str, str]]:
    """The first of ``templates`` for a refusal, each by its id and file name;
    read_flow lists them all."""
    return [
        {"id": template_id, "name": name}
        for template_id, name in list(templates.items())[:MAX_LISTED]
    ]


def _step_reads(
    step: Any, reads: dict[int, Any], templates: dict[str, str]
) -> dict[str, Any]:
    """What ``step`` reads and talks to, as the overview gives it: its
    connections, a Word step's template (its id, and its file name when it is
    among ``templates``; None while the step waits for one) and fields, and
    its reads (see ``_saved_reads``)."""
    from eneo.flows.application.flow_authoring_reads import (
        step_connections,
        word_fields,
    )

    # The services the step talks to, never their secrets.
    item: dict[str, Any] = {
        "connections": step_connections(step.model_dump(mode="json"))
    }
    if step.output_mode == "template_fill":
        template_id = _template_id(step.output_config)
        item["word_template"] = (
            {"id": template_id, "name": templates.get(template_id)}
            if template_id
            else None
        )
        item["word_fields"] = word_fields(step.output_config)
    item.update(reads.get(step.step_order, {}))
    return item


@_tool(_READS)
async def read_flow(
    ctx: Context,
    section: FlowSection = "overview",
    steps: list[int] | None = None,
    offset: int = 0,
) -> CallToolResult:
    """Read the saved draft. The overview (default) is short: the flow's name,
    its run form fields and every step with what it reads and gives
    (input_source, input_type, output_mode, output_type), the fields its result
    declares (output_fields), whether a person reviews it, what it reads
    (reads: each earlier result as the reference the flow resolves and
    where the read is written), which later steps read its result (readers,
    the same way), the run form fields it reads and, for a Word step, its
    template (word_template: its id, null while the step waits for one) and
    the template's fields (word_fields: each field and what it reads, null
    when nothing does, and bindings_without_field). In edit mode it also
    gives each template's file name and lists the flow's Word templates
    (word_templates: id and file name). Section "steps" gives
    the steps in full with their assistants' prompts and the same reads;
    section "settings" the flow without its steps (description,
    metadata_json with the run form, retention, permissions); section "all"
    everything, paged; section "blockers" every publish blocker the draft
    has now, of which a change result lists the first. The overview and the settings also say what the
    flow's space offers for transcription, by name (transcription_offer:
    transcription_models, speaker_services). steps=[5, 8] limits the overview or the steps section
    to those step numbers (1 is first). A step marked unreadable has a
    configuration the flow cannot read; read it in full and fix it. Follow
    next_offset until it is null."""

    async def operation(container, chat, request):
        from eneo.flows.application.flow_authoring_operations import get_flow
        from eneo.flows.application.flow_authoring_reads import run_form_fields

        flow = await get_flow(chat.flow_id, request, container)
        if section == "all":
            value: Any = flow.model_dump(mode="json")
        elif section == "settings":
            value = flow.model_dump(mode="json", exclude={"steps"})
            offer = await _transcription_offer(container, chat.space_id)
            if offer is not None:
                value["transcription_offer"] = offer
        elif section == "blockers":
            blockers = await _publish_blockers(container, chat.flow_id)
            if blockers is None:
                raise BadRequestException(
                    "The publish blockers could not be read now; try again."
                )
            value = {
                "publish_blockers": blockers,
                "publish_blocker_count": len(blockers),
            }
        else:
            orders = {step.step_order for step in flow.steps}
            if steps is not None and (missing := sorted(set(steps) - orders)):
                raise BadRequestException(
                    f"No step {', '.join(map(str, missing))}; the flow has "
                    f"{len(orders)} step(s), numbered from 1."
                )
            chosen = [
                step for step in flow.steps if steps is None or step.step_order in steps
            ]
            reads, prompts = await _saved_reads(container, chat.flow_id)
            templates = await _readable_templates(container, chat)
            items: list[dict[str, Any]] = []
            for step in chosen:
                if section == "overview":
                    item = _step_overview(step)
                else:
                    item = step.model_dump(mode="json")
                    prompt = prompts.get(step.assistant_id)
                    item["prompt"] = prompt.text if prompt is not None else None
                item.update(_step_reads(step, reads, templates))
                items.append(item)
            value = {
                "name": flow.name,
                "published_version": flow.published_version,
                "steps": items,
            }
            if section == "overview":
                value["description"] = flow.description
                value["run_form_fields"] = run_form_fields(flow.metadata_json)
                if templates:
                    # Every template, so that one no step uses can be chosen;
                    # the pages carry a long list.
                    value["word_templates"] = [
                        {"id": template_id, "name": name}
                        for template_id, name in templates.items()
                    ]
                offer = await _transcription_offer(container, chat.space_id)
                if offer is not None:
                    value["transcription_offer"] = offer
        return page_result(
            value, flow_id=flow.id, offset=offset, revision=flow.draft_revision
        )

    return await _call(ctx, operation)


@_tool(_EDITS_DRAFT)
async def update_flow_settings(
    ctx: Context, expected_revision: int, changes: dict[str, Any]
) -> CallToolResult:
    """Change the flow's name, description or metadata_json; what changes
    leaves out keeps its saved value. metadata_json is merged into the saved
    one key by key: a top-level key you send replaces that key whole (send
    its full value, for example the whole form_schema), a key sent as null is
    removed, and keys you leave out are kept. To rename a run form field,
    send the new form_schema in metadata_json with form_field_renames
    ({"old name": "new name"}): the steps' reads of the field follow it. A
    field a step reads cannot be removed."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_models import FlowEditorUpdateRequest
        from eneo.flows.application.flow_authoring_operations import (
            apply_editor_update,
            get_flow,
        )

        if set(changes) - _SETTINGS_FIELDS:
            raise BadRequestException(
                "Only name, description, metadata_json and form_field_renames "
                "can be changed here."
            )
        definition = changes
        if isinstance(changes.get("metadata_json"), dict):
            saved = await get_flow(chat.flow_id, request, container)
            definition = _merged_settings(changes, saved.metadata_json)
        flow = await apply_editor_update(
            chat.flow_id,
            request,
            FlowEditorUpdateRequest.model_validate(
                {"expected_revision": expected_revision, "definition": definition}
            ),
            container,
            audit_context=_CHAT_AUDIT,
        )
        return page_result(
            {"saved": True}, flow_id=chat.flow_id, revision=flow.draft_revision
        )

    return await _call(ctx, operation, changes_draft=True)


@_tool(_READS)
async def read_step_assistant(
    ctx: Context, step_id: UUID, offset: int = 0
) -> CallToolResult:
    """Read the settings and prompt of one step's assistant, with explicit pagination."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_assistant_router import get_flow_assistant
        from eneo.flows.application.flow_authoring_operations import get_flow

        flow = await get_flow(chat.flow_id, request, container)
        step = next((item for item in flow.steps if item.id == step_id), None)
        if step is None:
            raise NotFoundException("Step not found.")
        assistant = await get_flow_assistant(
            id=chat.flow_id,
            assistant_id=step.assistant_id,
            request=request,
            container=container,
        )
        return page_result(
            assistant.model_dump(mode="json")
            if hasattr(assistant, "model_dump")
            else assistant,
            flow_id=chat.flow_id,
            offset=offset,
            revision=flow.draft_revision,
        )

    return await _call(ctx, operation)


def require_safe_model_configuration(
    changes: dict[str, Any], saved: dict[str, Any]
) -> None:
    """Never let a model send a credential or retarget a retained credential.

    The auth mode and the fields beside its secret (a header name, a username)
    are configuration the model writes; the token, key or password is entered
    in the editor. A config that declares a mode with its credential empty
    passes, one that carries a value or a stored credential's sentinel does
    not."""
    from eneo.flows.http_transport import (
        HTTP_CONFIG_KEYS,
        HttpAuthoredConfig,
        contains_secret_sentinel,
    )
    from eneo.flows.http_transport.authored_config import (
        HttpAuthApiKey,
        HttpAuthBasicAuth,
        HttpAuthBearer,
    )

    def present(value: Any) -> bool:
        return value not in (None, "", {}, [])

    def holds_credential(authored: HttpAuthoredConfig) -> bool:
        match authored.auth:
            case HttpAuthBearer(token=secret):
                pass
            case HttpAuthApiKey(key=secret):
                pass
            case HttpAuthBasicAuth(password=secret):
                pass
            case _:
                secret = ""
        return present(secret) or any(
            header.secret and present(header.value)
            for header in authored.custom_headers
        )

    def declares_credential(value: dict[str, Any]) -> bool:
        # Read without the core model, for configs it refuses: any auth field
        # besides the mode and its public companions, or a header with a value.
        auth = value.get("auth")
        if isinstance(auth, dict):
            if any(
                present(item)
                for key, item in auth.items()
                if key not in ("mode", "type", "header_name", "username")
            ):
                return True
        elif auth not in (None, "", "none"):
            return True
        headers = value.get("custom_headers")
        return isinstance(headers, list) and any(
            isinstance(header, dict) and present(header.get("value"))
            for header in headers
        )

    def contains_credential(value: Any) -> bool:
        if contains_secret_sentinel(value):
            return True
        if isinstance(value, dict):
            if "auth" in value or "custom_headers" in value:
                try:
                    authored = HttpAuthoredConfig.model_validate(
                        {
                            key: item
                            for key, item in value.items()
                            if key in HTTP_CONFIG_KEYS
                        }
                    )
                except ValidationError:
                    # A malformed config without credentials goes on to the
                    # core, whose refusal names the fields to fix.
                    if declares_credential(value):
                        return True
                else:
                    if holds_credential(authored):
                        return True
            return any(
                (
                    key.lower()
                    in {
                        "headers",
                        "credentials",
                        "password",
                        "token",
                        "api_key",
                        "authorization",
                    }
                    and present(item)
                )
                or contains_credential(item)
                for key, item in value.items()
            )
        return isinstance(value, list) and any(
            contains_credential(item) for item in value
        )

    for key in ("input_config", "output_config"):
        if key in changes and (
            contains_credential(changes[key]) or contains_credential(saved.get(key))
        ):
            raise BadRequestException(
                "A credential never passes the chat: declare the auth mode with its "
                "token, key or password left empty for the person to enter in the "
                "flow editor, and leave a configuration that holds a stored "
                "credential to the editor."
            )


@_tool(_EDITS_DRAFT, appendix=_INPUT_BINDINGS_SHAPE)
async def update_step(
    ctx: Context,
    expected_revision: int,
    step_id: UUID,
    changes: dict[str, Any],
    assistant_changes: dict[str, Any] | None = None,
) -> CallToolResult:
    """Patch one saved step and optionally its assistant in one revision. Use the flow's own
    field names; input_config and output_config are each replaced whole (long material:
    input_config.long_material), except that a Word step keeps its template when
    output_config leaves template_asset_id out: only output_config null removes
    it. Renaming the step (user_description) rewrites
    the reads of its old name in every step. When other steps share the step's
    assistant, the step gets its own copy with assistant_changes and the others
    keep theirs; the result names the step's assistant_id. assistant_changes
    takes the assistant's own fields, for example {"prompt": {"text": "Sammanfatta brevet."}};
    an instruction is always prompt.text. A change that reaches several steps
    goes in one update_steps call instead."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_models import FlowEditorUpdateRequest
        from eneo.flows.application.flow_authoring_operations import (
            apply_editor_update,
            get_flow,
        )

        flow = await get_flow(chat.flow_id, request, container)
        step = _saved_step(flow, step_id)
        before = await _assistant_before(
            container, request, chat.flow_id, step, assistant_changes
        )
        edit = await _step_edit(
            container, chat.flow_id, step, changes, assistant_changes, before
        )
        updated = await apply_editor_update(
            chat.flow_id,
            request,
            FlowEditorUpdateRequest.model_validate(
                {
                    "expected_revision": expected_revision,
                    "definition": {},
                    "step_edits": edit.step_edits,
                    "assistants": edit.assistants,
                }
            ),
            container,
            audit_context=_CHAT_AUDIT,
        )
        saved_step = next(item for item in updated.steps if item.id == step_id)
        return _change_result(
            {
                "saved": True,
                "step_id": str(step_id),
                "assistant_id": str(saved_step.assistant_id),
                "changes": edit.fields,
            },
            [_changed_step(saved_step, edit.card_fields)],
            flow_id=chat.flow_id,
            revision=updated.draft_revision,
        )

    return await _call(ctx, operation, changes_draft=True)


def _saved_step(flow: Any, step_id: UUID) -> Any:
    step = next((item for item in flow.steps if item.id == step_id), None)
    if step is None:
        raise NotFoundException("Step not found.")
    return step


async def _assistant_before(
    container, request, flow_id: UUID, step: Any, assistant_changes: Any
) -> dict[str, Any] | None:
    """The step's assistant as saved, read only when the change touches it,
    so the change can say what each field was."""
    if assistant_changes is None:
        return None
    from eneo.flows.api.flow_assistant_router import get_flow_assistant

    assistant = await get_flow_assistant(
        id=flow_id, assistant_id=step.assistant_id, request=request, container=container
    )
    return cast(
        dict[str, Any],
        assistant.model_dump(mode="json")
        if hasattr(assistant, "model_dump")
        else assistant,
    )


def _changed_step(saved_step: Any, fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "step_id": str(saved_step.id),
        "step_order": saved_step.step_order,
        "name": saved_step.user_description,
        "fields": fields,
    }


def _change_result(
    page: dict[str, Any],
    changed: list[dict[str, Any]],
    *,
    flow_id: UUID,
    revision: int,
) -> CallToolResult:
    """A change's page for the model, and the affected steps with each
    field's value before and after in the structured content, which the
    chat draws as a card and keeps with the conversation."""
    result = page_result(page, flow_id=flow_id, revision=revision)
    result.structuredContent = {
        "flow_id": str(flow_id),
        "draft_revision": revision,
        "changes": changed,
    }
    return result


class _StepEdit:
    """One step's part of an editor update, checked as update_step checks
    it: only configuration fields change, and no credential is sent or
    retargeted. ``fields`` is what the edit changes, each with its value
    before and after, for the model; ``card_fields`` the same for the
    chat's change card, which keeps more of each value."""

    def __init__(
        self,
        step_edits: list[dict[str, Any]],
        assistants: list[dict[str, Any]],
        fields: list[dict[str, Any]],
        card_fields: list[dict[str, Any]],
    ):
        self.step_edits = step_edits
        self.assistants = assistants
        self.fields = fields
        self.card_fields = card_fields


async def with_word_template(
    container, flow_id: UUID, changes: dict[str, Any], saved: dict[str, Any]
) -> dict[str, Any]:
    """``changes`` as they are saved on a Word step that has a template. A
    change replaces output_config whole and only the person uploads a
    template, so an output_config object that names no template (the
    bindings alone, say) keeps the saved one: the save refills the template's
    field names from its id and publish reads the rest. null removes the
    template on purpose, and so does another output_mode. Another template
    replaces the step's when the flow has it, and is refused otherwise."""
    from eneo.flows.flow_api_error_code import FlowApiErrorCode

    if (changes.get("output_mode") or saved.get("output_mode")) != "template_fill":
        return changes
    sent = changes.get("output_config")
    kept = _template_id(saved.get("output_config"))
    if not isinstance(sent, dict) or not kept:
        return changes
    named = _template_id(sent)
    if not named:
        return {**changes, "output_config": {**sent, "template_asset_id": kept}}
    if named != kept:
        templates = await _flow_templates(container, flow_id)
        if named not in templates:
            raise _Refused(
                "output_config names a Word template the flow does not have. To"
                " keep the step's template, leave template_asset_id out; to use"
                " another, name one of the flow's (templates); output_config"
                " null removes the template.",
                code=FlowApiErrorCode.TEMPLATE_NOT_ACCESSIBLE.value,
                templates=_listed_templates(templates),
            )
    return changes


async def _step_edit(
    container,
    flow_id: UUID,
    step: Any,
    changes: dict[str, Any] | None,
    assistant_changes: dict[str, Any] | None,
    assistant_before: dict[str, Any] | None = None,
) -> _StepEdit:
    from eneo.flows.api.flow_models import FlowStepUpdateRequest
    from eneo.flows.application.flow_authoring_reads import step_changes

    step_id = step.id
    changes = changes or {}
    if set(changes) - (
        set(FlowStepUpdateRequest.model_fields) - {"id", "assistant_id", "step_order"}
    ):
        raise BadRequestException(
            "Use a step configuration field; step identity and order cannot be changed here."
        )
    saved = step.model_dump(
        mode="json", include=set(FlowStepUpdateRequest.model_fields)
    )
    require_safe_model_configuration(changes, saved)
    changes = await with_word_template(container, flow_id, changes, saved)
    return _StepEdit(
        step_edits=[{"step_id": str(step_id), "changes": changes}] if changes else [],
        fields=step_changes(saved, changes, assistant_before, assistant_changes),
        card_fields=step_changes(
            saved, changes, assistant_before, assistant_changes, card=True
        ),
        assistants=(
            []
            if assistant_changes is None
            else [
                {
                    "assistant_id": str(step.assistant_id),
                    "step_id": str(step_id),
                    "changes": assistant_changes,
                }
            ]
        ),
    )


_SETTINGS_FIELDS = frozenset(
    {"name", "description", "metadata_json", "form_field_renames"}
)


def _merged_settings(
    settings: dict[str, Any], saved_metadata: Mapping[str, Any] | None
) -> dict[str, Any]:
    """``settings`` with its metadata_json laid over the saved metadata key by
    key: a top-level key sent replaces the saved key, a key sent as null
    removes it, and saved keys it leaves out are kept. The core replaces the
    saved metadata with the one an update sends, so a model that sends only
    the key it changes would otherwise drop the rest."""
    merged = dict(saved_metadata or {})
    for key, value in settings["metadata_json"].items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return {**settings, "metadata_json": merged}


@with_config(ConfigDict(extra="forbid"))
class StepEdit(TypedDict, total=False):
    """One saved step's part of update_steps; a part left out is unchanged."""

    step_id: Required[UUID]
    changes: Annotated[
        dict[str, Any],
        Field(description="The step's fields to change, as update_step takes them."),
    ]
    assistant_changes: Annotated[
        dict[str, Any],
        Field(description="The assistant's own fields, as update_step takes them."),
    ]


@_tool(_EDITS_DRAFT)
async def update_steps(
    ctx: Context,
    expected_revision: int,
    edits: Annotated[
        list[dict[str, Any]],
        WithJsonSchema({"type": "array", "items": _closed_schema(StepEdit)}),
    ],
    settings: dict[str, Any] | None = None,
) -> CallToolResult:
    """Change several saved steps, and optionally the flow's settings, in one
    revision: everything is saved or nothing. Each edit is {"step_id": ...,
    "changes": {...}, "assistant_changes": {...}} with the fields update_step
    takes (either part may be left out); a step appears once. settings takes
    what update_flow_settings takes, its metadata_json merged into the saved
    one key by key the same way. Use it when one change reaches several
    steps: when a step's result changes, the steps that read it (readers in
    read_flow) get their new instructions in the same call, so the flow is
    never saved half-changed. A refusal names what to fix and saves nothing.
    The result lists the saved steps with their assistant ids."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_models import FlowEditorUpdateRequest
        from eneo.flows.application.flow_authoring_operations import (
            apply_editor_update,
            get_flow,
        )

        if not edits and not settings:
            raise BadRequestException("Send at least one edit or a settings change.")
        if settings and set(settings) - _SETTINGS_FIELDS:
            raise BadRequestException(
                "Only name, description, metadata_json and form_field_renames "
                "can be changed in settings."
            )
        flow = await get_flow(chat.flow_id, request, container)
        step_edits: list[dict[str, Any]] = []
        assistants: list[dict[str, Any]] = []
        edited: list[UUID] = []
        fields: dict[UUID, list[dict[str, Any]]] = {}
        card_fields: dict[UUID, list[dict[str, Any]]] = {}
        for edit in edits:
            if set(edit) - {"step_id", "changes", "assistant_changes"}:
                raise BadRequestException(
                    "An edit has step_id, changes and assistant_changes only."
                )
            try:
                step_id = UUID(str(edit.get("step_id")))
            except ValueError:
                raise BadRequestException("Each edit needs a step_id.") from None
            if step_id in edited:
                raise BadRequestException("A step appears once per call.")
            if not edit.get("changes") and edit.get("assistant_changes") is None:
                raise BadRequestException(
                    f"The edit of step {step_id} changes nothing."
                )
            step = _saved_step(flow, step_id)
            before = await _assistant_before(
                container, request, chat.flow_id, step, edit.get("assistant_changes")
            )
            part = await _step_edit(
                container,
                chat.flow_id,
                step,
                edit.get("changes"),
                edit.get("assistant_changes"),
                before,
            )
            step_edits.extend(part.step_edits)
            assistants.extend(part.assistants)
            edited.append(step_id)
            fields[step_id] = part.fields
            card_fields[step_id] = part.card_fields
        definition = settings or {}
        if isinstance(definition.get("metadata_json"), dict):
            definition = _merged_settings(definition, flow.metadata_json)
        updated = await apply_editor_update(
            chat.flow_id,
            request,
            FlowEditorUpdateRequest.model_validate(
                {
                    "expected_revision": expected_revision,
                    "definition": definition,
                    "step_edits": step_edits,
                    "assistants": assistants,
                }
            ),
            container,
            audit_context=_CHAT_AUDIT,
        )
        by_id = {step.id: step for step in updated.steps}
        return _change_result(
            {
                "saved": True,
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": by_id[step_id].step_order,
                        "name": by_id[step_id].user_description,
                        "assistant_id": str(by_id[step_id].assistant_id),
                        "changes": fields[step_id],
                    }
                    for step_id in edited
                ],
            },
            [_changed_step(by_id[step_id], card_fields[step_id]) for step_id in edited],
            flow_id=chat.flow_id,
            revision=updated.draft_revision,
        )

    return await _call(ctx, operation, changes_draft=True)


_EXAMPLE_PROBLEMS = {
    "syntax": "The example is not valid JSON.",
    "not_object": "The example must be a JSON object with the fields the step gives.",
    "no_fields": "The example has no fields.",
    "inexact_number": (
        "A number in the example cannot be held exactly; round it or write it as text."
    ),
    "too_large": "The example is too large; keep it to the fields the step gives.",
}


@_tool(_EDITS_DRAFT)
async def contract_from_example(
    ctx: Context, expected_revision: int, step_id: UUID, example: str
) -> CallToolResult:
    """Give a step the output contract one example of its answer implies, the way
    the editor's "Skapa från exempel" does: example is a JSON object whose keys
    become required fields typed by their values (numbers as number, lists by
    their first element). Saves output_type json and the contract on the step;
    the example itself is not kept. The result lists the fields, marks a name a
    later step cannot read as a reference (variable false) and a field a Word
    field cannot read (word false: a list, an object or a null), and notes what
    one example could not decide (an empty list, a null, a list of mixed
    elements)."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_models import FlowEditorUpdateRequest
        from eneo.flows.application.flow_authoring_operations import (
            apply_editor_update,
            get_flow,
        )
        from eneo.flows.domain.contract_from_example import (
            ExampleProblemError,
        )
        from eneo.flows.domain.contract_from_example import (
            contract_from_example as read_example,
        )
        from eneo.flows.flow_validators import template_bound_path_ok

        try:
            reading = read_example(example)
        except ExampleProblemError as error:
            raise BadRequestException(_EXAMPLE_PROBLEMS[error.problem]) from error
        flow = await get_flow(chat.flow_id, request, container)
        edit = await _step_edit(
            container,
            chat.flow_id,
            _saved_step(flow, step_id),
            {"output_type": "json", "output_contract": reading.contract},
            None,
        )
        updated = await apply_editor_update(
            chat.flow_id,
            request,
            FlowEditorUpdateRequest.model_validate(
                {
                    "expected_revision": expected_revision,
                    "definition": {},
                    "step_edits": edit.step_edits,
                    "assistants": [],
                }
            ),
            container,
            audit_context=_CHAT_AUDIT,
        )
        return page_result(
            {
                "saved": True,
                "step_id": str(step_id),
                "fields": [
                    {
                        "name": item.name,
                        "type": item.schema.get("type"),
                        "variable": item.variable,
                        # Publish's rule for what a Word field may read: a
                        # field it can name, of one required primitive type.
                        "word": item.variable
                        and template_bound_path_ok(reading.contract, (item.name,)),
                    }
                    for item in reading.fields
                ],
                "notes": list(reading.notes),
            },
            flow_id=chat.flow_id,
            revision=updated.draft_revision,
        )

    return await _call(ctx, operation, changes_draft=True)


def _kinds_appendix() -> str:
    """Each kind, what it does and the values it takes, from their owner."""

    def takes(kind: FlowStepKind) -> str:
        required, optional = step_kind_value_names(kind)
        parts = [f"needs {', '.join(required)}"] if required else []
        if optional:
            parts.append(f"may take {', '.join(optional)}")
        return "; ".join(parts) or "takes no values"

    return (
        "\nThe kinds: "
        + "; ".join(
            f"{kind.value} ({text}): {takes(kind)}"
            for kind, text in STEP_KIND_DESCRIPTIONS.items()
        )
        + "."
    )


@_tool(_EDITS_DRAFT, appendix=_kinds_appendix(), closed=True)
async def add_step(
    ctx: Context,
    expected_revision: int,
    name: str,
    kind: FlowStepKind,
    values: Annotated[
        dict[str, Any] | None,
        WithJsonSchema({"anyOf": [_closed_schema(StepKindValues), {"type": "null"}]}),
    ] = None,
    position: int | None = None,
    settings: dict[str, Any] | None = None,
) -> CallToolResult:
    """Add one step of a kind with a new assistant, in one revision: last, or
    at `position` (1 is first). The flow builds the step for its place: a
    step put first reads the run's input, and the step that was first then
    reads the new step (hand_over in the result); the steps after it keep
    their reads. values takes what the kind needs and nothing else, and a
    value the kind does not use is refused; instruction is the step's
    instruction to its model. read_step_kinds says which kinds may stand at a
    place and why the others may not. settings takes what
    update_flow_settings takes and is saved in the same revision, so a step
    that reads a run form field is added together with the field (the whole
    form_schema in metadata_json); everything is saved or nothing. A
    send_http step needs its url: ask for the address before adding it. A
    saved step is changed with update_step, never by a kind."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_definition_access import (
            require_flow_current_definition_access,
        )
        from eneo.flows.application.flow_authoring_operations import (
            apply_editor_update,
        )
        from eneo.flows.application.flow_step_kinds import (
            editor_update,
            insertion_change,
        )
        from eneo.flows.domain.contract_from_example import ExampleProblemError
        from eneo.flows.domain.step_kinds import check_step_kind_values

        if settings and set(settings) - _SETTINGS_FIELDS:
            raise BadRequestException(
                "Only name, description, metadata_json and form_field_renames "
                "can be changed in settings."
            )
        step_kind = FlowStepKind(kind)
        try:
            chosen = StepKindValues.model_validate(values or {})
        except ValidationError as error:
            # Where each value was wrong and what it takes, never what was sent.
            errors = error.errors(include_input=False, include_context=False)
            raise _Refused(
                f"{invalid_message(errors)} {step_kind_takes(step_kind)}",
                code="flow_step_kind_values_invalid",
                errors=errors[:MAX_LISTED],
            ) from None
        check_step_kind_values(step_kind, chosen)
        templates: dict[str, str] = {}
        if step_kind is FlowStepKind.TEMPLATE:
            templates = await _flow_templates(container, chat.flow_id)
            chosen = _word_step_values(chosen, templates)
        flow = (
            await require_flow_current_definition_access(
                request, container, flow_id=chat.flow_id
            )
        ).flow
        places = len(flow.steps) + 1
        place = places if position is None else _index_at(position, places) + 1
        try:
            change = insertion_change(flow, step_kind, position=place, values=chosen)
        except ExampleProblemError as error:
            raise BadRequestException(_EXAMPLE_PROBLEMS[error.problem]) from error
        require_safe_model_configuration(change.configuration, {})
        definition = settings or {}
        if isinstance(definition.get("metadata_json"), dict):
            definition = _merged_settings(definition, flow.metadata_json)
        updated = await apply_editor_update(
            chat.flow_id,
            request,
            editor_update(
                flow,
                change,
                expected_revision=expected_revision,
                position=place,
                name=name,
                assistant=(
                    {"prompt": {"text": chosen.instruction}}
                    if chosen.instruction
                    else None
                ),
                definition=definition,
            ),
            container,
            audit_context=_CHAT_AUDIT,
        )
        by_id = {step.id: step for step in updated.steps}
        added = next(step for step in updated.steps if step.step_order == place)
        reads, _prompts = await _saved_reads(container, chat.flow_id)
        return page_result(
            _addition_receipt(
                added,
                _step_overview(added) | _step_reads(added, reads, templates),
                [
                    {
                        "step_id": str(step_id),
                        "step_order": by_id[step_id].step_order,
                        "name": _cut(by_id[step_id].user_description),
                        "changes": changes,
                    }
                    for step_id, changes in change.step_edits
                ],
            ),
            flow_id=chat.flow_id,
            revision=updated.draft_revision,
        )

    return await _call(ctx, operation, changes_draft=True)


def _word_step_values(
    values: StepKindValues, templates: dict[str, str]
) -> StepKindValues:
    """A new Word step's values with its template settled, in a flow that has
    ``templates``: the template the step names, else the flow's only one.
    With several the step must say which; with none it is saved and waits for
    the person's upload. Its bindings are an object either way, so what then
    blocks publishing is the missing template itself."""
    template_id = values.template_asset_id
    if template_id is None and len(templates) > 1:
        raise _Refused(
            f"The flow has {len(templates)} Word templates: say which one the"
            " step fills with template_asset_id (templates).",
            code="flow_step_kind_values_invalid",
            templates=_listed_templates(templates),
        )
    if template_id is None and templates:
        template_id = UUID(next(iter(templates)))
    return values.model_copy(
        update={"template_asset_id": template_id, "bindings": values.bindings or {}}
    )


# What the answer to an addition says of the step when its details do not fit:
# each of fixed size, a Word step's template with its file name cut short.
_RECEIPT_STEP_FIELDS = (
    "step_order",
    "input_source",
    "input_type",
    "output_mode",
    "output_type",
    "review",
    "word_template",
)


def _addition_receipt(
    added: Any, details: dict[str, Any], hand_over: list[dict[str, Any]]
) -> dict[str, Any]:
    """What add_step answers with, whole in one page: a change cannot be read
    on from an offset. That the step was saved, its id and each step it took
    over from (id, order and changes, all of fixed size; an addition hands
    over from one step at most) are always there. What is only shown gives
    way until the answer fits a page: the step's details as the overview
    gives them and the names of the steps it took over from, cut short; else
    the step in short, of fixed size, and where to read it in full; else, on
    a page too small for that, neither the step in short nor the names."""
    receipt = {
        "saved": True,
        "step_id": str(added.id),
        "step": details,
        "hand_over": hand_over,
    }
    short = {
        **receipt,
        "step": {key: details[key] for key in _RECEIPT_STEP_FIELDS if key in details},
        "in_full": f"read_flow steps=[{added.step_order}] gives the step in full.",
    }
    bare = {
        "saved": True,
        "step_id": str(added.id),
        "hand_over": [
            {key: value for key, value in step.items() if key != "name"}
            for step in hand_over
        ],
        "in_full": short["in_full"],
    }
    return next(
        (
            shape
            for shape in (receipt, short)
            if len(_serialized(shape)) <= _page_size()
        ),
        bare,
    )


_STEP_KINDS_NOTE = (
    "This judges the place and the flow's structure with each kind's own "
    "configuration. The values add_step is given (an upload, reads, a review, "
    "a format) and what the space and the organisation allow (models, "
    "security classification, the transcription service, the real address of "
    "an HTTP step) are checked when the step is saved."
)


@_tool(_READS)
async def read_step_kinds(
    ctx: Context, position: int | None = None, offset: int = 0
) -> CallToolResult:
    """Read which kinds of step may stand at a place of the draft: `position`
    (1 is first), after the last step when left out. For each kind: allowed,
    or the refusals (code and message) the save would give it there; the
    values it needs and may take; the output_type it gives; review true when
    a person reviews it; and hand_over, the saved steps (by their order after
    the addition) adding it there would also change. Allowed is not yet
    saved: see the note. Follow next_offset until it is null."""

    async def operation(container, chat, request):
        import asyncio

        from eneo.flows.api.flow_definition_access import (
            require_flow_current_definition_access,
        )
        from eneo.flows.application.flow_step_kinds import step_kind_answer
        from eneo.flows.enums import FlowOutputType

        flow = (
            await require_flow_current_definition_access(
                request, container, flow_id=chat.flow_id
            )
        ).flow
        places = len(flow.steps) + 1
        place = places if position is None else _index_at(position, places) + 1
        stored = await container.flow_service().get_flow_assistant_prompts(flow)
        # Each kind judges the whole draft; off the event loop as the
        # editor's own read does.
        answer = await asyncio.to_thread(
            step_kind_answer,
            flow,
            prompts={
                assistant_id: prompt.text for assistant_id, prompt in stored.items()
            },
            positions=[place],
            step_ids=[],
        )
        orders = {step.id: step.step_order for step in flow.steps}
        kinds: list[dict[str, Any]] = []
        for option in answer.insertions[0].options:
            configuration = option.change.configuration
            item: dict[str, Any] = {
                "kind": option.kind.value,
                "allowed": option.allowed,
            }
            if not option.allowed:
                item["refusals"] = [
                    {
                        "code": refusal.issue_code or refusal.code,
                        "message": refusal.message,
                    }
                    for refusal in option.refusals
                ]
            required, optional = step_kind_value_names(option.kind)
            if required:
                item["needs"] = required
            if optional:
                item["may_take"] = optional
            item["gives"] = FlowOutputType(configuration["output_type"]).value
            if configuration["review_policy"] is not None:
                item["review"] = True
            if option.change.step_edits:
                item["hand_over"] = [
                    # Numbered as after the step is added before it.
                    {"step_order": orders[step_id] + 1, "changes": changes}
                    for step_id, changes in option.change.step_edits
                ]
            kinds.append(item)
        return page_result(
            {"position": place, "kinds": kinds, "note": _STEP_KINDS_NOTE},
            flow_id=chat.flow_id,
            offset=offset,
            revision=flow.draft_revision,
        )

    return await _call(ctx, operation)


@_tool(_EDITS_DRAFT)
async def move_step(
    ctx: Context, expected_revision: int, step_id: UUID, position: int
) -> CallToolResult:
    """Move a saved step to `position` (1 is first). Reads of moved steps
    follow them; a move that leaves a step before a step it reads is refused."""

    async def operation(container, chat, request):
        from eneo.flows.application.flow_authoring_operations import get_flow

        flow = await get_flow(chat.flow_id, request, container)
        ids = [step.id for step in flow.steps]
        if step_id not in ids:
            raise NotFoundException("Step not found.")
        ids.remove(step_id)
        ids.insert(_index_at(position, len(ids) + 1), step_id)
        return await _save_order(container, chat, request, expected_revision, ids)

    return await _call(ctx, operation, changes_draft=True)


@_tool(_EDITS_DRAFT)
async def remove_step(
    ctx: Context, expected_revision: int, step_id: UUID
) -> CallToolResult:
    """Remove a saved step and its managed assistant. Refused while another
    step still reads it: ask the user what that read should use instead
    rather than emptying it to get the removal through."""

    async def operation(container, chat, request):
        from eneo.flows.application.flow_authoring_operations import get_flow

        flow = await get_flow(chat.flow_id, request, container)
        ids = [step.id for step in flow.steps]
        if step_id not in ids:
            raise NotFoundException("Step not found.")
        ids.remove(step_id)
        return await _save_order(container, chat, request, expected_revision, ids)

    return await _call(ctx, operation, changes_draft=True)


def _index_at(position: int, places: int) -> int:
    if not 1 <= position <= places:
        raise BadRequestException(f"position must be between 1 and {places}.")
    return position - 1


async def _save_order(container, chat, request, expected_revision, ids):
    from eneo.flows.api.flow_models import FlowEditorUpdateRequest
    from eneo.flows.application.flow_authoring_operations import apply_editor_update

    updated = await apply_editor_update(
        chat.flow_id,
        request,
        FlowEditorUpdateRequest.model_validate(
            {
                "expected_revision": expected_revision,
                "definition": {},
                "step_order": [{"step_id": str(step_id)} for step_id in ids],
            }
        ),
        container,
        audit_context=_CHAT_AUDIT,
    )
    return page_result(
        {
            "saved": True,
            "steps": [
                {"step_id": str(step.id), "step_order": step.step_order}
                for step in updated.steps
            ],
        },
        flow_id=chat.flow_id,
        revision=updated.draft_revision,
    )


@_tool(_ACTS)
async def publish_flow(ctx: Context, expected_revision: int) -> CallToolResult:
    """Publish the current revision after the user explicitly requests
    publication. The person confirms it in the chat before it happens; a
    denied call published nothing, so do not repeat it unless asked again."""

    async def operation(container, chat, request):
        from eneo.flows.application.flow_authoring_operations import (
            publish_flow as publish,
        )

        flow = await publish(
            chat.flow_id, request, container, expected_revision=expected_revision
        )
        return page_result(
            {"published_version": flow.published_version},
            flow_id=chat.flow_id,
            revision=flow.draft_revision,
        )

    return await _call(ctx, operation, editing=True)


@_tool(_READS)
async def read_tool_options(ctx: Context, offset: int = 0) -> CallToolResult:
    """Read the MCP tools a tool step may call unattended, and why others are
    refused, with pagination. It says nothing about HTTP steps: http_get and
    http_post need no tool option; their destination is checked when
    the step is saved and run."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_tool_options_router import list_flow_tool_options

        options = await list_flow_tool_options(
            id=chat.flow_id, request=request, container=container
        )
        return page_result(
            options.model_dump(mode="json"), flow_id=chat.flow_id, offset=offset
        )

    return await _call(ctx, operation)


@_tool(_READS)
async def read_flow_suggestions(
    ctx: Context, include_runs: bool = False, offset: int = 0
) -> CallToolResult:
    """Read what the saved draft could do cheaper or simpler, with pagination:
    where a step's model receives the same earlier result twice
    (duplicate_read), takes more than it needs, carries data no step reads,
    or relays a result. Each item names its steps, the reads, an impact and
    how it is acted on (fix.kind). By default it reports only what the
    definition proves: the reads publish and the runtime resolve, no
    judgement of prompt text, no run content. With include_runs it also
    measures the last 10 finished runs the user may see (impact.basis runs:
    tokens_per_run, run_count, version, step_changed_since) and reports the
    findings only runs show (identical_inputs, context_headroom,
    format_fallback), and from what the worker measured of each model call:
    model_relay (a model step copies an earlier result into its output and a
    later step reads it from there instead of the original),
    overlapping_inputs (two inputs of a step share much of their text; when
    a duplicate_read or broad_all_previous_steps names the same two reads,
    the overlap is in its params.measured_overlaps instead) and
    deterministic_candidate (the runs show that most of the step's output was
    its input copied; a step without a model is worth trying when the step's
    own part is not needed), and oversized_reasoning (a step
    asks for high reasoning effort for a small extraction into JSON);
    runs.counted and runs.left_out say how many runs were measured. Only
    numbers come from the runs, never their content, and the read is
    audited. It needs the permission to view flow traces: without it the
    result is the definition alone and its note says why. Suggestions an
    editor of the flow dismissed are left out; dismissed_count says how
    many. Suggestions never block publishing and the tool changes nothing: a
    fix the user agrees to is made with apply_flow_suggestions when its
    fix.kind is patch, otherwise with update_step, both in edit mode. Works
    in view mode."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_suggestions_router import (
            read_flow_suggestions_answer,
        )
        from eneo.flows.flow_access_policy import (
            FlowApiAction,
            user_can_perform_flow_action,
        )

        runs = 0
        note = None
        if include_runs:
            if user_can_perform_flow_action(container.user(), FlowApiAction.TRACE_VIEW):
                runs = MCP_MEASURED_RUNS
            else:
                note = _NO_TRACE_NOTE
        suggestions = await read_flow_suggestions_answer(
            id=chat.flow_id, request=request, runs=runs, container=container
        )
        value = suggestions.model_dump(mode="json")
        if note is not None:
            value["note"] = note
        return page_result(
            value,
            flow_id=chat.flow_id,
            offset=offset,
            revision=suggestions.draft_revision,
        )

    return await _call(ctx, operation)


# How many runs ``read_flow_suggestions`` measures with ``include_runs``.
MCP_MEASURED_RUNS = 10
_NO_TRACE_NOTE = (
    "Numbers from past runs were not read: they need the permission to view "
    "flow traces, which this user does not have. These suggestions are from "
    "the definition alone."
)


@_tool(_EDITS_DRAFT)
async def apply_flow_suggestions(
    ctx: Context, fingerprints: list[str], expected_revision: int
) -> CallToolResult:
    """Apply the fixes of suggestions read_flow_suggestions reported, after the
    user agreed to them: only suggestions whose fix.kind is patch, named by
    fingerprint, with the draft_revision of that answer. All of them are
    applied or none; one call for every fix the user agreed to. Refused with
    flow_suggestion_stale when the draft no longer has one of them (read the
    suggestions again) and flow_suggestion_not_patchable for any other fix
    kind: propose that change and make it with update_step. The result lists
    the fingerprints applied, those an earlier fix of the call resolved
    (skipped) and the new draft_revision."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_suggestion_apply_models import (
            FlowSuggestionsApplyRequest,
        )
        from eneo.flows.application.flow_suggestion_apply import (
            apply_flow_suggestions as apply,
        )

        body = FlowSuggestionsApplyRequest.model_validate(
            {"fingerprints": fingerprints, "expected_revision": expected_revision}
        )
        result = await apply(
            chat.flow_id,
            request,
            fingerprints=body.fingerprints,
            expected_revision=body.expected_revision,
            container=container,
        )
        return page_result(
            {
                "saved": True,
                "applied": list(result.applied),
                "skipped": list(result.skipped),
            },
            flow_id=chat.flow_id,
            revision=result.flow.draft_revision,
        )

    return await _call(ctx, operation, changes_draft=True)


@_tool(_EDITS_DRAFT)
async def dismiss_flow_suggestion(
    ctx: Context, fingerprint: str, code: str
) -> CallToolResult:
    """Hide one suggestion read_flow_suggestions reported, named by its
    fingerprint and code, only when the user asks to hide or ignore that
    suggestion; never on your own judgement. The suggestion is then left out
    for everyone who edits this flow until a change to the draft changes
    what it is about. It changes nothing of the flow itself. A suggestion
    from the definition is refused with flow_suggestion_stale when the draft
    no longer has it (read the suggestions again). Dismissing one again
    changes nothing. Edit mode only."""

    async def operation(container, chat, request):
        from pydantic import TypeAdapter

        from eneo.flows.api.flow_suggestion_dismissal_models import (
            FlowSuggestionDismissalRequest,
            SuggestionFingerprint,
        )
        from eneo.flows.application.flow_suggestion_dismissals import (
            dismiss_flow_suggestion as dismiss,
        )

        body = FlowSuggestionDismissalRequest.model_validate({"code": code})
        dismissal = await dismiss(
            chat.flow_id,
            request,
            fingerprint=TypeAdapter(SuggestionFingerprint).validate_python(fingerprint),
            code=body.code,
            container=container,
        )
        return page_result(
            {
                "dismissed": True,
                "fingerprint": dismissal.fingerprint,
                "code": dismissal.code,
            },
            flow_id=chat.flow_id,
        )

    return await _call(ctx, operation, editing=True)


@_tool(_ACTS)
async def run_flow(
    ctx: Context,
    expected_flow_version: int,
    idempotency_key: str,
    inputs: dict[str, Any],
    step_inputs: dict[str, Any] | None = None,
) -> CallToolResult:
    """Start a published flow only when asked. Reuse idempotency_key after an
    uncertain response. The person confirms the run in the chat before it
    starts; a denied call started nothing, so do not repeat it unless asked
    again."""

    async def operation(container, chat, request):
        from fastapi import BackgroundTasks

        from eneo.flows.api.flow_models import FlowRunCreateRequest
        from eneo.flows.api.flow_run_lifecycle_router import create_flow_run

        body = FlowRunCreateRequest.model_validate(
            {
                "expected_flow_version": expected_flow_version,
                "input_payload_json": inputs,
                "step_inputs": step_inputs,
            }
        )
        tasks = BackgroundTasks()
        result = await create_flow_run(
            id=chat.flow_id,
            request=request,
            run_in=body,
            background_tasks=tasks,
            idempotency_key=idempotency_key,
            container=container,
        )
        # The core has committed its run/outbox before this existing dispatch.
        # FastAPI normally drains these tasks after the response; MCP must do it.
        await tasks()
        return _runtime_result(result, flow_id=chat.flow_id)

    return await _call_runtime(ctx, operation)


@_tool(_ACTS)
async def retry_run(ctx: Context, run_id: UUID, idempotency_key: str) -> CallToolResult:
    """Start a failed run again from its failed step, on the same flow version
    with the same inputs, keeping the steps that completed before it. Only
    after the person has agreed, and only for a transient error (the run's
    error is retryable); a setting error is fixed in the flow instead.
    Refused when the run did not fail, when its version is no longer
    published, or when no step completed before the failure. Reuse
    idempotency_key after an uncertain response: the same key returns the
    run it already started. The person confirms the retry in the chat first;
    a denied call started nothing."""

    async def operation(container, chat, request):
        from fastapi import BackgroundTasks
        from starlette.responses import Response

        from eneo.flows.api.flow_run_retry_router import (
            retry_flow_run_from_failed_step,
        )

        tasks = BackgroundTasks()
        result = await retry_flow_run_from_failed_step(
            id=chat.flow_id,
            run_id=run_id,
            request=request,
            response=Response(),
            background_tasks=tasks,
            idempotency_key=idempotency_key,
            container=container,
        )
        # The core has committed the run before this dispatch; MCP drains
        # the tasks FastAPI would drain after the response.
        await tasks()
        page = _runtime_result(result, flow_id=chat.flow_id)
        if not isinstance(result, Response):
            # The new run, for the chat's run card.
            page.structuredContent = {
                "flow_id": str(chat.flow_id),
                "run_id": str(result.run.id),
                "source_run_id": str(result.source_run_id),
                "created": result.created,
            }
        return page

    return await _call_runtime(ctx, operation)


RunSection = Literal["summary", "all"]


@_tool(_READS)
async def read_run(
    ctx: Context, run_id: UUID, section: RunSection = "summary", offset: int = 0
) -> CallToolResult:
    """Read a run of this flow. The summary (the default) gives the run's
    status, timing, tokens, error and result in short, and each step in one
    line: its status, duration, tokens, whether its prompt was cut, its
    long-material coverage, its diagnostics, its error and its review's
    outcome, so you can say which step costs or failed and why; open_review
    names a review still waiting for a decision and whether its result can
    be edited. Section "all" pages the whole run detail. Both are audited
    evidence reads."""

    async def operation(container, chat, request):
        from starlette.responses import Response

        from eneo.flows.api.flow_run_lifecycle_router import get_flow_run

        result = await get_flow_run(
            id=chat.flow_id, run_id=run_id, request=request, container=container
        )
        if section == "all" or isinstance(result, Response):
            return _runtime_result(result, flow_id=chat.flow_id, offset=offset)
        from eneo.flows.api.flow_run_steps_router import (
            get_flow_graph,
            list_flow_run_steps,
        )
        from eneo.flows.application.flow_authoring_reads import run_summary

        steps = await list_flow_run_steps(
            id=chat.flow_id, run_id=run_id, request=request, container=container
        )
        # The graph and checkpoint reads run on the chat's session, which does
        # not begin a transaction by itself as a request's session does.
        async with container.session().begin():
            graph = await get_flow_graph(
                id=chat.flow_id, request=request, run_id=run_id, container=container
            )
            checkpoints = await container.flow_run_review_checkpoint_repo().list_review_checkpoints_for_run(
                run_id=run_id, tenant_id=container.user().tenant_id
            )
        labels = {
            node.step_order: node.label
            for node in graph.nodes
            if node.step_order is not None
        }
        page = page_result(
            run_summary(result, steps, labels, checkpoints),
            flow_id=chat.flow_id,
            offset=offset,
        )
        page.structuredContent = {"flow_id": str(chat.flow_id), "run_id": str(run_id)}
        return page

    return await _call_runtime(ctx, operation)


@_tool(_ACTS)
async def cancel_run(ctx: Context, run_id: UUID) -> CallToolResult:
    """Cancel a run of this flow only when the user asks to cancel it. The
    person confirms it in the chat first; a denied call cancelled nothing."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_run_lifecycle_router import cancel_flow_run

        return _runtime_result(
            await cancel_flow_run(
                id=chat.flow_id, run_id=run_id, request=request, container=container
            ),
            flow_id=chat.flow_id,
        )

    return await _call_runtime(ctx, operation)


@_tool(_READS)
async def read_review(ctx: Context, run_id: UUID, offset: int = 0) -> CallToolResult:
    """Read the active review and its revision before proposing a review decision."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_run_review_router import (
            get_active_flow_run_review_checkpoint,
        )

        result = await get_active_flow_run_review_checkpoint(
            id=chat.flow_id, run_id=run_id, request=request, container=container
        )
        return _runtime_result(result, flow_id=chat.flow_id, offset=offset)

    return await _call_runtime(ctx, operation)


@_tool(_ACTS)
async def review_run(
    ctx: Context,
    run_id: UUID,
    checkpoint_id: UUID,
    expected_checkpoint_revision: int,
    action: Literal["approve", "reject", "edit", "resume", "approve_and_continue"],
    changes: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> CallToolResult:
    """Apply an explicitly requested review action using the current
    checkpoint revision. changes holds edited_value or rejection reason. The
    person confirms the decision in the chat first; a denied call decided
    nothing."""

    async def operation(container, chat, request):
        from fastapi import BackgroundTasks

        from eneo.flows.api import flow_run_review_router as review
        from eneo.flows.api.flow_models import (
            FlowRunReviewCheckpointApproveRequest,
            FlowRunReviewCheckpointEditRequest,
            FlowRunReviewCheckpointRejectRequest,
            FlowRunReviewCheckpointResumeRequest,
        )

        requests = {
            "approve": FlowRunReviewCheckpointApproveRequest,
            "reject": FlowRunReviewCheckpointRejectRequest,
            "edit": FlowRunReviewCheckpointEditRequest,
            "resume": FlowRunReviewCheckpointResumeRequest,
            "approve_and_continue": FlowRunReviewCheckpointApproveRequest,
        }
        handlers = {
            "approve": review.approve_flow_run_review_checkpoint,
            "reject": review.reject_flow_run_review_checkpoint,
            "edit": review.edit_flow_run_review_checkpoint,
            "resume": review.resume_flow_run_review_checkpoint,
            "approve_and_continue": review.approve_and_continue_flow_run_review_checkpoint,
        }
        body = requests[action].model_validate(
            {
                **(changes or {}),
                "expected_checkpoint_revision": expected_checkpoint_revision,
            }
        )
        kwargs: dict[str, Any] = dict(
            id=chat.flow_id,
            run_id=run_id,
            checkpoint_id=checkpoint_id,
            request=request,
            review_in=body,
            container=container,
        )
        tasks = BackgroundTasks()
        if action in {"resume", "approve_and_continue"}:
            if not idempotency_key:
                raise BadRequestException(
                    "A stable idempotency_key is required when resuming a run."
                )
            kwargs.update(background_tasks=tasks, idempotency_key=idempotency_key)
        result = await handlers[action](**kwargs)
        await tasks()
        return _runtime_result(result, flow_id=chat.flow_id)

    return await _call_runtime(ctx, operation)


EDIT_MODE_TOOLS = frozenset(
    {
        "update_flow_settings",
        "update_step",
        "update_steps",
        "contract_from_example",
        "add_step",
        "move_step",
        "remove_step",
        "publish_flow",
        "apply_flow_suggestions",
        "dismiss_flow_suggestion",
    }
)
"""The tools ``_call`` refuses outside edit mode. A turn in Fråga mode does not
offer them, so the model never calls what would be refused."""


async def build_flows_mcp_server(*, token: str, tenant_id: UUID, editing: bool = True):
    """The flows server for one turn: every tool in edit mode, the reading and
    run tools alone while the chat only asks."""
    return await build_ephemeral_server(
        mcp,
        name=FLOWS_SERVER_NAME,
        description="Configure the flow bound to this chat.",
        token=token,
        tenant_id=tenant_id,
        exclude_tools=() if editing else EDIT_MODE_TOOLS,
    )
