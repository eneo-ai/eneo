"""Tool calls a tool's view makes through the host.

A view (MCP App) may call tools on the server it came from. It runs in the
user's browser with no credentials of its own, so the call is made here, for
the user, and only where one of the user's own turns could have made it: the
view must belong to a finished tool call of the conversation, the server must
still be one the assistant reaches, and the tool must be enabled, approved and
visible to views. The result goes back to the view. It is not written into
the conversation: what a view wants the model to know, it says itself.

A view is given its call's arguments as they are stored, with the signature of
every file link removed. When it passes such a link on (to read the same file
again), the link is signed anew here, and only for a file its own call was
given and the conversation or its assistant still holds.
"""

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

from eneo.authentication.signed_urls import (
    build_signed_original_download_url,
    redact_reference_tokens,
    reference_file_ids,
    restore_reference_tokens,
)
from eneo.files.file_reference import file_reference_base_url
from eneo.files.model_file_references import (
    UnknownFileReference,
    handle_file_ids,
    resolve_file_handles,
)
from eneo.main.config import get_settings
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.assistants.assistant_service import AssistantService
    from eneo.files.file_models import File
    from eneo.mcp_apps.infrastructure.repo_impl.mcp_app_view_repo_impl import (
        McpAppViewRepo,
    )
    from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
        MCPProxySessionFactory,
    )
    from eneo.questions.question import ToolCallInfo
    from eneo.sessions.session import SessionInDB

logger = get_logger(__name__)

# The arguments of one call, as JSON.
MAX_ARGUMENT_BYTES = 1024 * 1024

# One answer for every reason a view may not make a call, so a view learns
# nothing about tools and servers it is not offered.
_NOT_FOUND = "The view cannot call this tool"


class ViewCallNotReady(Exception):
    """The tool call the view belongs to has not finished."""


@dataclass(frozen=True)
class ViewToolCallResult:
    mcp_server_id: UUID
    tool_name: str
    text: str | None
    structured_content: dict[str, Any] | None
    is_error: bool
    # Files whose links were signed again for this call.
    signed_files: "list[File]" = field(default_factory=lambda: [])


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


def originating_call(
    conversation: "SessionInDB", tool_call_id: str, view_id: UUID
) -> "tuple[UUID | None, ToolCallInfo] | None":
    """The conversation's tool call that shows this view, and its assistant.

    Tool call ids come from model providers and may repeat between turns, so
    the newest call with the id that also shows this very view is the one.
    """
    for question in reversed(conversation.questions or []):
        for call in question.tool_calls or []:
            if call.tool_call_id != tool_call_id or not call.app_view:
                continue
            if _uuid(call.app_view.get("view_id")) == view_id:
                return question.assistant_id, call
    return None


def view_server_id(
    conversation: "SessionInDB", tool_call_id: str, view_id: UUID
) -> UUID | None:
    """The server of the view shown for a tool call, when the conversation has one."""
    found = originating_call(conversation, tool_call_id, view_id)
    if found is None:
        return None
    return _uuid((found[1].app_view or {}).get("mcp_server_id"))


async def _with_signed_file_links(
    arguments: dict[str, Any],
    *,
    call: "ToolCallInfo",
    conversation: "SessionInDB",
    assistant_id: UUID,
    assistant_service: "AssistantService",
    tenant_id: UUID,
) -> "tuple[dict[str, Any], list[File]]":
    """``arguments`` with the unsigned file links a view may use signed again.

    A link is signed only if the view's own call carried it and the file is
    one the conversation holds (attached to or generated in one of its turns)
    or an attachment of its assistant. What a call's arguments say is the
    model's writing, so it is never on its own a reason to sign a link.
    """
    unsigned = reference_file_ids(
        arguments, include_redacted=True
    ) - reference_file_ids(arguments)
    unsigned |= handle_file_ids(arguments)
    originating_files = reference_file_ids(
        call.arguments, include_redacted=True
    ) | handle_file_ids(call.arguments)
    wanted = unsigned & originating_files
    base_url = file_reference_base_url()
    if not wanted or not base_url:
        return arguments, []

    held: "dict[UUID, File]" = {
        file.id: file
        for question in conversation.questions or []
        for file in [
            *getattr(question, "files", []),
            *getattr(question, "generated_files", []),
        ]
    }
    if wanted - held.keys():
        for file in await assistant_service.attachment_files(assistant_id):
            held.setdefault(file.id, file)

    signed = [held[file_id] for file_id in sorted(wanted & held.keys(), key=str)]
    expires_in = get_settings().file_reference_url_expiry_seconds
    fresh = {
        file.id: build_signed_original_download_url(
            file_id=file.id,
            base_url=base_url,
            expires_in=expires_in,
            tenant_id=tenant_id,
        )
        for file in signed
    }
    restored = cast("dict[str, Any]", restore_reference_tokens(arguments, fresh))
    try:
        restored = resolve_file_handles(restored, fresh)
    except UnknownFileReference as exc:
        raise BadRequestException(
            "The file reference is not available to this view"
        ) from exc
    return restored, signed


async def call_tool_from_view(
    *,
    conversation: "SessionInDB",
    tool_call_id: str,
    view_id: UUID,
    name: str,
    arguments: dict[str, Any],
    assistant_service: "AssistantService",
    app_view_repo: "McpAppViewRepo",
    proxy_factory: "MCPProxySessionFactory",
    identity_headers: dict[str, str],
    tenant_id: UUID,
) -> ViewToolCallResult:
    """Run ``name`` on the server of the view shown for ``tool_call_id``."""
    found = originating_call(conversation, tool_call_id, view_id)
    if found is None:
        raise NotFoundException(_NOT_FOUND)
    assistant_id, call = found
    if call.result_status not in (None, "succeeded", "completed"):
        raise ViewCallNotReady()

    mcp_server_id = _uuid((call.app_view or {}).get("mcp_server_id"))
    if assistant_id is None and conversation.assistant is not None:
        assistant_id = conversation.assistant.id
    if mcp_server_id is None or assistant_id is None:
        raise NotFoundException(_NOT_FOUND)

    if len(json.dumps(arguments, ensure_ascii=False).encode()) > MAX_ARGUMENT_BYTES:
        raise BadRequestException("The tool arguments are too large")

    server = await assistant_service.mcp_server_for_view(
        assistant_id=assistant_id, mcp_server_id=mcp_server_id
    )
    if server is None:
        raise NotFoundException(_NOT_FOUND)

    # A historical call is not an enduring grant. Check the current pin and
    # originating tool on every request, including already-open browser views.
    view = await app_view_repo.get_for_tenant(
        view_id, tenant_id, approved_only=True, tool_name=call.tool_name
    )
    if view is None or view.mcp_server_id != server.id:
        raise NotFoundException(_NOT_FOUND)

    arguments, signed_files = await _with_signed_file_links(
        arguments,
        call=call,
        conversation=conversation,
        assistant_id=assistant_id,
        assistant_service=assistant_service,
        tenant_id=tenant_id,
    )

    # The session offers exactly the server's tools a view may call; a tool
    # that is disabled, unapproved or kept for the model is not among them.
    proxy = proxy_factory.create(
        [server], identity_headers=identity_headers, for_view=True
    )
    proxy.allow_file_references(file.id for file in signed_files)
    try:
        prefixed = proxy.prefixed_tool_name(server.id, name)
        if prefixed is None:
            raise NotFoundException(_NOT_FOUND)
        result = (await proxy.call_tools_parallel([(prefixed, arguments)]))[0]
    finally:
        await proxy.close()

    # Tools can echo freshly signed links; never hand those credentials to a view.
    result = cast(dict[str, Any], redact_reference_tokens(result))
    blocks = cast(list[dict[str, Any]], result.get("content") or [])
    texts = [
        str(block.get("text"))
        for block in blocks
        if block.get("type") == "text" and block.get("text")
    ]
    return ViewToolCallResult(
        mcp_server_id=server.id,
        tool_name=name,
        text="\n".join(texts) or None,
        structured_content=result.get("structured_content"),
        is_error=bool(result.get("is_error")),
        signed_files=signed_files,
    )
