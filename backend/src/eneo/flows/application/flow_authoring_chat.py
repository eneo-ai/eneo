"""Session-bound authorization for the ordinary chat used by the flow editor."""

from __future__ import annotations

from typing import cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.assistants.assistant import AssistantOrigin
from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.flow_authoring_chats_table import FlowAuthoringChats
from eneo.database.tables.flow_tables import Flows
from eneo.database.tables.sessions_table import Sessions
from eneo.flows.api.flow_definition_access import (
    require_flow_current_definition_access,
    require_flow_edit_access,
)
from eneo.flows.application.feature_gate import require_flows_enabled
from eneo.main.container.container import Container
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.prompts.api.prompt_models import PromptCreate
from eneo.sessions.session import SessionAdd


def _session(container: Container) -> AsyncSession:
    return cast(AsyncSession, container.session())


AUTHORING_INSTRUCTIONS = """Help the user configure this flow through the flow tools.
Read the saved definition and revision before changing it. Preserve settings the
user has not asked to change. The tools use the existing flow core: input_source,
input_type, output_mode and output_type describe a step. Never invent step kinds.
Published flows must be unpublished before editing. A refused edit means the
user must enter edit mode or reload the current revision. Do not try to bypass it.
Never ask for credentials or include credentials in tool arguments. Credentials
are configured by the user in the editor. Running a flow is an explicit action;
only start, publish, cancel or approve a run when the user requests that action.

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
"""


class FlowAuthoringChatPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    flow_id: UUID
    assistant_id: UUID
    session_id: UUID
    editing: bool


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
        return FlowAuthoringChatPublic.model_validate(chat)
    assistant, _ = await container.assistant_service().create_assistant(
        name=access.flow.name,
        space_id=access.flow.space_id,
        hidden=True,
    )
    if (
        assistant.completion_model is None
        or not assistant.completion_model.supports_tool_calling
    ):
        raise BadRequestException(
            "Choose a default model that supports tools for this space."
        )
    await container.assistant_service().update_assistant(
        assistant_id=assistant.id,
        update=AssistantUpdateCommand(prompt=PromptCreate(text=AUTHORING_INSTRUCTIONS)),
        include_hidden=True,
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
    return FlowAuthoringChatPublic.model_validate(chat)


async def set_authoring_mode(
    container: Container,
    *,
    flow_id: UUID,
    session_id: UUID,
    editing: bool,
    expected_revision: int,
) -> FlowAuthoringChatPublic:
    chat = await load_authoring_chat(
        container, session_id=session_id, flow_id=flow_id, lock=True
    )
    service = container.flow_service()
    await service.reserve_draft_revision(
        flow_id=flow_id, expected_revision=expected_revision
    )
    if editing:
        await require_flow_edit_access(
            scoped_request(chat.space_id), container, flow_id=flow_id
        )
    if chat.editing != editing:
        chat.editing = editing
        user = container.user()
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
                    "session_id": str(session_id),
                    "editing": editing,
                },
            ),
        )
        await _session(container).flush()
    return FlowAuthoringChatPublic.model_validate(chat)
