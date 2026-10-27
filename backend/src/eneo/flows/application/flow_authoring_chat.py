"""Session-bound authorization for the ordinary chat used by the flow editor.

A person has one chat per flow: a hidden assistant and the conversation that
is current. Earlier conversations stay with the assistant for traceability,
but only the current one is ever answered or sent to the model, because
``load_authoring_chat`` admits only the session the chat points at.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Iterable, Literal, cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant import AssistantOrigin
from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.flow_authoring_chats_table import FlowAuthoringChats
from eneo.database.tables.flow_tables import Flows
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.flows.api.flow_definition_access import (
    require_flow_current_definition_access,
    require_flow_edit_access,
)
from eneo.flows.application.feature_gate import require_flows_enabled
from eneo.flows.domain.flow_authoring_chat_policy import (
    resolve_flow_authoring_chat_model_id,
)
from eneo.flows.domain.flow_suggestions import (
    FLOW_SUGGESTION_AUTHORING_RULES,
    FlowSuggestionCode,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from eneo.main.exceptions import BadRequestException, NotFoundException
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


_AUTHORING_BASICS = """Help the user configure this flow through the flow tools.
Read the saved definition and revision before changing it. Preserve settings the
user has not asked to change. The tools take the flow's own fields: input_source,
input_type, output_mode and output_type describe a step. Never invent step kinds.

Speak to the person in plain language, as the flow editor does: name steps and
their values with the reference forms, and describe what a step reads and gives.
Never mention revisions, tool names, internal field keys (input_source,
output_mode, metadata_json, output_contract and the like), the "core", the
"kärnan" or other machinery in an answer. When a change is refused, say in plain
words what stands in the way and offer the next step, for example: "Fältet
diarienummer används fortfarande av steg 2, så det kan inte tas bort än. Ska jag
ändra steg 2 först?" Quote a refusal's text only when it helps the person.
Published flows must be unpublished before editing. A refused edit means the
user must enter edit mode or reload the current revision. Do not try to bypass it.
Never ask for credentials or include credentials in tool arguments. Credentials
are configured by the user in the editor. Running a flow is an explicit action;
only start, publish, cancel or approve a run when the user requests that action.
Once run_flow has started a run, the chat shows the run itself beside your
answer: its progress, step by step, and its result when it is done. So say in
one sentence that the run is started and stop there; do not read the run and
do not repeat its result unless the user asks about it.

How a flow works: steps run in order and each step has its own assistant. Only
the first step may read the run (input_source flow_input); a step can also read
previous_step, all_previous_steps, an http_get request or a tool. A first step
that takes uploads (input_type document, audio or file) sets
input_config.runtime_input to {"enabled": true, "input_format": <its input_type>}.
Run form fields are declared in metadata_json.form_schema.fields. output_mode is
what the step delivers (pass_through returns the answer; http_post only on the
last step; template_fill fills a Word template), output_type its form (text,
json, docx, pdf).
In a prompt or input_bindings.question, {{ step_N.output.text }} reads the text of
step N (numbered from 1 in flow order), {{ step_N.output.structured.<field> }} a
field of a JSON step's output_contract, {{ flow_input.<field> }} a run form field
and {{ step_input.text }} the step's own upload. A step reads only earlier steps.
When a later step needs specific facts, let an earlier json step declare them in
its output_contract. Give every step a short, unique name. Publishing checks the
whole flow and names what to fix.
Moving, removing or renaming a step, or renaming a run form field (send
form_field_renames with the new metadata_json), keeps every read pointing where
it pointed: the reads are rewritten, and a change that would leave a read without
its step or field is refused. Change that read first when it is refused.
When two steps share an assistant, update_step with assistant_changes gives the
edited step its own copy and leaves the other step's assistant as it was.
An http_get step (input_source http_get) keeps its request in input_config and
an http_post step in output_config, flat in this shape: {"url": "...",
"auth": {"mode": "none"}, "timeout_seconds": 30, "response_format": "text" or
"json"}; an http_post may add "body": {"mode": "auto"} or {"mode":
"json_template", "template": "..."}. The step decides the method, so there is no
method or headers key. The url and a body template may read
{{ flow_input.<field> }} and earlier steps. Keep auth at {"mode": "none"}:
credentials and custom headers are set by the user in the editor. An HTTP step
without credentials is added through the tools like any other step; it does not
depend on read_tool_options. When a tool refuses a change, the refusal names
what to fix: correct it and try again rather than concluding that the change
is impossible, and do not rely on an earlier refusal in this conversation
without calling the tool again.
"""

_TASK_TO_FLOW = """You build flows; you do not do the work a flow is for. When the user
pastes or describes work to be done (instructions for a task, a prompt written
for an assistant, a procedure, a checklist, a template to fill), they want a
flow that does it, however the message is phrased. Never carry such a task out
in the chat, not even as an example, and never answer it with the result it
asks for. Read it as a specification instead: what comes in (a run form field,
an upload, a document), the parts the work falls into and what each part gives
the next, what should come out and in which form, and where a person should
review. In edit mode, build it: a step per part with its own instruction
written from the user's text, its reads and its result, the run form fields
it needs, and a name for each step; then say in a few sentences what the flow
does, step by step, and what to try it with. Make one step of work that is
one judgment, and a step of its own where a result is used again later, where
the format changes (text to structured values, a file), or where a person
reviews. When the user's text is short enough to be one step, one step is
right; do not pad. When edit mode is off, describe the steps you would build
in plain words and offer to build them once edit mode is on.
"""

_SUGGESTIONS_INTRODUCED = """After a change, the tool result lists under introduced_suggestions the
suggestions the change introduced against these rules. Resolve each in the same
turn, with
apply_flow_suggestions for a fix whose fix.kind is patch and otherwise by
adjusting the step with update_step, unless the user explicitly asked for that
shape. Then tell the user in one plain sentence what you adjusted and why.
"""

_SUGGESTIONS_ON_REQUEST = """When the user asks to optimize or simplify the flow or make it cheaper, call
read_flow_suggestions first. Explain each finding in plain words with its
impact: which step receives which earlier result twice and through which
reads. When the tool reports no suggestions, that is good news: say in a
sentence or two that the flow looks well put together and that the check
found nothing to make cheaper or simpler, in a glad tone, never an apology.
Do not then list the kinds of problems the check looks for. Never claim a
duplication the tool did not report, and never say the
flow is free of them beyond what it reported. Suggestions never block
publishing. For these findings about the flow as it was, change nothing until
the user agrees, and then only what they agreed to. A finding whose fix.kind is
patch is fixed with apply_flow_suggestions in edit mode, every agreed fix in one
call; when the user asks to fix everything, that means every patch fix the tool
reported. Any other finding you propose as a concrete change and make with
update_step. When numbers from past runs would help the user choose, call
read_flow_suggestions with include_runs and say what they mean in plain words,
such as how many tokens a duplicate costs per run; never state a number the
tool did not give. Hide a suggestion with dismiss_flow_suggestion only when the
user asks you to hide or ignore it, never on your own judgement; it is then
hidden for everyone who edits the flow, and read_flow_suggestions says how many
are hidden.
"""


def _suggestion_rules() -> str:
    """The catalogue's authoring rules, one per suggestion code."""
    return "".join(
        textwrap.fill(
            FLOW_SUGGESTION_AUTHORING_RULES[code],
            width=80,
            initial_indent="- ",
            subsequent_indent="  ",
        )
        + "\n"
        for code in FlowSuggestionCode
    )


AUTHORING_INSTRUCTIONS = (
    _AUTHORING_BASICS
    + _TASK_TO_FLOW
    + "Design every step by these rules from the start:\n"
    + _suggestion_rules()
    + _SUGGESTIONS_INTRODUCED
    + _SUGGESTIONS_ON_REQUEST
)


class FlowAuthoringChatPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    flow_id: UUID
    assistant_id: UUID
    session_id: UUID = Field(
        description=(
            "The chat's current conversation. Starting a new conversation "
            "(explicitly, or by entering edit mode after a pause) replaces it; "
            "earlier conversations are kept but never answered again."
        )
    )
    editing: bool
    completion_model_id: UUID | None = Field(
        default=None,
        description=(
            "The model the caller chose for this chat; null follows the default "
            "(`default_completion_model_id`)."
        ),
    )
    reasoning_effort: str | None = Field(
        default=None,
        description=(
            "The reasoning effort the caller chose; null uses the model's own "
            "default. Applied only when the chat's model offers that level."
        ),
    )
    default_completion_model_id: UUID | None = Field(
        default=None,
        description=(
            "The model the chat answers with while `completion_model_id` is "
            "null: the organisation's default for flow chats when this space "
            "allows it, else the space's default among models that support tools."
        ),
    )


def scoped_request(space_id: UUID) -> Request:
    from eneo.internal_mcp.foundation import request_for_bound_space

    return request_for_bound_space(space_id)


async def load_authoring_chat(
    container: Container,
    *,
    session_id: UUID,
    assistant_id: UUID | None = None,
    flow_id: UUID | None = None,
    lock: bool = False,
) -> FlowAuthoringChats:
    user = container.user()
    await require_flows_enabled(container.feature_flag_service(), user.tenant_id)
    query = (
        sa.select(FlowAuthoringChats)
        .join(Sessions, Sessions.id == FlowAuthoringChats.session_id)
        .join(Assistants, Assistants.id == FlowAuthoringChats.assistant_id)
        .join(Flows, Flows.id == FlowAuthoringChats.flow_id)
        .where(
            FlowAuthoringChats.tenant_id == user.tenant_id,
            FlowAuthoringChats.user_id == user.id,
            FlowAuthoringChats.session_id == session_id,
            Sessions.user_id == user.id,
            Sessions.api_key_id.is_(None),
            Sessions.assistant_id == FlowAuthoringChats.assistant_id,
            Assistants.space_id == FlowAuthoringChats.space_id,
            Assistants.hidden.is_(True),
            Assistants.origin == AssistantOrigin.USER,
            Flows.tenant_id == user.tenant_id,
            Flows.space_id == FlowAuthoringChats.space_id,
            Flows.deleted_at.is_(None),
        )
    )
    if assistant_id is not None:
        query = query.where(FlowAuthoringChats.assistant_id == assistant_id)
    if flow_id is not None:
        query = query.where(FlowAuthoringChats.flow_id == flow_id)
    chat = await _session(container).scalar(query)
    if chat is None:
        raise NotFoundException("Flow authoring chat not found.")
    request = scoped_request(chat.space_id)
    await require_flow_current_definition_access(
        request, container, flow_id=chat.flow_id
    )
    if lock:
        # Every writer locks the flow before its chat/assistants, including
        # mode changes, so leaving edit mode fences an in-flight tool call.
        await _session(container).scalar(
            sa.select(Flows.id)
            .where(
                Flows.tenant_id == user.tenant_id,
                Flows.id == chat.flow_id,
            )
            .with_for_update()
        )
        chat = await _session(container).scalar(
            query.with_for_update(of=FlowAuthoringChats).execution_options(
                populate_existing=True
            )
        )
        if chat is None:
            raise NotFoundException("Flow authoring chat not found.")
    return chat


async def require_authoring_edit(
    container: Container, chat: FlowAuthoringChats
) -> None:
    if not chat.editing:
        raise BadRequestException(
            "Enter edit mode in the flow editor before changing this flow."
        )
    await require_flow_edit_access(
        scoped_request(chat.space_id), container, flow_id=chat.flow_id
    )


# --- The chat's model -------------------------------------------------------


@dataclass(frozen=True)
class _ChatModels:
    """The models a flow chat in one space may answer with."""

    usable: list[CompletionModel]
    default: CompletionModel | None

    def get(self, model_id: UUID | None) -> CompletionModel | None:
        return next((model for model in self.usable if model.id == model_id), None)

    def effective(self, chosen_id: UUID | None) -> CompletionModel | None:
        """The person's model while the space allows it, else the default."""
        return self.get(chosen_id) or self.default


def _chat_models(container: Container, space: Space) -> _ChatModels:
    # The space's usable models are those enabled in it that meet its
    # classification, the same list an ordinary assistant's model comes from.
    usable = [
        model
        for model in space.completion_models
        if model.can_access and model.supports_tool_calling
    ]
    tenant = getattr(container.user(), "tenant", None)
    organisation_default = resolve_flow_authoring_chat_model_id(
        cast(dict[str, Any] | None, getattr(tenant, "flow_settings", None))
    )
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


def _require_choosable_model(space: Space, model_id: UUID) -> CompletionModel:
    """The model a person asks for, refused the way an assistant's model is."""
    if space.is_completion_model_available(model_id):
        model = space.get_completion_model(model_id)
        if not model.supports_tool_calling:
            raise FlowBadRequestException(
                "The flow chat needs a model that supports tools.",
                code=FlowApiErrorCode.AUTHORING_MODEL_WITHOUT_TOOLS,
                context={"completion_model_id": str(model_id)},
            )
        return model
    if any(
        model.id == model_id and model.can_access
        for model in space.completion_models_below_classification
    ):
        raise FlowBadRequestException(
            "The model's security classification is below the space's.",
            code=FlowApiErrorCode.AUTHORING_MODEL_BELOW_CLASSIFICATION,
            context={"completion_model_id": str(model_id)},
        )
    raise FlowBadRequestException(
        "The model is not enabled in the flow's space.",
        code=FlowApiErrorCode.AUTHORING_MODEL_NOT_IN_SPACE,
        context={"completion_model_id": str(model_id)},
    )


def _no_model() -> FlowBadRequestException:
    return FlowBadRequestException(
        "Choose a default model that supports tools for this space.",
        code=FlowApiErrorCode.AUTHORING_CHAT_NO_MODEL,
    )


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


async def _load_space(container: Container, chat: FlowAuthoringChats) -> Space:
    return await container.space_repo().one(
        id=chat.space_id, hidden_assistant_ids={chat.assistant_id}
    )


async def _sync_assistant(
    container: Container, chat: FlowAuthoringChats, space: Space | None = None
) -> CompletionModel | None:
    """Give the chat's assistant the current instructions and the model and
    reasoning effort in force; write only what differs. Returns the default."""
    space = space or await _load_space(container, chat)
    models = _chat_models(container, space)
    model = models.effective(chat.completion_model_id)
    if model is None:
        raise _no_model()
    assistant = space.get_assistant(assistant_id=chat.assistant_id)
    changes: dict[str, Any] = {}
    if assistant.get_prompt_text() != AUTHORING_INSTRUCTIONS:
        changes["prompt"] = PromptCreate(text=AUTHORING_INSTRUCTIONS)
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
    # A file uploaded in the chat is looked up through the files tool where
    # the model needs it, not put whole in the prompt: the chat is shown
    # long material (a letter, a transcript) to build a flow around. A model
    # without tool calling gets the text inlined anyway.
    if assistant.inline_file_text:
        changes["inline_file_text"] = False
    # The tool runtime's functions, as far as the space offers them and a
    # provider is ready; a space setting that changed is followed here.
    states = await capability_availability(
        _session(container), chat.tenant_id, space.security_classification
    )
    wanted = tool_runtime_capabilities(space.enabled_capabilities, states)
    if sorted(wanted) != sorted(assistant.enabled_capabilities):
        changes["enabled_capabilities"] = wanted
    if changes:
        await container.assistant_service().update_assistant(
            assistant_id=chat.assistant_id,
            update=AssistantUpdateCommand(**changes),
            include_hidden=True,
        )
    return models.default


def _public(
    chat: FlowAuthoringChats, default: CompletionModel | None
) -> FlowAuthoringChatPublic:
    return FlowAuthoringChatPublic(
        flow_id=chat.flow_id,
        assistant_id=chat.assistant_id,
        session_id=chat.session_id,
        editing=chat.editing,
        completion_model_id=chat.completion_model_id,
        reasoning_effort=chat.reasoning_effort,
        default_completion_model_id=default.id if default is not None else None,
    )


# --- Conversations ----------------------------------------------------------

ConversationReason = Literal["requested", "idle"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _idle_since_last_activity(
    container: Container, chat: FlowAuthoringChats
) -> bool:
    """Whether the current conversation has questions and none of them, nor a
    mode change, is newer than the idle threshold. An empty conversation is
    never replaced: there is nothing in it to leave behind."""
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
    idle = timedelta(minutes=get_settings().flow_authoring_chat_idle_minutes)
    return _now() - last_activity > idle


async def _start_conversation(
    container: Container, chat: FlowAuthoringChats, *, reason: ConversationReason
) -> None:
    """Point the chat at a new, empty conversation with the same assistant."""
    user = container.user()
    flow = await container.flow_service().get_flow(chat.flow_id)
    previous = chat.session_id
    # The caller's transaction, as when the chat was created.
    conversation = await container.session_repo().add(
        SessionAdd(name=flow.name, user_id=user.id, assistant_id=chat.assistant_id)
    )
    chat.session_id = conversation.id
    await _session(container).flush()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_AUTHORING_CONVERSATION_STARTED,
        entity_type=EntityType.FLOW,
        entity_id=chat.flow_id,
        description="Started a new conversation in a flow authoring chat.",
        metadata=AuditMetadata.standard(
            actor=user,
            target=flow,
            extra={
                "session_id": str(conversation.id),
                "previous_session_id": str(previous),
                "reason": reason,
            },
        ),
    )


# --- Entry points -----------------------------------------------------------


async def get_or_create_authoring_chat(
    container: Container, *, flow_id: UUID, request: Request
) -> FlowAuthoringChatPublic:
    user = container.user()
    await require_flows_enabled(container.feature_flag_service(), user.tenant_id)
    access = await require_flow_edit_access(request, container, flow_id=flow_id)
    await _session(container).scalar(
        sa.select(Flows.id)
        .where(
            Flows.tenant_id == user.tenant_id,
            Flows.id == flow_id,
        )
        .with_for_update()
    )
    existing = await _session(container).scalar(
        sa.select(FlowAuthoringChats).where(
            FlowAuthoringChats.tenant_id == user.tenant_id,
            FlowAuthoringChats.user_id == user.id,
            FlowAuthoringChats.flow_id == flow_id,
        )
    )
    if existing is not None:
        chat = await load_authoring_chat(
            container, session_id=existing.session_id, flow_id=flow_id
        )
        return _public(chat, await _sync_assistant(container, chat))
    space = await container.space_repo().one(id=access.flow.space_id)
    if _chat_models(container, space).default is None:
        raise _no_model()
    assistant, _ = await container.assistant_service().create_assistant(
        name=access.flow.name,
        space_id=access.flow.space_id,
        hidden=True,
    )
    # Use the caller's transaction: SessionService.create_session commits in
    # a separate transaction, which cannot yet see this newly created parent.
    conversation = await container.session_repo().add(
        SessionAdd(
            name=access.flow.name,
            user_id=user.id,
            assistant_id=assistant.id,
        )
    )
    chat = (
        await _session(container).scalars(
            sa.insert(FlowAuthoringChats)
            .values(
                tenant_id=user.tenant_id,
                user_id=user.id,
                flow_id=flow_id,
                space_id=access.flow.space_id,
                assistant_id=assistant.id,
                session_id=conversation.id,
                editing=False,
            )
            .returning(FlowAuthoringChats)
        )
    ).one()
    default = await _sync_assistant(container, chat)
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_AUTHORING_CHAT_CREATED,
        entity_type=EntityType.FLOW,
        entity_id=flow_id,
        description="Created a flow authoring chat.",
        metadata=AuditMetadata.standard(
            actor=user,
            target=access.flow,
            extra={
                "assistant_id": str(assistant.id),
                "session_id": str(conversation.id),
            },
        ),
    )
    return _public(chat, default)


async def update_authoring_chat(
    container: Container,
    *,
    flow_id: UUID,
    session_id: UUID,
    editing: bool | None = None,
    expected_revision: int | None = None,
    completion_model_id: UUID | None | NotProvided = NOT_PROVIDED,
    reasoning_effort: str | None | NotProvided = NOT_PROVIDED,
) -> FlowAuthoringChatPublic:
    """Change the chat's edit mode, model or reasoning effort, then bring its
    assistant in line. Entering edit mode after a pause starts a new
    conversation (see ``_idle_since_last_activity``)."""
    chat = await load_authoring_chat(
        container, session_id=session_id, flow_id=flow_id, lock=True
    )
    user = container.user()
    service = container.flow_service()
    if editing is not None:
        if expected_revision is None:
            raise BadRequestException(
                "Send expected_revision with editing: a mode change is fenced "
                "on the draft revision the caller last read."
            )
        await service.reserve_draft_revision(
            flow_id=flow_id, expected_revision=expected_revision
        )
        if editing:
            await require_flow_edit_access(
                scoped_request(chat.space_id), container, flow_id=flow_id
            )
        if chat.editing != editing:
            if editing and await _idle_since_last_activity(container, chat):
                await _start_conversation(container, chat, reason="idle")
            chat.editing = editing
            chat.mode_changed_at = _now()
            await container.audit_service().log_async(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action=ActionType.FLOW_AUTHORING_MODE_CHANGED,
                entity_type=EntityType.FLOW,
                entity_id=flow_id,
                description="Changed flow authoring edit mode.",
                metadata=AuditMetadata.standard(
                    actor=user,
                    target=await service.get_flow(flow_id),
                    extra={
                        "session_id": str(chat.session_id),
                        "editing": editing,
                    },
                ),
            )
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
    return _public(chat, await _sync_assistant(container, chat, space))


async def _change_model(
    container: Container,
    chat: FlowAuthoringChats,
    space: Space,
    *,
    completion_model_id: UUID | None | NotProvided,
    reasoning_effort: str | None | NotProvided,
) -> None:
    new_model_id = (
        completion_model_id
        if is_provided(completion_model_id)
        else chat.completion_model_id
    )
    new_effort = (
        reasoning_effort if is_provided(reasoning_effort) else chat.reasoning_effort
    )
    if is_provided(completion_model_id) and completion_model_id is not None:
        _require_choosable_model(space, completion_model_id)
    if is_provided(reasoning_effort) and reasoning_effort is not None:
        model = _chat_models(container, space).effective(new_model_id)
        if model is None:
            raise _no_model()
        if _offered_reasoning_effort(model, reasoning_effort) != reasoning_effort:
            raise FlowBadRequestException(
                "The chat's model does not offer this reasoning effort.",
                code=FlowApiErrorCode.AUTHORING_REASONING_EFFORT_UNSUPPORTED,
                context={
                    "reasoning_effort": reasoning_effort,
                    "completion_model_id": str(model.id),
                },
            )
    previous = (chat.completion_model_id, chat.reasoning_effort)
    if previous == (new_model_id, new_effort):
        return
    chat.completion_model_id = new_model_id
    chat.reasoning_effort = new_effort
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_AUTHORING_CHAT_MODEL_CHANGED,
        entity_type=EntityType.FLOW,
        entity_id=chat.flow_id,
        description="Changed the model of a flow authoring chat.",
        metadata=AuditMetadata.standard(
            actor=user,
            target=await container.flow_service().get_flow(chat.flow_id),
            extra={
                "session_id": str(chat.session_id),
                "completion_model_id": (
                    str(new_model_id) if new_model_id is not None else None
                ),
                "reasoning_effort": new_effort,
            },
        ),
    )
    await _session(container).flush()


async def start_authoring_conversation(
    container: Container, *, flow_id: UUID, session_id: UUID
) -> FlowAuthoringChatPublic:
    """Leave the current conversation behind and continue in a new one."""
    chat = await load_authoring_chat(
        container, session_id=session_id, flow_id=flow_id, lock=True
    )
    await require_flow_edit_access(
        scoped_request(chat.space_id), container, flow_id=flow_id
    )
    await _start_conversation(container, chat, reason="requested")
    space = await _load_space(container, chat)
    return _public(chat, _chat_models(container, space).default)
