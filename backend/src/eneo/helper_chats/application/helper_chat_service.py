"""Session-bound authorization and upkeep of a helper chat, for every target.

A person has one chat per target: a hidden assistant and the conversation
that is current. Earlier conversations stay with the assistant for
traceability and are listed for their person (``list_conversations``), but
only the current one is ever answered or sent to the model, because
``load_chat`` admits only the session the chat points at. What the chat helps
with, who may read and change it and how its audit entries read is the
target's (``helper_chats.targets``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant import AssistantOrigin
from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.helper_chats_table import HelperChats
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.helper_chats.binding import HelperChatBinding
from eneo.helper_chats.targets import (
    HelperChatAuditEvent,
    HelperChatModes,
    HelperChatTarget,
    target_for,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.main.logging import get_logger
from eneo.main.models import NOT_PROVIDED, NotProvided, is_provided
from eneo.mcp_servers.application.capability_resolver import capability_availability
from eneo.mcp_servers.domain.capabilities import (
    CapabilityAvailability,
    CapabilityPurpose,
)
from eneo.prompts.api.prompt_models import PromptCreate
from eneo.sessions.session import SessionAdd

if TYPE_CHECKING:
    from eneo.completion_models.domain import CompletionModel
    from eneo.spaces.space import Space


def _session(container: Container) -> AsyncSession:
    return cast(AsyncSession, container.session())


logger = get_logger(__name__)


@dataclass(frozen=True)
class OpenedChat:
    """A chat as an entry point leaves it, with the model it answers with
    while the person has chosen none."""

    chat: HelperChats
    default_completion_model_id: UUID | None


def in_edit_mode(target: HelperChatTarget[Any], chat: HelperChats) -> bool:
    """Whether the chat is in edit mode, where the chat itself may write to
    its target. Never on a target without modes, whatever its row holds."""
    return target.modes is not None and chat.editing


def _modes_of(target: HelperChatTarget[Any]) -> HelperChatModes[Any]:
    """The modes of a target that has them. Only what a target with modes
    offers asks, so a target without them here is a caller's mistake."""
    if target.modes is None:
        raise TypeError(f"A helper chat on a {target.target_type} has no modes.")
    return target.modes


async def load_chat(
    container: Container,
    target: HelperChatTarget[Any],
    *,
    session_id: UUID,
    assistant_id: UUID | None = None,
    target_id: UUID | None = None,
    lock: bool = False,
) -> HelperChats:
    """The caller's chat for ``session_id`` on ``target``, after the binding's
    access checks.

    Opening the chat, the start of a turn and every tool call load the chat
    here, so this is where a chat left in edit mode returns to view mode
    after a pause (``_leave_edit_mode_after_pause``): the chat opened, or a
    turn started on a tab left open, after the pause offers no writing tools,
    and its tool calls are refused a change."""
    chat, _ = await _load_chat(
        container,
        target,
        session_id=session_id,
        assistant_id=assistant_id,
        target_id=target_id,
        lock=lock,
    )
    return chat


async def _load_chat(
    container: Container,
    target: HelperChatTarget[Any],
    *,
    session_id: UUID,
    assistant_id: UUID | None,
    target_id: UUID | None,
    lock: bool,
) -> tuple[HelperChats, Any]:
    """``load_chat``, with the target as its read check read it."""
    await target.require_available(container)
    chat, record = await _read_chat(
        container,
        target,
        session_id=session_id,
        assistant_id=assistant_id,
        target_id=target_id,
        lock=lock,
    )
    await _leave_edit_mode_after_pause(container, chat)
    return chat, record


async def _read_chat(
    container: Container,
    target: HelperChatTarget[Any],
    *,
    session_id: UUID | None,
    assistant_id: UUID | None,
    target_id: UUID | None,
    lock: bool,
) -> tuple[HelperChats, Any]:
    """The caller's chat on ``target`` as it is stored, after the binding's
    checks: the chat for ``session_id``, or without one the caller's chat on
    ``target_id``. Its row, its current conversation and its hidden assistant
    must all be the caller's own, and the target the caller's to read. The
    caller asks whether the target is offered first. Nothing is written."""
    user = container.user()
    query = (
        sa.select(HelperChats)
        .join(Sessions, Sessions.id == HelperChats.session_id)
        .join(Assistants, Assistants.id == HelperChats.assistant_id)
        .where(
            HelperChats.tenant_id == user.tenant_id,
            HelperChats.user_id == user.id,
            HelperChats.target_type == target.target_type,
            Sessions.user_id == user.id,
            Sessions.api_key_id.is_(None),
            Sessions.assistant_id == HelperChats.assistant_id,
            Assistants.space_id == HelperChats.space_id,
            Assistants.hidden.is_(True),
            Assistants.origin == AssistantOrigin.USER,
            target.target_exists(user.tenant_id),
        )
    )
    if session_id is not None:
        query = query.where(HelperChats.session_id == session_id)
    if assistant_id is not None:
        query = query.where(HelperChats.assistant_id == assistant_id)
    if target_id is not None:
        query = query.where(HelperChats.target_id == target_id)
    chat = await _session(container).scalar(query)
    if chat is None:
        raise target.refusals.chat_not_found()
    record = await target.require_read(
        container, target.scoped_request(chat.space_id), chat.target_id
    )
    if lock:
        # Every writer locks the target before its chat and assistant,
        # including mode changes, so leaving edit mode fences an in-flight
        # tool call.
        await target.lock(container, chat.target_id)
        chat = await _session(container).scalar(
            query.with_for_update(of=HelperChats).execution_options(
                populate_existing=True
            )
        )
        if chat is None:
            raise target.refusals.chat_not_found()
    return chat, record


def turn_in_edit_mode(
    target: HelperChatTarget[Any], chat: HelperChats, record: object
) -> bool:
    """Whether a turn of the chat runs in edit mode: the chat is in it and
    the target may change right now. A turn on a target that cannot change
    (a published flow) runs as "Fråga" whatever the row holds, so the tools
    it is offered and the note it is told say what the panel shows; the row
    is left as it is."""
    return in_edit_mode(target, chat) and target.changeable(record)


async def load_binding(
    container: Container, *, session_id: UUID, assistant_id: UUID
) -> HelperChatBinding:
    """The chat ``assistant_id`` answers in, loaded as its target loads it,
    with the mode its turn runs in (``turn_in_edit_mode``), read from the
    target its access check loaded. An assistant that is no chat's is not
    found."""
    target_type = await _session(container).scalar(
        sa.select(HelperChats.target_type).where(
            HelperChats.tenant_id == container.user().tenant_id,
            HelperChats.assistant_id == assistant_id,
        )
    )
    if target_type is None:
        raise NotFoundException("Helper chat not found.")
    target = target_for(target_type)
    chat, record = await _load_chat(
        container,
        target,
        session_id=session_id,
        assistant_id=assistant_id,
        target_id=None,
        lock=False,
    )
    return HelperChatBinding(
        target_type=chat.target_type,
        target_id=chat.target_id,
        editing=turn_in_edit_mode(target, chat, record),
    )


async def require_edit_mode(
    container: Container,
    target: HelperChatTarget[Any],
    chat: HelperChats,
    *,
    change: bool = False,
) -> None:
    """Edit mode and edit access to the chat's ``target``, which has modes,
    and with ``change`` also a target that may change right now, so a change
    it refuses is refused before anything is read or written."""
    modes = _modes_of(target)
    if not chat.editing:
        raise modes.not_editing()
    await _require_edit_access(container, target, chat, change=change)


async def require_approved_change(
    container: Container, target: HelperChatTarget[Any], chat: HelperChats
) -> None:
    """What a change the person approves in the chat before it runs (such as
    publishing) needs: edit access to a target that may change right now,
    and on a target with modes edit mode too. A chat on a target without
    modes never writes by itself, so there the approval takes its place."""
    if target.modes is not None:
        await require_edit_mode(container, target, chat, change=True)
        return
    await _require_edit_access(container, target, chat, change=True)


async def _require_edit_access(
    container: Container,
    target: HelperChatTarget[Any],
    chat: HelperChats,
    *,
    change: bool,
) -> None:
    record = await target.require_edit(
        container, target.scoped_request(chat.space_id), chat.target_id
    )
    if change:
        target.require_changeable(record)


# --- The chat's model -------------------------------------------------------


@dataclass(frozen=True)
class _ChatModels:
    """The models a helper chat in one space may answer with."""

    usable: list[CompletionModel]
    default: CompletionModel | None

    def get(self, model_id: UUID | None) -> CompletionModel | None:
        return next((model for model in self.usable if model.id == model_id), None)

    def effective(self, chosen_id: UUID | None) -> CompletionModel | None:
        """The person's model while the space allows it, else the default."""
        return self.get(chosen_id) or self.default


def _chat_models(
    container: Container, target: HelperChatTarget[Any], space: Space
) -> _ChatModels:
    # The space's usable models are those enabled in it that meet its
    # classification, the same list an ordinary assistant's model comes from.
    usable = [
        model
        for model in space.completion_models
        if model.can_access and model.supports_tool_calling
    ]
    organisation_default = target.organisation_default_model_id(container)
    default = next(
        (model for model in usable if model.id == organisation_default), None
    ) or space.select_default_completion_model(usable)
    return _ChatModels(usable=usable, default=default)


def _offered_reasoning_effort(
    model: CompletionModel, reasoning_effort: str | None
) -> str | None:
    """The level when the model offers it, else None (the model's own default)."""
    return (
        ModelKwargs(reasoning_effort=reasoning_effort)
        .filter_unsupported(model.get_supported_model_kwargs())
        .reasoning_effort
    )


def _require_choosable_model(
    target: HelperChatTarget[Any], space: Space, model_id: UUID
) -> CompletionModel:
    """The model a person asks for, refused the way an assistant's model is."""
    if space.is_completion_model_available(model_id):
        model = space.get_completion_model(model_id)
        if not model.supports_tool_calling:
            raise target.refusals.model_without_tools(model_id)
        return model
    if any(
        model.id == model_id and model.can_access
        for model in space.completion_models_below_classification
    ):
        raise target.refusals.model_below_classification(model_id)
    raise target.refusals.model_not_in_space(model_id)


# The functions of the tool runtime the chat may use: reading an uploaded
# file where it needs to, making a file or a chart, computing. Searching the
# web and making images are not the chat's business.
TOOL_RUNTIME_CAPABILITIES: tuple[CapabilityPurpose, ...] = (
    "file_analysis",
    "file_creation",
    "charts",
    "compute",
)


def tool_runtime_capabilities(
    offered: Iterable[str], states: Iterable[CapabilityAvailability]
) -> list[CapabilityPurpose]:
    """The tool runtime's functions the chat's assistant gets: those its space
    offers and a provider is ready for, in a fixed order."""
    offered_set = set(offered)
    ready = {state.purpose for state in states if state.available}
    return [
        purpose
        for purpose in TOOL_RUNTIME_CAPABILITIES
        if purpose in offered_set and purpose in ready
    ]


async def _load_space(container: Container, chat: HelperChats) -> Space:
    return await container.space_repo().one(
        id=chat.space_id, hidden_assistant_ids={chat.assistant_id}
    )


async def _sync_assistant(
    container: Container, chat: HelperChats, space: Space | None = None
) -> CompletionModel | None:
    """Give the chat's assistant the target's current instructions and the
    model and reasoning effort in force; write only what differs. Returns
    the default."""
    target = target_for(chat.target_type)
    space = space or await _load_space(container, chat)
    models = _chat_models(container, target, space)
    model = models.effective(chat.completion_model_id)
    if model is None:
        raise target.refusals.no_model()
    assistant = space.get_assistant(assistant_id=chat.assistant_id)
    changes: dict[str, Any] = {}
    instructions = target.instructions(container)
    if assistant.get_prompt_text() != instructions:
        changes["prompt"] = PromptCreate(text=instructions)
    model_changes = (
        assistant.completion_model is None or assistant.completion_model.id != model.id
    )
    if model_changes:
        changes["completion_model_id"] = model.id
    stored = assistant.completion_model_kwargs or ModelKwargs()
    effort = _offered_reasoning_effort(model, chat.reasoning_effort)
    if stored.reasoning_effort != effort:
        changes["completion_model_kwargs"] = stored.model_copy(
            update={"reasoning_effort": effort}
        )
    if changes:
        await container.assistant_service().update_assistant(
            assistant_id=chat.assistant_id,
            update=AssistantUpdateCommand(**changes),
            include_hidden=True,
        )
    await _sync_tools(container, chat, space, assistant)
    return models.default


async def _sync_tools(
    container: Container, chat: HelperChats, space: Space, assistant: Any
) -> None:
    """Give the chat's assistant what its target's chat works with
    (``HelperChatTarget.tool_runtime``): look-up mode for uploads and the tool
    runtime's functions its space offers, or neither. Each goes in an update
    of its own: a refusal (a provider that stopped meeting the space's
    classification, a tool set that does not fit the model) is logged and
    leaves the chat as it is, and never takes the other setting with it."""
    tool_runtime = target_for(chat.target_type).tool_runtime
    # With the tool runtime, a file uploaded in the chat is looked up through
    # the files tool where the model needs it, not put whole in the prompt:
    # the chat is shown long material (a letter, a transcript) to work from.
    # A model without tool calling gets the text inlined anyway. Without the
    # tool runtime there is no files tool, and the text goes with the question.
    if assistant.inline_file_text == tool_runtime:
        await _update_tools(
            container,
            chat,
            "look-up mode" if tool_runtime else "uploads read with the question",
            inline_file_text=not tool_runtime,
        )
    # The tool runtime's functions, as far as the space offers them and a
    # provider is ready; a space setting that changed is followed here.
    wanted: list[CapabilityPurpose] = []
    if tool_runtime:
        states = await capability_availability(
            _session(container), chat.tenant_id, space.security_classification
        )
        wanted = tool_runtime_capabilities(space.enabled_capabilities, states)
    if sorted(wanted) != sorted(assistant.enabled_capabilities):
        await _update_tools(
            container, chat, "the tool runtime's functions", enabled_capabilities=wanted
        )


async def _update_tools(
    container: Container, chat: HelperChats, what: str, **setting: Any
) -> None:
    try:
        await container.assistant_service().update_assistant(
            assistant_id=chat.assistant_id,
            update=AssistantUpdateCommand(**setting),
            include_hidden=True,
        )
    except BadRequestException as exc:
        logger.warning(
            "The helper chat's assistant %s did not get %s: %s",
            chat.assistant_id,
            what,
            exc,
        )


# --- Conversations ----------------------------------------------------------

# Why a conversation started or the edit mode changed: the person asked, or
# the chat had been idle.
ChangeReason = Literal["requested", "idle"]
# Why a conversation started: a change's reasons, or the chat was opened with a
# fresh start while its conversation held a question.
ConversationStartReason = Literal["requested", "idle", "fresh_start"]

# The most conversations a list holds, and the characters of a conversation's
# first question that make its title.
CONVERSATION_LIST_LIMIT = 50
CONVERSATION_TITLE_LENGTH = 200


class HelperChatConversationPublic(BaseModel):
    """One of the person's conversations in their chat on a target."""

    session_id: UUID = Field(
        description=(
            "The conversation. Read it with `GET /api/v1/conversations/{session_id}/`."
        )
    )
    title: str = Field(
        description=(
            "The conversation's first question, its whitespace collapsed, cut "
            f"to {CONVERSATION_TITLE_LENGTH} characters. Mentions stay as they "
            "were written (`@[Namn](setting:key)`)."
        )
    )
    started_at: datetime = Field(description="When the conversation started.")
    last_asked_at: datetime = Field(
        description="When the conversation's last question was asked."
    )
    current: bool = Field(
        description=(
            "Whether it is the chat's current conversation, the one its "
            "questions go to. Every other conversation is read only: asking "
            "in one returns not found."
        )
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _audit(
    container: Container,
    target: HelperChatTarget[Any],
    event: HelperChatAuditEvent | None,
    *,
    target_id: UUID,
    record: object,
    extra: dict[str, object],
) -> None:
    """One audit entry for ``event`` on the target, with the person as actor;
    none when the target has no action for the event."""
    if event is None:
        return
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=event.action,
        entity_type=target.audit.entity_type,
        entity_id=target_id,
        description=event.description,
        metadata=AuditMetadata.standard(actor=user, target=record, extra=extra),
    )


async def _idle_since_last_activity(
    container: Container, chat: HelperChats, modes: HelperChatModes[Any]
) -> bool:
    """Whether the current conversation has questions and none of them, nor a
    mode change, is newer than the target's idle threshold. An empty
    conversation is never replaced: there is nothing in it to leave behind."""
    last_question = await _session(container).scalar(
        sa.select(sa.func.max(Questions.created_at)).where(
            Questions.session_id == chat.session_id
        )
    )
    if last_question is None:
        return False
    last_activity = max(
        moment for moment in (last_question, chat.mode_changed_at) if moment
    )
    return _now() - last_activity > modes.idle_after()


async def _leave_edit_mode_after_pause(container: Container, chat: HelperChats) -> None:
    """Turn edit mode off when the conversation has been idle, so a person who
    comes back after the pause asks in view mode until they turn edit mode on.
    A chat on a target without modes is never in edit mode, so nothing here
    applies to it.

    ``mode_changed_at`` is left as it is: the idle measure counts the person's
    own activity, so turning edit mode on after this still starts a new
    conversation. The update matches only the chat as it was read, so a mode
    change or a new conversation saved meanwhile is kept."""
    modes = target_for(chat.target_type).modes
    if modes is None or not chat.editing:
        return
    if not await _idle_since_last_activity(container, chat, modes):
        return
    left = await _session(container).scalar(
        sa.update(HelperChats)
        .where(
            HelperChats.tenant_id == chat.tenant_id,
            HelperChats.session_id == chat.session_id,
            HelperChats.editing.is_(True),
            HelperChats.mode_changed_at.is_not_distinct_from(chat.mode_changed_at),
        )
        .values(editing=False)
        .returning(HelperChats.session_id)
        .execution_options(synchronize_session=False)
    )
    if left is None:
        return
    # The row now says what the update wrote; the loaded chat says the same
    # without being written again.
    set_committed_value(chat, "editing", False)
    await _audit_mode_change(container, chat, modes, reason="idle")


async def _audit_mode_change(
    container: Container,
    chat: HelperChats,
    modes: HelperChatModes[Any],
    *,
    reason: ChangeReason,
) -> None:
    """The one audit entry for a change of edit mode, the person's or the
    pause's, with the mode the chat is now in."""
    target = target_for(chat.target_type)
    await _audit(
        container,
        target,
        modes.mode_changed,
        target_id=chat.target_id,
        record=await target.load(container, chat.target_id),
        extra={
            "session_id": str(chat.session_id),
            "editing": chat.editing,
            "reason": reason,
        },
    )


async def _holds_a_question(container: Container, session_id: UUID) -> bool:
    return bool(
        await _session(container).scalar(
            sa.select(sa.exists().where(Questions.session_id == session_id))
        )
    )


async def _start_conversation(
    container: Container, chat: HelperChats, *, reason: ConversationStartReason
) -> None:
    """Point the chat at a new, empty conversation with the same assistant."""
    target = target_for(chat.target_type)
    user = container.user()
    record = await target.load(container, chat.target_id)
    previous = chat.session_id
    # The caller's transaction, as when the chat was created.
    conversation = await container.session_repo().add(
        SessionAdd(
            name=target.name(record), user_id=user.id, assistant_id=chat.assistant_id
        )
    )
    chat.session_id = conversation.id
    await _session(container).flush()
    await _audit(
        container,
        target,
        target.audit.conversation_started,
        target_id=chat.target_id,
        record=record,
        extra={
            "session_id": str(conversation.id),
            "previous_session_id": str(previous),
            "reason": reason,
        },
    )


# --- Entry points -----------------------------------------------------------


def _opened(chat: HelperChats, default: CompletionModel | None) -> OpenedChat:
    return OpenedChat(
        chat=chat,
        default_completion_model_id=default.id if default is not None else None,
    )


async def chat_exists(
    container: Container, target: HelperChatTarget[Any], *, target_id: UUID
) -> bool:
    """Whether the caller already has a chat on the target. Reads only, so an
    entry point that reports what ``get_or_create_chat`` would do can ask."""
    user = container.user()
    return bool(
        await _session(container).scalar(
            sa.select(
                sa.exists().where(
                    HelperChats.tenant_id == user.tenant_id,
                    HelperChats.user_id == user.id,
                    HelperChats.target_type == target.target_type,
                    HelperChats.target_id == target_id,
                )
            )
        )
    )


def chat_default_model(
    container: Container, target: HelperChatTarget[Any], space: Space
) -> CompletionModel | None:
    """The model a chat on the target in ``space`` answers with while the
    person has chosen none; None when the space offers no model the chat can
    use, which ``get_or_create_chat`` refuses."""
    return _chat_models(container, target, space).default


async def get_or_create_chat(
    container: Container,
    target: HelperChatTarget[Any],
    *,
    target_id: UUID,
    request: Request,
    fresh_start: bool = False,
) -> OpenedChat:
    """The caller's chat on the target, made on first use with its hidden
    assistant and first conversation; ``request`` is the caller's own.

    With ``fresh_start`` an existing chat whose current conversation holds a
    question moves to a new, empty one, as a new conversation does, and an
    empty current conversation is kept, so opening again and again leaves
    no empty conversation behind. The model and the mode stay as they are.
    The target's lock orders two openings, so the second finds the first's
    empty conversation and keeps it."""
    user = container.user()
    await target.require_available(container)
    record = await target.require_edit(container, request, target_id)
    # A delete that committed while this waited for the lock leaves no target.
    if not await target.lock(container, target_id):
        raise target.refusals.target_not_found()
    existing = await _session(container).scalar(
        sa.select(HelperChats).where(
            HelperChats.tenant_id == user.tenant_id,
            HelperChats.user_id == user.id,
            HelperChats.target_type == target.target_type,
            HelperChats.target_id == target_id,
        )
    )
    if existing is not None:
        chat = await load_chat(
            container, target, session_id=existing.session_id, target_id=target_id
        )
        if fresh_start and await _holds_a_question(container, chat.session_id):
            await _start_conversation(container, chat, reason="fresh_start")
        return _opened(chat, await _sync_assistant(container, chat))
    space_id = target.space_id(record)
    name = target.name(record)
    space = await container.space_repo().one(id=space_id)
    if _chat_models(container, target, space).default is None:
        raise target.refusals.no_model()
    assistant, _ = await container.assistant_service().create_assistant(
        name=name,
        space_id=space_id,
        hidden=True,
    )
    # Use the caller's transaction: SessionService.create_session commits in
    # a separate transaction, which cannot yet see this newly created parent.
    conversation = await container.session_repo().add(
        SessionAdd(
            name=name,
            user_id=user.id,
            assistant_id=assistant.id,
        )
    )
    chat = (
        await _session(container).scalars(
            sa.insert(HelperChats)
            .values(
                tenant_id=user.tenant_id,
                user_id=user.id,
                target_type=target.target_type,
                target_id=target_id,
                space_id=space_id,
                assistant_id=assistant.id,
                session_id=conversation.id,
                editing=(
                    target.modes is not None
                    and target.modes.starts_in_edit_mode(record)
                ),
            )
            .returning(HelperChats)
        )
    ).one()
    default = await _sync_assistant(container, chat)
    await _audit(
        container,
        target,
        target.audit.chat_created,
        target_id=target_id,
        record=record,
        extra={
            "assistant_id": str(assistant.id),
            "session_id": str(conversation.id),
        },
    )
    return _opened(chat, default)


async def update_chat(
    container: Container,
    target: HelperChatTarget[Any],
    *,
    target_id: UUID,
    session_id: UUID,
    editing: bool | None = None,
    expected_revision: int | None = None,
    completion_model_id: UUID | None | NotProvided = NOT_PROVIDED,
    reasoning_effort: str | None | NotProvided = NOT_PROVIDED,
) -> OpenedChat:
    """Change the chat's model or reasoning effort, and on a target with
    modes its edit mode, then bring its assistant in line. Entering edit mode
    after a pause starts a new conversation (see
    ``_idle_since_last_activity``)."""
    chat = await load_chat(
        container, target, session_id=session_id, target_id=target_id, lock=True
    )
    if editing is not None:
        modes = _modes_of(target)
        await modes.fence_mode_change(container, target_id, expected_revision)
        if editing:
            await target.require_edit(
                container, target.scoped_request(chat.space_id), target_id
            )
        if chat.editing != editing:
            if editing and await _idle_since_last_activity(container, chat, modes):
                await _start_conversation(container, chat, reason="idle")
            chat.editing = editing
            chat.mode_changed_at = _now()
            await _audit_mode_change(container, chat, modes, reason="requested")
            await _session(container).flush()

    space = await _load_space(container, chat)
    if is_provided(completion_model_id) or is_provided(reasoning_effort):
        await _change_model(
            container,
            chat,
            space,
            completion_model_id=completion_model_id,
            reasoning_effort=reasoning_effort,
        )
    return _opened(chat, await _sync_assistant(container, chat, space))


async def _change_model(
    container: Container,
    chat: HelperChats,
    space: Space,
    *,
    completion_model_id: UUID | None | NotProvided,
    reasoning_effort: str | None | NotProvided,
) -> None:
    target = target_for(chat.target_type)
    new_model_id = (
        completion_model_id
        if is_provided(completion_model_id)
        else chat.completion_model_id
    )
    new_effort = (
        reasoning_effort if is_provided(reasoning_effort) else chat.reasoning_effort
    )
    if is_provided(completion_model_id) and completion_model_id is not None:
        _require_choosable_model(target, space, completion_model_id)
    if is_provided(reasoning_effort) and reasoning_effort is not None:
        model = _chat_models(container, target, space).effective(new_model_id)
        if model is None:
            raise target.refusals.no_model()
        if _offered_reasoning_effort(model, reasoning_effort) != reasoning_effort:
            raise target.refusals.reasoning_effort_unsupported(
                reasoning_effort, model.id
            )
    previous = (chat.completion_model_id, chat.reasoning_effort)
    if previous == (new_model_id, new_effort):
        return
    chat.completion_model_id = new_model_id
    chat.reasoning_effort = new_effort
    if target.audit.model_changed is not None:
        await _audit(
            container,
            target,
            target.audit.model_changed,
            target_id=chat.target_id,
            record=await target.load(container, chat.target_id),
            extra={
                "session_id": str(chat.session_id),
                "completion_model_id": (
                    str(new_model_id) if new_model_id is not None else None
                ),
                "reasoning_effort": new_effort,
            },
        )
    await _session(container).flush()


async def start_new_conversation(
    container: Container,
    target: HelperChatTarget[Any],
    *,
    target_id: UUID,
    session_id: UUID,
) -> OpenedChat:
    """Leave the current conversation behind and continue in a new one."""
    chat = await load_chat(
        container, target, session_id=session_id, target_id=target_id, lock=True
    )
    await target.require_edit(
        container, target.scoped_request(chat.space_id), target_id
    )
    await _start_conversation(container, chat, reason="requested")
    space = await _load_space(container, chat)
    return _opened(chat, _chat_models(container, target, space).default)


async def list_conversations(
    container: Container,
    target: HelperChatTarget[Any],
    *,
    target_id: UUID,
    request: Request,
) -> list[HelperChatConversationPublic]:
    """The caller's conversations in their chat on the target that hold a
    question, the latest question first, at most
    ``CONVERSATION_LIST_LIMIT``; ``request`` is the caller's own.

    The checks are opening's: the target is offered, the caller may edit it,
    and the chat is found as ``load_chat`` finds it. Only the caller's own
    conversations with the chat's hidden assistant in the caller's tenant
    are read, in one query. Nothing is written, so a chat left in edit mode
    stays as it is until it is opened or used."""
    user = container.user()
    await target.require_available(container)
    await target.require_edit(container, request, target_id)
    chat, _ = await _read_chat(
        container,
        target,
        session_id=None,
        assistant_id=None,
        target_id=target_id,
        lock=False,
    )
    first_question = (
        sa.select(sa.func.substr(Questions.question, 1, CONVERSATION_TITLE_LENGTH))
        .where(Questions.session_id == Sessions.id)
        .order_by(Questions.created_at, Questions.id)
        .limit(1)
        .correlate(Sessions)
        .scalar_subquery()
    )
    last_asked = sa.func.max(Questions.created_at)
    rows = (
        await _session(container).execute(
            sa.select(Sessions.id, Sessions.created_at, last_asked, first_question)
            .join(
                Questions,
                sa.and_(
                    Questions.session_id == Sessions.id,
                    Questions.tenant_id == user.tenant_id,
                ),
            )
            .where(
                Sessions.assistant_id == chat.assistant_id,
                Sessions.user_id == user.id,
                Sessions.api_key_id.is_(None),
            )
            .group_by(Sessions.id)
            .order_by(last_asked.desc(), Sessions.id.desc())
            .limit(CONVERSATION_LIST_LIMIT)
        )
    ).all()
    return [
        HelperChatConversationPublic(
            session_id=session_id,
            title=" ".join((title or "").split()),
            started_at=started_at,
            last_asked_at=last_asked_at,
            current=session_id == chat.session_id,
        )
        for session_id, started_at, last_asked_at, title in rows
    ]
