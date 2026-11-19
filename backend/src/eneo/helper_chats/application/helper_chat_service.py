"""Session-bound authorization and upkeep of a helper chat, for every target.

A person has one chat per target: a hidden assistant and the conversation
that is current. Earlier conversations stay with the assistant for
traceability, but only the current one is ever answered or sent to the model,
because ``load_chat`` admits only the session the chat points at. What the
chat helps with, who may read and change it and how its audit entries read
is the target's (``helper_chats.targets``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import Request
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
    return target.has_modes and chat.editing


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
    user = container.user()
    await target.require_available(container)
    query = (
        sa.select(HelperChats)
        .join(Sessions, Sessions.id == HelperChats.session_id)
        .join(Assistants, Assistants.id == HelperChats.assistant_id)
        .where(
            HelperChats.tenant_id == user.tenant_id,
            HelperChats.user_id == user.id,
            HelperChats.session_id == session_id,
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
    await _leave_edit_mode_after_pause(container, chat)
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
    """Edit mode and edit access to the chat's ``target``, and with
    ``change`` also a target that may change right now, so a change it
    refuses is refused before anything is read or written."""
    if not in_edit_mode(target, chat):
        raise target.refusals.not_editing()
    await _require_edit_access(container, target, chat, change=change)


async def require_approved_change(
    container: Container, target: HelperChatTarget[Any], chat: HelperChats
) -> None:
    """What a change the person approves in the chat before it runs (such as
    publishing) needs: edit access to a target that may change right now,
    and on a target with modes edit mode too. A chat on a target without
    modes never writes by itself, so there the approval takes its place."""
    if target.has_modes:
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
    """Give the chat's assistant look-up mode for uploads and the tool
    runtime's functions its space offers. Each goes in an update of its own:
    a refusal (a provider that stopped meeting the space's classification, a
    tool set that does not fit the model) is logged and leaves the chat as it
    is, and never takes the other setting with it."""
    # A file uploaded in the chat is looked up through the files tool where
    # the model needs it, not put whole in the prompt: the chat is shown
    # long material (a letter, a transcript) to work from. A model without
    # tool calling gets the text inlined anyway.
    if assistant.inline_file_text:
        await _update_tools(container, chat, "look-up mode", inline_file_text=False)
    # The tool runtime's functions, as far as the space offers them and a
    # provider is ready; a space setting that changed is followed here.
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


async def _idle_since_last_activity(container: Container, chat: HelperChats) -> bool:
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
    return _now() - last_activity > target_for(chat.target_type).idle_after()


async def _leave_edit_mode_after_pause(container: Container, chat: HelperChats) -> None:
    """Turn edit mode off when the conversation has been idle, so a person who
    comes back after the pause asks in view mode until they turn edit mode on.
    A chat on a target without modes is never in edit mode, so nothing here
    applies to it.

    ``mode_changed_at`` is left as it is: the idle measure counts the person's
    own activity, so turning edit mode on after this still starts a new
    conversation. The update matches only the chat as it was read, so a mode
    change or a new conversation saved meanwhile is kept."""
    if not in_edit_mode(target_for(chat.target_type), chat):
        return
    if not await _idle_since_last_activity(container, chat):
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
    await _audit_mode_change(container, chat, reason="idle")


async def _audit_mode_change(
    container: Container, chat: HelperChats, *, reason: ChangeReason
) -> None:
    """The one audit entry for a change of edit mode, the person's or the
    pause's, with the mode the chat is now in."""
    target = target_for(chat.target_type)
    if target.audit.mode_changed is None:
        return
    await _audit(
        container,
        target,
        target.audit.mode_changed,
        target_id=chat.target_id,
        record=await target.load(container, chat.target_id),
        extra={
            "session_id": str(chat.session_id),
            "editing": chat.editing,
            "reason": reason,
        },
    )


async def _start_conversation(
    container: Container, chat: HelperChats, *, reason: ChangeReason
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
) -> OpenedChat:
    """The caller's chat on the target, made on first use with its hidden
    assistant and first conversation; ``request`` is the caller's own."""
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
                editing=target.starts_in_edit_mode(record),
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
    """Change the chat's edit mode, model or reasoning effort, then bring its
    assistant in line. Entering edit mode after a pause starts a new
    conversation (see ``_idle_since_last_activity``). A chat on a target
    without modes refuses any ``editing``."""
    chat = await load_chat(
        container, target, session_id=session_id, target_id=target_id, lock=True
    )
    if editing is not None:
        if not target.has_modes:
            raise target.refusals.no_modes()
        await target.fence_mode_change(container, target_id, expected_revision)
        if editing:
            await target.require_edit(
                container, target.scoped_request(chat.space_id), target_id
            )
        if chat.editing != editing:
            if editing and await _idle_since_last_activity(container, chat):
                await _start_conversation(container, chat, reason="idle")
            chat.editing = editing
            chat.mode_changed_at = _now()
            await _audit_mode_change(container, chat, reason="requested")
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
