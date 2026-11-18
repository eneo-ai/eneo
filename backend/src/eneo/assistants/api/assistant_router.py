from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from eneo.assistants.api import assistant_protocol
from eneo.assistants.api.assistant_models import (
    AskAssistant,
    AssistantCreatePublic,
    AssistantPublic,
    AssistantUpdatePublic,
    AssistantWidgetStatus,
)
from eneo.assistants.application.assistant_guards import (
    raise_if_flow_managed as _raise_if_flow_managed,
)
from eneo.assistants.application.assistant_guards import (
    raise_if_helper_chat as _raise_if_helper_chat,
)
from eneo.assistants.application.assistant_publish_operation import (
    apply_assistant_publish,
)
from eneo.assistants.application.assistant_update_operation import (
    apply_assistant_update,
)

# Audit logging - module level imports for consistency
from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.entity_types import EntityType
from eneo.authentication.auth_dependencies import (
    get_scope_filter,
    require_resource_permission_for_method,
    require_user_for_creation,
)
from eneo.authentication.auth_models import audit_actor_for
from eneo.authentication.endpoint_access import (
    Authentication,
    Authorization,
    endpoint_access,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import NotFoundException
from eneo.main.models import (
    CursorPaginatedResponse,
    PaginatedResponse,
)
from eneo.prompts.api.prompt_models import PromptSparse
from eneo.server import protocol
from eneo.server.dependencies.container import get_container
from eneo.server.protocol import responses
from eneo.sessions.session import (
    AskResponse,
    SessionFeedback,
    SessionMetadataPublic,
    SessionPublic,
)
from eneo.sessions.session_protocol import (
    to_session_metadata_paginated_response,
    to_session_public,
)
from eneo.spaces.api.space_models import TransferRequest

router = APIRouter()
_ASSISTANT_ACCESS_REASON = (
    "AssistantService enforces assistant permissions and space membership."
)
ApiKeyRevokingContainer = Annotated[
    Container,
    Depends(get_container(with_user=True, transaction_scope="function")),
]


@router.post(
    "/",
    response_model=AssistantPublic,
    description="Create a new assistant in a space.",
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def create_assistant(
    request: Request,
    assistant: AssistantCreatePublic,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    _user_for_creation: None = Depends(require_user_for_creation),
):
    # Scope validation: scoped keys cannot create assistants outside their scope
    scope_filter = get_scope_filter(request)
    if scope_filter.space_id is not None:
        if scope_filter.space_id != assistant.space_id:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "insufficient_scope",
                    "message": (
                        f"API key is scoped to space '{scope_filter.space_id}'. "
                        f"Cannot create assistant in space '{assistant.space_id}'."
                    ),
                },
            )

    assistant_service = container.assistant_service()
    assembler = container.assistant_assembler()
    current_user = container.user()

    # Create assistant
    created_assistant, permissions = await assistant_service.create_assistant(
        name=assistant.name,
        space_id=assistant.space_id,
        enabled_capabilities=assistant.enabled_capabilities,
    )

    # Get space for context
    space = None
    if created_assistant.space_id:
        try:
            space_service = container.space_service()
            space = await space_service.get_space(created_assistant.space_id)
        except Exception:
            space = None

    # Build extra context for assistant configuration
    extra = {
        "type": created_assistant.type.value if created_assistant.type else "standard",
        "configuration": {
            "enabled_capabilities": created_assistant.enabled_capabilities,
            "model": created_assistant.completion_model.nickname
            if created_assistant.completion_model
            else None,
            "temperature": created_assistant.completion_model_kwargs.temperature
            if created_assistant.completion_model_kwargs
            else None,
            "top_p": created_assistant.completion_model_kwargs.top_p
            if created_assistant.completion_model_kwargs
            else None,
            "data_retention_days": created_assistant.data_retention_days,
            "insights_enabled": created_assistant.insight_enabled
            if hasattr(created_assistant, "insight_enabled")
            else None,
            "published": created_assistant.published,
        },
    }

    created_assistant_id = created_assistant.id
    assert created_assistant_id is not None

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        user=current_user,
        action=ActionType.ASSISTANT_CREATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=created_assistant_id,
        description=f"Created assistant '{created_assistant.name}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=created_assistant,
            space=space,
            extra=extra,
        ),
    )

    return assembler.from_assistant_to_model(created_assistant, permissions=permissions)


@router.get(
    "/",
    response_model=PaginatedResponse[AssistantPublic],
    description="List assistants. Requires Admin permission if `for_tenant` is `true`.",
    responses=responses.get_responses([403]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=(
        "Lists caller-created assistants. Tenant-wide listing requires admin "
        "permission and rejects resource-scoped API keys."
    ),
)
async def get_assistants(
    request: Request,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    name: str | None = None,
    for_tenant: bool = False,
):
    """Requires Admin permission if `for_tenant` is `true`."""
    scope_filter = get_scope_filter(request)

    # Assistant-scoped keys must not bypass scope via for_tenant
    if (
        for_tenant
        and scope_filter.scope_type is not None
        and scope_filter.scope_type != "tenant"
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "insufficient_scope",
                "message": (
                    "Scoped API keys cannot use for_tenant=true. "
                    "This parameter requires a tenant-scoped key or bearer auth."
                ),
            },
        )

    service = container.assistant_service()
    assembler = container.assistant_assembler()

    assistants = await service.get_assistants(
        name,
        for_tenant,
        space_id_filter=scope_filter.space_id,
        assistant_id_filter=scope_filter.assistant_id,
    )

    assistants = [
        assembler.from_assistant_to_model(assistant)
        for assistant in assistants
        if assistant.completion_model is not None
    ]

    return protocol.to_paginated_response(assistants)


async def _assistant_response(
    container: Container, assistant_id: UUID
) -> AssistantPublic:
    """Single serialization path for an assistant response.

    Always resolves and attaches effective_config, so no endpoint can forget it
    — a personal default assistant returned without it makes the chat UI drop
    governance filtering (show every model/MCP server). Used by GET and update.
    """
    service = container.assistant_service()
    assembler = container.assistant_assembler()
    (
        assistant,
        permissions,
        effective_config,
    ) = await service.get_assistant_with_effective_config(assistant_id=assistant_id)
    is_help_assistant = await service.is_help_assistant(assistant_id=assistant_id)
    return assembler.from_assistant_to_model(
        assistant=assistant,
        permissions=permissions,
        effective_config=effective_config,
        is_help_assistant=is_help_assistant,
    )


@router.get(
    "/{id}/",
    response_model=AssistantPublic,
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def get_assistant(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    await _raise_if_helper_chat(container, id, owner_may_read=True)
    return await _assistant_response(container, id)


@router.get(
    "/{id}/widget-status/",
    response_model=AssistantWidgetStatus,
    description=(
        "Whether an active web widget publishes the assistant, for anyone who "
        "can read it. Says nothing else about the widget. Requires a session token."
    ),
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.SESSION,
    authorization=Authorization.AUTHENTICATED,
    reason=(
        "Assistant readers learn whether a widget publishes the assistant;"
        " AssistantService enforces read access, and the session-only policy"
        " keeps widgets invisible to API keys."
    ),
)
async def get_assistant_widget_status(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    await _raise_if_helper_chat(container, id, owner_may_read=True)
    assistant, _ = await container.assistant_service().get_assistant(id)
    return AssistantWidgetStatus(
        serves_active_widget=await container.widget_repo().serves_target(
            tenant_id=container.user().tenant_id, target_id=assistant.id
        )
    )


@router.post(
    "/{id}/",
    response_model=AssistantPublic,
    responses=responses.get_responses([400, 403, 404]),
    description=(
        "Update an assistant. Omitting a field leaves it unchanged, and so "
        "does null for every field except these: Null clears description, "
        "metadata_json, icon_id and data_retention_days. Null "
        "completion_model_kwargs resets the model settings to their defaults. "
        "An empty list clears a list field (groups, websites, attachments, "
        "integration_knowledge_list, mcp_servers, mcp_tools, "
        "enabled_capabilities, skill_bindings)."
    ),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def update_assistant(
    id: UUID,
    assistant: AssistantUpdatePublic,
    request: Request,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Omitted and null fields are not updated; see the route description."""
    if (
        assistant.skill_bindings is not None
        and getattr(request.state, "api_key", None) is not None
    ):
        raise HTTPException(
            status_code=403,
            detail="Skill binding changes require a session token.",
        )

    await apply_assistant_update(container, assistant_id=id, update=assistant)

    # Re-resolve through the shared response path so the body carries the
    # governance effective_config (same as GET /{id}/ and the space endpoint).
    # Without it a personal default-assistant update returns effective_config=None
    # and the chat UI falls back to showing every model and MCP server.
    return await _assistant_response(container, id)


@router.delete(
    "/{id}/",
    status_code=204,
    description="Delete an assistant.",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def delete_assistant(
    id: UUID,
    container: ApiKeyRevokingContainer,
):
    await _raise_if_helper_chat(container, id)
    service = container.assistant_service()
    current_user = container.user()

    # Get assistant details BEFORE deletion (snapshot pattern)
    assistant, _ = await service.get_assistant(id)
    _raise_if_flow_managed(assistant, id)

    # Get space for context before deletion
    space = None
    if assistant.space_id:
        try:
            space_service = container.space_service()
            space = await space_service.get_space(assistant.space_id)
        except Exception:
            space = None

    # Delete assistant
    await service.delete_assistant(id)

    # Build extra context capturing what was deleted (for incident investigation)
    extra = {
        "type": assistant.type.value if assistant.type else "standard",
        "impact": {
            "knowledge_sources": {
                "collections": len(assistant.collections)
                if assistant.collections
                else 0,
                "websites": len(assistant.websites) if assistant.websites else 0,
                "integrations": len(assistant.integration_knowledge_list)
                if assistant.integration_knowledge_list
                else 0,
            },
            "configuration": {
                "model": assistant.completion_model.nickname
                if assistant.completion_model
                else None,
                "temperature": assistant.completion_model_kwargs.temperature
                if assistant.completion_model_kwargs
                else None,
                "top_p": assistant.completion_model_kwargs.top_p
                if assistant.completion_model_kwargs
                else None,
                "data_retention_days": assistant.data_retention_days,
                "published": assistant.published,
            },
            "created_at": assistant.created_at.isoformat()
            if assistant.created_at
            else None,
        },
    }

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        user=current_user,
        action=ActionType.ASSISTANT_DELETED,
        entity_type=EntityType.ASSISTANT,
        entity_id=id,
        description=f"Deleted assistant '{assistant.name}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=assistant,
            space=space,
            extra=extra,
        ),
    )


@router.post(
    "/{id}/sessions/",
    response_model=AskResponse,
    description="Ask an assistant and start a new session. Streams the response as Server-Sent Events if `stream` is `true`.",
    responses=responses.streaming_response(AskResponse, [400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.ASSISTANT,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def ask_assistant(
    id: UUID,
    ask: AskAssistant,
    container: Annotated[
        Container,
        Depends(get_container(with_user_from_assistant_api_key=True)),
    ],
    version: Annotated[int, Query(ge=1, le=2)] = 1,
):
    """Streams the response as Server-Sent Events if stream == true"""
    service = container.assistant_service()
    user = container.user()

    file_ids = list(ask.files)
    tool_assistant_id = None
    if ask.tools is not None and ask.tools.assistants:
        tool_assistant_id = ask.tools.assistants[0].id
    response = await service.ask(
        question=ask.question,
        disabled_capabilities=ask.disabled_capabilities,
        disabled_mcp_server_ids=ask.disabled_mcp_server_ids,
        assistant_id=id,
        file_ids=file_ids,
        stream=ask.stream,
        tool_assistant_id=tool_assistant_id,
        version=version,
    )

    # Audit logging for new session started
    session_id = response.session.id
    assistant, _ = await service.get_assistant(id)

    # Get space for context
    space = None
    if assistant.space_id:
        try:
            space_service = container.space_service()
            space = await space_service.get_space(assistant.space_id)
        except Exception:
            space = None

    # Build extra context for session
    extra = {
        "session_id": str(session_id),
        "stream": ask.stream,
        "has_files": len(file_ids) > 0,
        "file_count": len(file_ids),
        "has_tool_assistant": tool_assistant_id is not None,
    }

    audit_service = container.audit_service()
    actor_id, actor_type = audit_actor_for(user)
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=actor_id,
        actor_type=actor_type,
        action=ActionType.SESSION_STARTED,
        entity_type=EntityType.ASSISTANT,
        entity_id=id,
        description=f"Started new session with assistant '{assistant.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=assistant,
            space=space,
            extra=extra,
        ),
    )

    return await assistant_protocol.to_response(
        response=response,
        stream=ask.stream,
        show_pricing=user.can_view_model_pricing,
    )


@router.get(
    "/{id}/sessions/",
    response_model=CursorPaginatedResponse[SessionMetadataPublic],
    responses=responses.get_responses([400, 403, 404]),
    dependencies=[Depends(require_resource_permission_for_method("conversations"))],
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def get_assistant_sessions(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
    limit: Annotated[int | None, Query(gt=0)] = None,
    cursor: datetime | None = None,
    previous: bool = False,
):
    assistant_service = container.assistant_service()
    session_service = container.session_service()

    assistant_in_db, _ = await assistant_service.get_assistant(id)

    sessions, total_count = await session_service.get_sessions_by_assistant(
        assistant_id=assistant_in_db.id,
        limit=limit,
        cursor=cursor,
        previous=previous,
    )

    return to_session_metadata_paginated_response(
        sessions=sessions,
        limit=limit,
        cursor=cursor,
        previous=previous,
        total_count=total_count,
    )


@router.get(
    "/{id}/sessions/{session_id}/",
    response_model=SessionPublic,
    responses=responses.get_responses([400, 403, 404, 410]),
    dependencies=[Depends(require_resource_permission_for_method("conversations"))],
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def get_assistant_session(
    id: UUID,
    session_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    assistant_service = container.assistant_service()
    session_service = container.session_service()

    await assistant_service.get_assistant(id)
    try:
        session = await session_service.get_session_by_uuid(session_id, assistant_id=id)
    except NotFoundException:
        # The partner was authorized above; the owner check comes first.
        await session_service.get_session_ownership(session_id, assistant_id=id)
        await session_service.refuse_removed_copy(session_id)
        raise
    return to_session_public(session)


@router.delete(
    "/{id}/sessions/{session_id}/",
    response_model=SessionPublic,
    description="Delete a session belonging to an assistant.",
    responses=responses.get_responses([400, 403, 404]),
    dependencies=[Depends(require_resource_permission_for_method("conversations"))],
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def delete_assistant_session(
    id: UUID,
    session_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    session_service = container.session_service()
    assistant_service = container.assistant_service()
    user = container.user()

    # Authorize before mutating the session. This also enforces personal_chat
    # for sessions belonging to the personal space's default assistant.
    assistant, _ = await assistant_service.get_assistant(id)

    session = await session_service.delete(session_id, assistant_id=id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get space for context
    space = None
    if assistant.space_id:
        try:
            space_service = container.space_service()
            space = await space_service.get_space(assistant.space_id)
        except Exception:
            space = None

    # Build extra context for session deletion
    extra = {
        "session_id": str(session_id),
    }

    audit_service = container.audit_service()
    actor_id, actor_type = audit_actor_for(user)
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=actor_id,
        actor_type=actor_type,
        action=ActionType.SESSION_ENDED,
        entity_type=EntityType.ASSISTANT,
        entity_id=id,
        description=f"Ended session with assistant '{assistant.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=assistant,
            space=space,
            extra=extra,
        ),
    )

    return to_session_public(session)


@router.post(
    "/{id}/sessions/{session_id}/",
    response_model=AskResponse,
    description="Ask a follow-up question in an existing session. Streams the response as Server-Sent Events if `stream` is `true`.",
    responses=responses.streaming_response(AskResponse, [400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.ASSISTANT,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def ask_followup(
    id: UUID,
    session_id: UUID,
    ask: AskAssistant,
    container: Annotated[
        Container,
        Depends(get_container(with_user_from_assistant_api_key=True)),
    ],
    version: Annotated[int, Query(ge=1, le=2)] = 1,
):
    """Streams the response as Server-Sent Events if stream == true"""
    service = container.assistant_service()

    file_ids = list(ask.files)
    tool_assistant_id = None
    if ask.tools is not None and ask.tools.assistants:
        tool_assistant_id = ask.tools.assistants[0].id
    response = await service.ask(
        question=ask.question,
        disabled_capabilities=ask.disabled_capabilities,
        disabled_mcp_server_ids=ask.disabled_mcp_server_ids,
        assistant_id=id,
        file_ids=file_ids,
        stream=ask.stream,
        session_id=session_id,
        tool_assistant_id=tool_assistant_id,
        version=version,
    )

    return await assistant_protocol.to_response(
        response=response,
        stream=ask.stream,
        show_pricing=container.user().can_view_model_pricing,
    )


@router.post(
    "/{id}/sessions/{session_id}/feedback/",
    response_model=SessionPublic,
    description="Leave feedback on a session.",
    responses=responses.get_responses([400, 403, 404, 410]),
    dependencies=[Depends(require_resource_permission_for_method("conversations"))],
)
@endpoint_access(
    authentication=Authentication.ASSISTANT,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def leave_feedback(
    id: UUID,
    session_id: UUID,
    feedback: SessionFeedback,
    container: Annotated[
        Container,
        Depends(get_container(with_user_from_assistant_api_key=True)),
    ],
):
    assistant_service = container.assistant_service()
    session_service = container.session_service()

    await assistant_service.get_assistant(id)
    try:
        session = await session_service.leave_feedback(
            session_id=session_id, assistant_id=id, feedback=feedback
        )
    except NotFoundException:
        # The partner was authorized above; the owner check comes first.
        await session_service.get_session_ownership(session_id, assistant_id=id)
        await session_service.refuse_removed_copy(session_id)
        raise

    return to_session_public(session)


@router.post(
    "/{id}/transfer/",
    status_code=204,
    description=(
        "Transfer an assistant to another space. Refused with 400 while the "
        "assistant has Skill bindings or a web widget that is not archived."
    ),
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def transfer_assistant_to_space(
    id: UUID,
    transfer_req: TransferRequest,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    await _raise_if_helper_chat(container, id)
    # Get assistant info BEFORE transfer to capture source space
    user = container.user()
    assistant_service = container.assistant_service()
    assistant_before, _ = await assistant_service.get_assistant(id)
    _raise_if_flow_managed(assistant_before, id)

    # Get source space info
    source_space = None
    if assistant_before.space_id:
        try:
            space_service = container.space_service()
            source_space = await space_service.get_space(assistant_before.space_id)
        except Exception:
            source_space = None

    # Transfer assistant
    service = container.resource_mover_service()
    await service.move_assistant_to_space(
        assistant_id=id,
        space_id=transfer_req.target_space_id,
    )

    # Get target space info
    target_space = None
    try:
        space_service = container.space_service()
        target_space = await space_service.get_space(transfer_req.target_space_id)
    except Exception:
        target_space = None

    # Build extra context for transfer (captures both source and target for incident investigation)
    extra = {
        "transfer": {
            "source_space_id": str(assistant_before.space_id)
            if assistant_before.space_id
            else None,
            "source_space_name": source_space.name if source_space else None,
            "target_space_id": str(transfer_req.target_space_id),
            "target_space_name": target_space.name if target_space else None,
        },
    }

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.ASSISTANT_TRANSFERRED,
        entity_type=EntityType.ASSISTANT,
        entity_id=id,
        description=f"Transferred assistant '{assistant_before.name}' from '{source_space.name if source_space else 'unknown'}' to '{target_space.name if target_space else 'unknown'}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=assistant_before,
            space=target_space,  # Use target space as the current space context
            extra=extra,
        ),
    )


@router.get(
    "/{id}/prompts/",
    response_model=PaginatedResponse[PromptSparse],
    description="List the prompt history for an assistant.",
    responses=responses.get_responses([404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def get_prompts(
    id: UUID, container: Annotated[Container, Depends(get_container(with_user=True))]
):
    await _raise_if_helper_chat(container, id, owner_may_read=True)
    service = container.assistant_service()
    assembler = container.prompt_assembler()

    prompts = await service.get_prompts_by_assistant(id)
    prompts = [assembler.from_prompt_to_model(prompt) for prompt in prompts]

    return protocol.to_paginated_response(prompts)


@router.post(
    "/{id}/publish/",
    response_model=AssistantPublic,
    description="Publish or unpublish an assistant.",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def publish_assistant(
    id: UUID,
    published: bool,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    applied = await apply_assistant_publish(
        container, assistant_id=id, published=published
    )
    return container.assistant_assembler().from_assistant_to_model(
        assistant=applied.assistant, permissions=applied.permissions
    )


@router.get(
    "/{id}/mcp-servers/",
    response_model=None,
    description="Get all MCP servers associated with an assistant.",
    responses=responses.get_responses([403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def get_assistant_mcp_servers(
    id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Get all MCP servers associated with an assistant."""
    await _raise_if_helper_chat(container, id, owner_may_read=True)
    service = container.assistant_service()
    mcp_servers = await service.get_assistant_mcp_servers(id)

    # Return as list of AssistantMCPServerPublic
    return {
        "items": [
            {
                "mcp_server_id": mcp.id,
                "mcp_server_name": mcp.name,
                "enabled": True,  # If it's in the list, it's enabled
                "config": None,  # TODO: Get from association table
                "priority": 0,  # TODO: Get from association table
            }
            for mcp in mcp_servers
        ]
    }


@router.post(
    "/{id}/mcp-servers/{mcp_server_id}/",
    response_model=None,
    description="Add an MCP server to an assistant.",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def add_mcp_to_assistant(
    id: UUID,
    mcp_server_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Add an MCP server to an assistant."""
    await _raise_if_helper_chat(container, id)
    service = container.assistant_service()
    existing_assistant, _ = await service.get_assistant(assistant_id=id)
    _raise_if_flow_managed(existing_assistant, id)

    assistant, _permissions = await service.add_mcp_to_assistant(
        assistant_id=id,
        mcp_server_id=mcp_server_id,
    )

    # Audit logging
    user = container.user()
    audit_service = container.audit_service()
    mcp_server_service = container.mcp_server_service()
    mcp_server = await mcp_server_service.get_mcp_server(mcp_server_id)
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.ASSISTANT_UPDATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=id,
        description=f"Added MCP server '{mcp_server.name}' to assistant '{assistant.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=assistant,
            changes={
                "mcp_servers": {
                    "added": [{"id": str(mcp_server.id), "name": mcp_server.name}]
                }
            },
        ),
    )

    return {"success": True}


@router.delete(
    "/{id}/mcp-servers/{mcp_server_id}/",
    status_code=204,
    description="Remove an MCP server from an assistant.",
    responses=responses.get_responses([400, 403, 404]),
)
@endpoint_access(
    authentication=Authentication.USER,
    authorization=Authorization.AUTHENTICATED,
    reason=_ASSISTANT_ACCESS_REASON,
)
async def remove_mcp_from_assistant(
    id: UUID,
    mcp_server_id: UUID,
    container: Annotated[Container, Depends(get_container(with_user=True))],
):
    """Remove an MCP server from an assistant."""
    await _raise_if_helper_chat(container, id)
    service = container.assistant_service()

    # Get context before removal for audit log
    assistant, _ = await service.get_assistant(assistant_id=id)
    _raise_if_flow_managed(assistant, id)
    mcp_server_service = container.mcp_server_service()
    mcp_server = await mcp_server_service.get_mcp_server(mcp_server_id)

    await service.remove_mcp_from_assistant(
        assistant_id=id,
        mcp_server_id=mcp_server_id,
    )

    # Audit logging
    user = container.user()
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        user=user,
        action=ActionType.ASSISTANT_UPDATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=id,
        description=f"Removed MCP server '{mcp_server.name}' from assistant '{assistant.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=assistant,
            changes={
                "mcp_servers": {
                    "removed": [{"id": str(mcp_server.id), "name": mcp_server.name}]
                }
            },
        ),
    )
