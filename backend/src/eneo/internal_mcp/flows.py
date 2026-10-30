# pyright: basic
"""Thin session-bound tools over the adopted flow core's authorized operations."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Literal, cast
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

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
    instructions="""Configure the flow bound to this chat. Tools cannot be pointed at another flow.
Read the current saved revision and configuration before editing; use that revision
on every change. Keep unchanged fields. Every change goes through the flow's own
validation, permissions, classification and audit. The tools that change the flow
are offered only while the chat is in edit mode (Redigera); when they are absent,
say what you would change and that the person can switch the mode beside the send
button.
read_flow's overview (the default) lists every step in short with what it reads and
which later steps read it; section "steps" with steps=[...] gives those steps in
full with their prompts, section "settings" the flow without its steps. Read a step
in full before changing it. A change that reaches several steps goes in one
update_steps call.
Read pages until next_offset is null before claiming you reviewed the whole value.
Credentials belong in the editor and must never be requested or placed in tools.
A completion step whose input may exceed its model's window can set
input_config.long_material = {"mode": "digest"}: such input is read in parts with
the step's own model and the answer is written over the notes. The step result
records the coverage; partial coverage fails the step unless it has a review.
Changing input_config replaces it whole, so keep its other keys.
Name a step in an answer as @[<user_description>](step:<id>) with the values
read_flow gives, and a value a step produces as the reference the flow resolves,
{{step_<step_order>.output.text}} or {{step_<step_order>.output.structured.<field>}};
the editor shows both as pills that open the step. The person's messages use the
same forms.
""",
)


def page_result(
    value: Any, *, flow_id: UUID, offset: int = 0, revision: int | None = None
) -> CallToolResult:
    if offset < 0:
        raise BadRequestException("offset must be non-negative.")
    serialized = json.dumps(
        value, ensure_ascii=False, default=str, separators=(",", ":")
    )
    if offset > len(serialized):
        raise BadRequestException(
            "offset is beyond this value; read again from offset 0 after a change."
        )
    end = min(len(serialized), offset + max(1, min(4000, default_page_cap() // 4)))
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
    also reports the suggestions the change introduced (``_with_introduced``).
    """
    from eneo.flows.application.flow_authoring_chat import (
        load_authoring_chat,
        require_authoring_edit,
        scoped_request,
    )
    from eneo.flows.application.flow_authoring_operations import (
        authoring_transaction,
    )

    try:
        # Refusals are caught outside this block so failed writes roll back;
        # the change's audit entries are logged once it has committed.
        async with internal_tool_context(ctx, transactional=False) as scope:
            if scope.session_id is None:
                raise NotFoundException("Flow authoring chat not found.")
            async with authoring_transaction(scope.container):
                chat = await load_authoring_chat(
                    scope.container,
                    session_id=scope.session_id,
                    assistant_id=scope.assistant_id,
                    lock=editing or changes_draft,
                )
                if editing or changes_draft:
                    await require_authoring_edit(scope.container, chat)
                request = scoped_request(chat.space_id)
                if not changes_draft:
                    return await operation(scope.container, chat, request)
                before = await _draft_suggestions(scope.container, chat.flow_id)
                result = await operation(scope.container, chat, request)
                return await _with_introduced(
                    result, scope.container, chat.flow_id, before
                )
    except (
        BadRequestException,
        ConflictException,
        NotFoundException,
        UnauthorizedException,
        ValidationError,
    ) as exc:
        details = (
            exc.errors(include_input=False, include_context=False)
            if isinstance(exc, ValidationError)
            else None
        )
        message = (
            "The submitted configuration is invalid."
            if details is not None
            else str(exc)
        )
        return CallToolResult(
            isError=True,
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "message": message,
                            "code": getattr(exc, "code", None),
                            "errors": details,
                        },
                        default=str,
                    ),
                )
            ],
        )


async def _draft_suggestions(container, flow_id: UUID):
    """The draft's static suggestions and its steps, read in a savepoint of
    the change's transaction, without those the flow's editors dismissed;
    None when they cannot be computed. A failure is logged by its kind only
    and never fails the change."""
    from sqlalchemy.ext.asyncio import AsyncSession

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
    while (
        len(json.dumps(page, ensure_ascii=False)) > default_page_cap()
        and page["introduced_suggestions"]
    ):
        page["introduced_suggestions"] = page["introduced_suggestions"][:-1]
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
            async with scope.container.session().begin():
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
        NotFoundException,
        UnauthorizedException,
        ValidationError,
    ) as exc:
        errors = (
            exc.errors(include_input=False, include_context=False)
            if isinstance(exc, ValidationError)
            else None
        )
        return CallToolResult(
            isError=True,
            content=[
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "message": "The submitted configuration is invalid."
                            if errors is not None
                            else str(exc),
                            "code": getattr(exc, "code", None),
                            "errors": errors,
                        },
                        default=str,
                    ),
                )
            ],
        )


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


FlowSection = Literal["overview", "steps", "settings", "all"]

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


@mcp.tool()
async def read_flow(
    ctx: Context,
    section: FlowSection = "overview",
    steps: list[int] | None = None,
    offset: int = 0,
) -> CallToolResult:
    """Read the saved draft. The overview (default) is short: the flow's name,
    its run form fields and every step with its kind, the fields its result
    declares (output_fields), whether a person reviews it, what it reads
    (reads: each earlier result as the reference the flow resolves and
    where the read is written), which later steps read its result (readers,
    the same way) and the run form fields it reads. Section "steps" gives
    the steps in full with their assistants' prompts and the same reads;
    section "settings" the flow without its steps (description,
    metadata_json with the run form, retention, permissions); section "all"
    everything, paged. steps=[5, 8] limits the overview or the steps section
    to those step numbers (1 is first). A step marked unreadable has a
    configuration the flow cannot read; read it in full and fix it. Follow
    next_offset until it is null."""

    async def operation(container, chat, request):
        from eneo.flows.application.flow_authoring_operations import get_flow
        from eneo.flows.application.flow_authoring_reads import (
            output_fields,
            run_form_fields,
            step_reads_summary,
        )

        flow = await get_flow(chat.flow_id, request, container)
        if section == "all":
            value: Any = flow.model_dump(mode="json")
        elif section == "settings":
            value = flow.model_dump(mode="json", exclude={"steps"})
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
            saved = await container.flow_service().get_flow(chat.flow_id)
            prompts = await container.flow_service().get_flow_assistant_prompts(saved)
            reads = step_reads_summary(saved, prompts)
            items: list[dict[str, Any]] = []
            for step in chosen:
                if section == "overview":
                    item = step.model_dump(
                        mode="json", include=set(_OVERVIEW_STEP_FIELDS)
                    )
                    item["output_fields"] = output_fields(step.output_contract)
                    item["review"] = step.review_policy is not None
                else:
                    item = step.model_dump(mode="json")
                    prompt = prompts.get(step.assistant_id)
                    item["prompt"] = prompt.text if prompt is not None else None
                item.update(reads.get(step.step_order, {}))
                items.append(item)
            value = {
                "name": flow.name,
                "published_version": flow.published_version,
                "steps": items,
            }
            if section == "overview":
                value["description"] = flow.description
                value["run_form_fields"] = run_form_fields(flow.metadata_json)
        return page_result(
            value, flow_id=flow.id, offset=offset, revision=flow.draft_revision
        )

    return await _call(ctx, operation)


@mcp.tool()
async def update_flow_settings(
    ctx: Context, expected_revision: int, changes: dict[str, Any]
) -> CallToolResult:
    """Change flow name, description or metadata_json, preserving all other fields.
    To rename a run form field, send the new metadata_json with
    form_field_renames ({"old name": "new name"}): the steps' reads of the field
    follow it. A field a step reads cannot be removed."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_models import FlowEditorUpdateRequest
        from eneo.flows.application.flow_authoring_operations import apply_editor_update

        if set(changes) - {
            "name",
            "description",
            "metadata_json",
            "form_field_renames",
        }:
            raise BadRequestException(
                "Only name, description, metadata_json and form_field_renames "
                "can be changed here."
            )
        flow = await apply_editor_update(
            chat.flow_id,
            request,
            FlowEditorUpdateRequest.model_validate(
                {"expected_revision": expected_revision, "definition": changes}
            ),
            container,
        )
        return page_result(
            {"saved": True}, flow_id=chat.flow_id, revision=flow.draft_revision
        )

    return await _call(ctx, operation, changes_draft=True)


@mcp.tool()
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
    """Never let a model send a credential or retarget a retained credential."""
    from eneo.flows.http_transport import (
        HTTP_CONFIG_KEYS,
        HttpAuthoredConfig,
        contains_secret_sentinel,
    )

    def declares_secret_material(value: dict[str, Any]) -> bool:
        # Read without the core model, for configs it refuses: any auth other
        # than none, any auth field besides its mode, or any custom header.
        auth = value.get("auth")
        if isinstance(auth, dict):
            if auth.get("mode", auth.get("type")) not in (None, "", "none"):
                return True
            if any(
                item not in (None, "", {}, [])
                for key, item in auth.items()
                if key not in ("mode", "type")
            ):
                return True
        elif auth not in (None, "", "none"):
            return True
        return value.get("custom_headers") not in (None, "", {}, [])

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
                    if declares_secret_material(value):
                        return True
                else:
                    if authored.has_declared_credentials:
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
                    and item not in (None, {}, [], "")
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
                "Configure credentials and destinations that use them directly in the flow editor."
            )


@mcp.tool()
async def update_step(
    ctx: Context,
    expected_revision: int,
    step_id: UUID,
    changes: dict[str, Any],
    assistant_changes: dict[str, Any] | None = None,
) -> CallToolResult:
    """Patch one saved step and optionally its assistant in one revision. Use the flow's own
    field names; input_config is replaced whole (long material:
    input_config.long_material). Renaming the step (user_description) rewrites
    the reads of its old name in every step. When other steps share the step's
    assistant, the step gets its own copy with assistant_changes and the others
    keep theirs; the result names the step's assistant_id. A change that
    reaches several steps goes in one update_steps call instead."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_models import FlowEditorUpdateRequest
        from eneo.flows.application.flow_authoring_operations import (
            apply_editor_update,
            get_flow,
        )

        flow = await get_flow(chat.flow_id, request, container)
        edit = _step_edit(flow, step_id, changes, assistant_changes)
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
        )
        saved_step = next(item for item in updated.steps if item.id == step_id)
        return page_result(
            {
                "saved": True,
                "step_id": str(step_id),
                "assistant_id": str(saved_step.assistant_id),
            },
            flow_id=chat.flow_id,
            revision=updated.draft_revision,
        )

    return await _call(ctx, operation, changes_draft=True)


class _StepEdit:
    """One step's part of an editor update, checked as update_step checks
    it: the step exists, only configuration fields change, and no
    credential is sent or retargeted."""

    def __init__(
        self, step_edits: list[dict[str, Any]], assistants: list[dict[str, Any]]
    ):
        self.step_edits = step_edits
        self.assistants = assistants


def _step_edit(
    flow: Any,
    step_id: UUID,
    changes: dict[str, Any] | None,
    assistant_changes: dict[str, Any] | None,
) -> _StepEdit:
    from eneo.flows.api.flow_models import FlowStepUpdateRequest

    step = next((item for item in flow.steps if item.id == step_id), None)
    if step is None:
        raise NotFoundException("Step not found.")
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
    return _StepEdit(
        step_edits=[{"step_id": str(step_id), "changes": changes}] if changes else [],
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


@mcp.tool()
async def update_steps(
    ctx: Context,
    expected_revision: int,
    edits: list[dict[str, Any]],
    settings: dict[str, Any] | None = None,
) -> CallToolResult:
    """Change several saved steps, and optionally the flow's settings, in one
    revision: everything is saved or nothing. Each edit is {"step_id": ...,
    "changes": {...}, "assistant_changes": {...}} with the fields update_step
    takes (either part may be left out); a step appears once. settings takes
    what update_flow_settings takes. Use it when one change reaches several
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
            part = _step_edit(
                flow, step_id, edit.get("changes"), edit.get("assistant_changes")
            )
            step_edits.extend(part.step_edits)
            assistants.extend(part.assistants)
            edited.append(step_id)
        updated = await apply_editor_update(
            chat.flow_id,
            request,
            FlowEditorUpdateRequest.model_validate(
                {
                    "expected_revision": expected_revision,
                    "definition": settings or {},
                    "step_edits": step_edits,
                    "assistants": assistants,
                }
            ),
            container,
        )
        by_id = {step.id: step for step in updated.steps}
        return page_result(
            {
                "saved": True,
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": by_id[step_id].step_order,
                        "name": by_id[step_id].user_description,
                        "assistant_id": str(by_id[step_id].assistant_id),
                    }
                    for step_id in edited
                ],
            },
            flow_id=chat.flow_id,
            revision=updated.draft_revision,
        )

    return await _call(ctx, operation, changes_draft=True)


@mcp.tool()
async def add_step(
    ctx: Context,
    expected_revision: int,
    name: str,
    configuration: dict[str, Any],
    assistant_changes: dict[str, Any] | None = None,
    position: int | None = None,
) -> CallToolResult:
    """Add a step with a new managed assistant, atomically: last, or at `position`
    (1 is first). Reads of the steps after it move with them. Use the flow's own
    configuration field names."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_models import FlowEditorUpdateRequest
        from eneo.flows.application.flow_authoring_operations import (
            apply_editor_update,
            get_flow,
        )

        require_safe_model_configuration(configuration, {})
        step_order = None
        if position is not None:
            flow = await get_flow(chat.flow_id, request, container)
            slots: list[dict[str, Any]] = [
                {"step_id": str(step.id)} for step in flow.steps
            ]
            slots.insert(_index_at(position, len(slots) + 1), {"new_step": 0})
            step_order = slots
        updated = await apply_editor_update(
            chat.flow_id,
            request,
            FlowEditorUpdateRequest.model_validate(
                {
                    "expected_revision": expected_revision,
                    "definition": {},
                    "new_steps": [
                        {
                            "name": name,
                            "configuration": configuration,
                            "assistant": assistant_changes or {},
                        }
                    ],
                    "step_order": step_order,
                }
            ),
            container,
        )
        added = updated.steps[-1 if position is None else position - 1]
        return page_result(
            {"saved": True, "step_id": str(added.id)},
            flow_id=chat.flow_id,
            revision=updated.draft_revision,
        )

    return await _call(ctx, operation, changes_draft=True)


@mcp.tool()
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


@mcp.tool()
async def remove_step(
    ctx: Context, expected_revision: int, step_id: UUID
) -> CallToolResult:
    """Remove a saved step and its managed assistant. Refused while another
    step still reads it; change that read first."""

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


@mcp.tool()
async def publish_flow(ctx: Context, expected_revision: int) -> CallToolResult:
    """Publish the current revision after the user explicitly requests publication."""

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


@mcp.tool()
async def unpublish_flow(ctx: Context, expected_revision: int) -> CallToolResult:
    """Unpublish the flow after the user explicitly requests editing a published flow."""

    async def operation(container, chat, request):
        from eneo.flows.application.flow_authoring_operations import (
            unpublish_flow as unpublish,
        )

        flow = await unpublish(
            chat.flow_id, request, container, expected_revision=expected_revision
        )
        return page_result(
            {"published_version": flow.published_version},
            flow_id=chat.flow_id,
            revision=flow.draft_revision,
        )

    return await _call(ctx, operation, editing=True)


@mcp.tool()
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


@mcp.tool()
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
    deterministic_candidate (a model step only copies its inputs, which a
    compose_text step does without a model), and oversized_reasoning (a step
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
async def run_flow(
    ctx: Context,
    expected_flow_version: int,
    idempotency_key: str,
    inputs: dict[str, Any],
    step_inputs: dict[str, Any] | None = None,
) -> CallToolResult:
    """Start a published flow only when asked. Reuse idempotency_key after an uncertain response."""

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


@mcp.tool()
async def read_run(ctx: Context, run_id: UUID, offset: int = 0) -> CallToolResult:
    """Read paged run results through the authorized evidence snapshot and audit."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_run_lifecycle_router import get_flow_run

        result = await get_flow_run(
            id=chat.flow_id, run_id=run_id, request=request, container=container
        )
        return _runtime_result(result, flow_id=chat.flow_id, offset=offset)

    return await _call_runtime(ctx, operation)


@mcp.tool()
async def cancel_run(ctx: Context, run_id: UUID) -> CallToolResult:
    """Cancel a run of this flow only when the user asks to cancel it."""

    async def operation(container, chat, request):
        from eneo.flows.api.flow_run_lifecycle_router import cancel_flow_run

        return _runtime_result(
            await cancel_flow_run(
                id=chat.flow_id, run_id=run_id, request=request, container=container
            ),
            flow_id=chat.flow_id,
        )

    return await _call_runtime(ctx, operation)


@mcp.tool()
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


@mcp.tool()
async def review_run(
    ctx: Context,
    run_id: UUID,
    checkpoint_id: UUID,
    expected_checkpoint_revision: int,
    action: Literal["approve", "reject", "edit", "resume", "approve_and_continue"],
    changes: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> CallToolResult:
    """Apply an explicitly requested review action using the current checkpoint revision. changes holds edited_value or rejection reason."""

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
        "add_step",
        "move_step",
        "remove_step",
        "publish_flow",
        "unpublish_flow",
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
