import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from intric.assistants.api import assistant_protocol
from intric.assistants.api.assistant_models import (
    AskAssistant,
    AssistantCreatePublic,
    AssistantPublic,
    AssistantUpdatePublic,
    TokenEstimateRequest,
    TokenEstimateResponse,
    TokenEstimateBreakdown,
)
from intric.authentication.auth_models import ApiKey
from intric.database.database import AsyncSession, get_session_with_transaction
from intric.main.config import get_settings
from intric.main.container.container import Container
from intric.main.models import NOT_PROVIDED, CursorPaginatedResponse, PaginatedResponse
from intric.prompts.api.prompt_models import PromptSparse
from intric.server import protocol
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.sessions.session import (
    AskResponse,
    SessionFeedback,
    SessionMetadataPublic,
    SessionPublic,
)
from intric.sessions.session_protocol import (
    to_session_public,
    to_sessions_paginated_response,
)
from intric.spaces.api.space_models import TransferApplicationRequest

# Audit logging - module level imports for consistency
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType

router = APIRouter()
logger = logging.getLogger(__name__)

# These limits keep the endpoint responsive while still supporting large-context models.
DEFAULT_CHARS_PER_TOKEN = 6  # Generous factor to cover dense languages
MAX_TOTAL_FILE_SIZE = 50_000_000  # 50 MB
MAX_ABSOLUTE_TEXT_LENGTH = 2_000_000  # 2 MB safeguard in case of misconfigured models


@router.post(
    "/",
    response_model=AssistantPublic,
    responses=responses.get_responses([404]),
)
async def create_assistant(
    assistant: AssistantCreatePublic,
    container: Container = Depends(get_container(with_user=True)),
):
    assistant_service = container.assistant_service()
    assembler = container.assistant_assembler()
    current_user = container.user()

    # Create assistant
    created_assistant, permissions = await assistant_service.create_assistant(
        name=assistant.name, space_id=assistant.space_id
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

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.ASSISTANT_CREATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=created_assistant.id,
        description=f"Created assistant '{created_assistant.name}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=created_assistant,
            space=space,
            extra=extra,
        ),
    )

    return assembler.from_assistant_to_model(created_assistant, permissions=permissions)


@router.get("/", response_model=PaginatedResponse[AssistantPublic])
async def get_assistants(
    name: str = None,
    for_tenant: bool = False,
    container: Container = Depends(get_container(with_user=True)),
):
    """Requires Admin permission if `for_tenant` is `true`."""
    service = container.assistant_service()
    assembler = container.assistant_assembler()

    assistants = await service.get_assistants(name, for_tenant)

    assistants = [
        assembler.from_assistant_to_model(assistant)
        for assistant in assistants
        if assistant.completion_model is not None
    ]

    return protocol.to_paginated_response(assistants)


@router.get(
    "/{id}/",
    response_model=AssistantPublic,
    responses=responses.get_responses([400, 404]),
)
async def get_assistant(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.assistant_service()
    assembler = container.assistant_assembler()

    assistant, permissions = await service.get_assistant(assistant_id=id)

    return assembler.from_assistant_to_model(
        assistant=assistant, permissions=permissions
    )


@router.post(
    "/{id}/",
    response_model=AssistantPublic,
    responses=responses.get_responses([400, 404]),
)
async def update_assistant(
    id: UUID,
    assistant: AssistantUpdatePublic,
    container: Container = Depends(get_container(with_user=True)),
):
    """Omitted fields are not updated"""
    service = container.assistant_service()
    assembler = container.assistant_assembler()
    current_user = container.user()

    # Get old state for change tracking
    old_assistant, _ = await service.get_assistant(assistant_id=id)

    attachment_ids = None
    if assistant.attachments is not None:
        attachment_ids = [attachment.id for attachment in assistant.attachments]

    groups = None
    if assistant.groups is not None:
        groups = [group.id for group in assistant.groups]

    websites = None
    if assistant.websites is not None:
        websites = [website.id for website in assistant.websites]

    integration_knowledge_ids = None
    if assistant.integration_knowledge_list is not None:
        integration_knowledge_ids = [i.id for i in assistant.integration_knowledge_list]

    completion_model_id = None
    if assistant.completion_model is not None:
        completion_model_id = assistant.completion_model.id

    completion_model_kwargs = None
    if assistant.completion_model_kwargs is not None:
        completion_model_kwargs = assistant.completion_model_kwargs

    # get original request dict to check if description was actually provided
    # (@partial_model overrides NOT_PROVIDED with None)
    request_dict = assistant.model_dump(exclude_unset=True)
    description = assistant.description
    metadata_json = assistant.metadata_json

    # if description wasn't in the original request, use NOT_PROVIDED
    if "description" not in request_dict:
        description = NOT_PROVIDED

    if "metadata_json" not in request_dict:
        metadata_json = NOT_PROVIDED

    # Handle icon_id: check if it was provided in the request
    icon_id = NOT_PROVIDED
    if "icon_id" in request_dict:
        icon_id = assistant.icon_id

    updated_assistant, permissions = await service.update_assistant(
        assistant_id=id,
        name=assistant.name,
        prompt=assistant.prompt,
        completion_model_id=completion_model_id,
        completion_model_kwargs=completion_model_kwargs,
        logging_enabled=assistant.logging_enabled,
        attachment_ids=attachment_ids,
        groups=groups,
        websites=websites,
        integration_knowledge_ids=integration_knowledge_ids,
        description=description,
        insight_enabled=assistant.insight_enabled,
        data_retention_days=assistant.data_retention_days,
        metadata_json=metadata_json,
        icon_id=icon_id,
    )

    # Track ALL changes comprehensively
    changes = {}

    # Name change
    if assistant.name and assistant.name != old_assistant.name:
        changes["name"] = {"old": old_assistant.name, "new": assistant.name}

    # Prompt change
    if assistant.prompt and assistant.prompt.text:
        old_prompt_text = old_assistant.prompt.text if old_assistant.prompt else ""
        if assistant.prompt.text != old_prompt_text:
            prompt_preview = (
                assistant.prompt.text[:50] + "..."
                if len(assistant.prompt.text) > 50
                else assistant.prompt.text
            )
            changes["prompt"] = {"changed": True, "preview": prompt_preview}

    # Model change
    if (
        completion_model_id
        and old_assistant.completion_model
        and completion_model_id != old_assistant.completion_model.id
    ):
        changes["model"] = {
            "old": old_assistant.completion_model.nickname
            if old_assistant.completion_model
            else None,
            "new": updated_assistant.completion_model.nickname
            if updated_assistant.completion_model
            else None,
        }

    # Temperature/Top-p changes
    # Get temperature values from completion_model_kwargs
    old_temperature = (
        old_assistant.completion_model_kwargs.temperature
        if old_assistant.completion_model_kwargs
        else None
    )
    new_temperature = (
        updated_assistant.completion_model_kwargs.temperature
        if updated_assistant.completion_model_kwargs
        else None
    )
    if old_temperature != new_temperature:
        changes["temperature"] = {"old": old_temperature, "new": new_temperature}

    old_top_p = (
        old_assistant.completion_model_kwargs.top_p
        if old_assistant.completion_model_kwargs
        else None
    )
    new_top_p = (
        updated_assistant.completion_model_kwargs.top_p
        if updated_assistant.completion_model_kwargs
        else None
    )
    if old_top_p != new_top_p:
        changes["top_p"] = {"old": old_top_p, "new": new_top_p}

    # Description change
    if description is not NOT_PROVIDED and description != old_assistant.description:
        if isinstance(old_assistant.description, str):
            old_desc_preview = (
                (old_assistant.description[:50] + "...")
                if len(old_assistant.description) > 50
                else old_assistant.description
            )
        else:
            old_desc_preview = old_assistant.description
        if isinstance(description, str):
            new_desc_preview = (
                (description[:50] + "...") if len(description) > 50 else description
            )
        else:
            new_desc_preview = description
        changes["description"] = {"old": old_desc_preview, "new": new_desc_preview}

    # Insights change
    if assistant.insight_enabled != old_assistant.insight_enabled:
        changes["insights_enabled"] = {
            "old": old_assistant.insight_enabled,
            "new": assistant.insight_enabled,
        }

    # Data retention change
    if assistant.data_retention_days != old_assistant.data_retention_days:
        changes["data_retention_days"] = {
            "old": old_assistant.data_retention_days,
            "new": assistant.data_retention_days,
        }

    # Helper function to track added/removed items
    def get_changes_for_list(
        old_list,
        new_list,
        name_attr="name",
        is_attachment=False,
        assistant_space_id=None,
    ):
        """Compare two lists and return added/removed items with their IDs, names, and scope."""
        old_items = {}
        new_items = {}

        def get_scope(item, assistant_space_id):
            """Determine if knowledge is 'space' or 'organizational'"""
            if not assistant_space_id or not hasattr(item, "space_id"):
                return None  # Cannot determine scope

            # If the item's space_id matches the assistant's, it's space-scoped
            # Otherwise, it's organizational (from parent/org space)
            if item.space_id == assistant_space_id:
                return "space"
            else:
                return "organizational"

        def extract_item_info(item, assistant_space_id):
            """Extract ID, name, and scope from an item, handling attachments specially."""
            item_id = str(item.id) if hasattr(item, "id") else str(item)

            # Special handling for FileAttachment objects
            if is_attachment:
                # For attachments, extract just the filename and optionally blob ID
                item_name = item.name if hasattr(item, "name") else "unknown_file"
                # Add blob ID if it exists and is not None
                if hasattr(item, "blob") and item.blob:
                    item_name = f"{item_name} (blob: {item.blob})"
            else:
                # For other types, use the specified attribute or a safe fallback
                if hasattr(item, name_attr):
                    item_name = getattr(item, name_attr)
                elif hasattr(item, "name"):
                    item_name = item.name
                else:
                    # Only use str() for simple types, not complex objects
                    item_name = f"{item.__class__.__name__}_{item_id}"

            # Determine scope
            scope = get_scope(item, assistant_space_id)

            return item_id, item_name, scope

        if old_list:
            for item in old_list:
                item_id, item_name, scope = extract_item_info(item, assistant_space_id)
                old_items[item_id] = {"name": item_name, "scope": scope}

        if new_list:
            for item in new_list:
                item_id, item_name, scope = extract_item_info(item, assistant_space_id)
                new_items[item_id] = {"name": item_name, "scope": scope}

        # Build added/removed lists with scope information
        added = []
        for k in new_items:
            if k not in old_items:
                item_data = {"id": k, "name": new_items[k]["name"]}
                if new_items[k]["scope"]:
                    item_data["scope"] = new_items[k]["scope"]
                added.append(item_data)

        removed = []
        for k in old_items:
            if k not in new_items:
                item_data = {"id": k, "name": old_items[k]["name"]}
                if old_items[k]["scope"]:
                    item_data["scope"] = old_items[k]["scope"]
                removed.append(item_data)

        return added, removed

    # Track knowledge source changes in detail
    knowledge_changes = {}

    # Collections
    collections_added, collections_removed = get_changes_for_list(
        old_assistant.collections,
        updated_assistant.collections,
        assistant_space_id=updated_assistant.space_id,
    )
    if collections_added or collections_removed:
        knowledge_changes["collections"] = {}
        if collections_added:
            knowledge_changes["collections"]["added"] = collections_added
        if collections_removed:
            knowledge_changes["collections"]["removed"] = collections_removed

    # Websites
    websites_added, websites_removed = get_changes_for_list(
        old_assistant.websites,
        updated_assistant.websites,
        name_attr="url",
        assistant_space_id=updated_assistant.space_id,
    )
    if websites_added or websites_removed:
        knowledge_changes["websites"] = {}
        if websites_added:
            knowledge_changes["websites"]["added"] = websites_added
        if websites_removed:
            knowledge_changes["websites"]["removed"] = websites_removed

    # Attachments
    attachments_added, attachments_removed = get_changes_for_list(
        old_assistant.attachments,
        updated_assistant.attachments,
        name_attr="name",
        is_attachment=True,
        assistant_space_id=updated_assistant.space_id,
    )
    if attachments_added or attachments_removed:
        knowledge_changes["attachments"] = {}
        if attachments_added:
            knowledge_changes["attachments"]["added"] = attachments_added
        if attachments_removed:
            knowledge_changes["attachments"]["removed"] = attachments_removed

    # Integration Knowledge
    integrations_added, integrations_removed = get_changes_for_list(
        old_assistant.integration_knowledge_list,
        updated_assistant.integration_knowledge_list,
        assistant_space_id=updated_assistant.space_id,
    )
    if integrations_added or integrations_removed:
        knowledge_changes["integrations"] = {}
        if integrations_added:
            knowledge_changes["integrations"]["added"] = integrations_added
        if integrations_removed:
            knowledge_changes["integrations"]["removed"] = integrations_removed

    if knowledge_changes:
        changes["knowledge_sources"] = knowledge_changes

    # Create summary of changes
    change_summary = []
    if "name" in changes:
        change_summary.append("name")
    if "prompt" in changes:
        change_summary.append("prompt")
    if "model" in changes:
        change_summary.append("model")
    if "temperature" in changes or "top_p" in changes:
        change_summary.append("parameters")
    if "description" in changes:
        change_summary.append("description")
    if "insights_enabled" in changes:
        change_summary.append("insights")
    if "data_retention_days" in changes:
        change_summary.append("retention")
    if "knowledge_sources" in changes:
        change_summary.append("knowledge sources")

    # Get space for context
    space = None
    if updated_assistant.space_id:
        try:
            space_service = container.space_service()
            space = await space_service.get_space(updated_assistant.space_id)
        except Exception:
            space = None

    # Build extra context
    extra = {
        "type": updated_assistant.type.value if updated_assistant.type else "standard",
        "summary": f"Modified {', '.join(change_summary)}"
        if change_summary
        else "No changes detected",
    }

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.ASSISTANT_UPDATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=id,
        description=f"Updated assistant '{updated_assistant.name}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=updated_assistant,
            space=space,
            changes=changes,
            extra=extra,
        ),
    )

    return assembler.from_assistant_to_model(updated_assistant, permissions=permissions)


@router.delete(
    "/{id}/",
    status_code=204,
    responses=responses.get_responses([403, 404]),
)
async def delete_assistant(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.assistant_service()
    current_user = container.user()

    # Get assistant details BEFORE deletion (snapshot pattern)
    assistant, _ = await service.get_assistant(id)

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
        actor_id=current_user.id,
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
    responses=responses.streaming_response(AskResponse, [400, 404]),
)
async def ask_assistant(
    id: UUID,
    ask: AskAssistant,
    version: int = Query(default=1, ge=1, le=2),
    container: Container = Depends(
        get_container(with_user_from_assistant_api_key=True)
    ),
    db_session: AsyncSession = Depends(get_session_with_transaction),
):
    """Streams the response as Server-Sent Events if stream == true"""
    service = container.assistant_service()
    user = container.user()

    file_ids = [file.id for file in ask.files]
    tool_assistant_id = None
    if ask.tools is not None and ask.tools.assistants:
        tool_assistant_id = ask.tools.assistants[0].id
    response = await service.ask(
        question=ask.question,
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
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
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
        response=response, db_session=db_session, stream=ask.stream
    )


@router.get(
    "/{id}/sessions/",
    response_model=CursorPaginatedResponse[SessionMetadataPublic],
    responses=responses.get_responses([400, 404]),
)
async def get_assistant_sessions(
    id: UUID,
    limit: int = Query(default=None, gt=0),
    cursor: datetime = None,
    previous: bool = False,
    container: Container = Depends(get_container(with_user=True)),
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
    return to_sessions_paginated_response(
        sessions=sessions,
        limit=limit,
        cursor=cursor,
        previous=previous,
        total_count=total_count,
    )


@router.get(
    "/{id}/sessions/{session_id}/",
    response_model=SessionPublic,
    responses=responses.get_responses([400, 404]),
)
async def get_assistant_session(
    id: UUID,
    session_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    session_service = container.session_service()
    session = await session_service.get_session_by_uuid(session_id, assistant_id=id)

    return to_session_public(session)


@router.delete(
    "/{id}/sessions/{session_id}/",
    response_model=SessionPublic,
    responses=responses.get_responses([400, 404]),
)
async def delete_assistant_session(
    id: UUID,
    session_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    session_service = container.session_service()
    assistant_service = container.assistant_service()
    user = container.user()

    # Delete session
    session = await session_service.delete(session_id, assistant_id=id)

    # Get assistant info for audit log
    assistant, _ = await assistant_service.get_assistant(id)

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
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
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
    responses=responses.streaming_response(AskResponse, [400, 404]),
)
async def ask_followup(
    id: UUID,
    session_id: UUID,
    ask: AskAssistant,
    version: int = Query(default=1, ge=1, le=2),
    container: Container = Depends(
        get_container(with_user_from_assistant_api_key=True)
    ),
    db_session: AsyncSession = Depends(get_session_with_transaction),
):
    """Streams the response as Server-Sent Events if stream == true"""
    service = container.assistant_service()

    file_ids = [file.id for file in ask.files]
    tool_assistant_id = None
    if ask.tools is not None and ask.tools.assistants:
        tool_assistant_id = ask.tools.assistants[0].id
    response = await service.ask(
        question=ask.question,
        assistant_id=id,
        file_ids=file_ids,
        stream=ask.stream,
        session_id=session_id,
        tool_assistant_id=tool_assistant_id,
        version=version,
    )

    return await assistant_protocol.to_response(
        response=response, db_session=db_session, stream=ask.stream
    )


@router.post(
    "/{id}/sessions/{session_id}/feedback/",
    response_model=SessionPublic,
    responses=responses.get_responses([400, 404]),
)
async def leave_feedback(
    id: UUID,
    session_id: UUID,
    feedback: SessionFeedback,
    container: Container = Depends(
        get_container(with_user_from_assistant_api_key=True)
    ),
):
    session_service = container.session_service()
    session = await session_service.leave_feedback(
        session_id=session_id, assistant_id=id, feedback=feedback
    )

    return to_session_public(session)


@router.get(
    "/{id}/api-keys/",
    response_model=ApiKey,
    deprecated=True,
    description=(
        "Legacy assistant API key endpoint. Use /api/v1/api-keys for scoped v2 keys."
    ),
)
async def generate_read_only_assistant_key(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    """Generates a read-only api key for this assistant.

    This api key can only be used on `POST /api/v1/assistants/{id}/sessions/`
    and `POST /api/v1/assistants/{id}/sessions/{session_id}/`."""
    settings = get_settings()
    if not settings.api_key_legacy_endpoints_enabled:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "deprecated_endpoint",
                "message": "Legacy assistant API key endpoint is disabled. Use /api/v1/api-keys.",
            },
        )
    service = container.assistant_service()
    user = container.user()

    # Generate API key
    api_key = await service.generate_api_key(id)

    # Get assistant info for audit log
    assistant, _ = await service.get_assistant(id)

    # Get space for context
    space = None
    if assistant.space_id:
        try:
            space_service = container.space_service()
            space = await space_service.get_space(assistant.space_id)
        except Exception:
            space = None

    # Build extra context for API key generation
    extra = {
        "truncated_key": api_key.truncated_key,
        "key_type": "assistant_read_only",
    }

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.API_KEY_GENERATED,
        entity_type=EntityType.API_KEY,
        entity_id=id,  # Use assistant ID as entity ID for assistant API keys
        description=f"Generated read-only API key for assistant '{assistant.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=assistant,
            space=space,
            extra=extra,
        ),
    )

    return api_key


@router.post("/{id}/transfer/", status_code=204)
async def transfer_assistant_to_space(
    id: UUID,
    transfer_req: TransferApplicationRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    # Get assistant info BEFORE transfer to capture source space
    user = container.user()
    assistant_service = container.assistant_service()
    assistant_before, _ = await assistant_service.get_assistant(id)

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
        move_resources=transfer_req.move_resources,
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
            "move_resources": transfer_req.move_resources,
        },
    }

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
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
    include_in_schema=get_settings().dev,
)
async def get_prompts(
    id: UUID, container: Container = Depends(get_container(with_user=True))
):
    service = container.assistant_service()
    assembler = container.prompt_assembler()

    prompts = await service.get_prompts_by_assistant(id)
    prompts = [assembler.from_prompt_to_model(prompt) for prompt in prompts]

    return protocol.to_paginated_response(prompts)


@router.post(
    "/{id}/publish/",
    response_model=AssistantPublic,
    responses=responses.get_responses([403, 404]),
)
async def publish_assistant(
    id: UUID,
    published: bool,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.assistant_service()
    assembler = container.assistant_assembler()
    user = container.user()

    # Publish/unpublish assistant
    assistant, permissions = await service.publish_assistant(
        assistant_id=id, publish=published
    )

    # Get space for context
    space = None
    if assistant.space_id:
        try:
            space_service = container.space_service()
            space = await space_service.get_space(assistant.space_id)
        except Exception:
            space = None

    # Build extra context
    extra = {
        "published": published,
        "action": "published" if published else "unpublished",
    }

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.ASSISTANT_PUBLISHED,
        entity_type=EntityType.ASSISTANT,
        entity_id=id,
        description=f"{'Published' if published else 'Unpublished'} assistant '{assistant.name}'",
        metadata=AuditMetadata.standard(
            actor=user,
            target=assistant,
            space=space,
            extra=extra,
        ),
    )

    return assembler.from_assistant_to_model(
        assistant=assistant, permissions=permissions
    )


@router.post(
    "/{id}/token-estimate",
    response_model=TokenEstimateResponse,
    responses=responses.get_responses([400, 404]),
    summary="Estimate token usage for text and files",
)
async def estimate_tokens(
    id: UUID,
    payload: TokenEstimateRequest,
    container: Container = Depends(get_container(with_user=True)),
) -> TokenEstimateResponse:
    """Estimate token usage for the given text and files for this assistant.

    The Space Actor + FileService stack already enforces tenant and ownership
    boundaries; this endpoint adds lightweight guardrails to keep the operation
    responsive while supporting large-context models.
    """

    from intric.tokens.token_utils import count_tokens, count_assistant_prompt_tokens

    service = container.assistant_service()
    file_service = container.file_service()

    assistant, _ = await service.get_assistant(assistant_id=id)

    if not assistant.completion_model:
        raise HTTPException(status_code=400, detail="Assistant has no model configured")

    model_name = assistant.completion_model.name
    token_limit = assistant.completion_model.token_limit

    max_chars = min(
        MAX_ABSOLUTE_TEXT_LENGTH,
        int(token_limit * DEFAULT_CHARS_PER_TOKEN)
        if token_limit
        else MAX_ABSOLUTE_TEXT_LENGTH,
    )

    text = payload.text or ""
    if len(text) > max_chars:
        raise HTTPException(
            status_code=400,
            detail=(
                "Text input is too large for this assistant's context window. "
                f"Reduce the size below {max_chars:,} characters."
            ),
        )

    file_ids = payload.file_ids or []

    prompt_tokens = 0
    if assistant.prompt:
        prompt_text = getattr(assistant.prompt, "prompt", None) or getattr(
            assistant.prompt, "text", None
        )
        if prompt_text:
            prompt_tokens = count_assistant_prompt_tokens(prompt_text, model_name)

    text_tokens = count_tokens(text, model_name) if text else 0

    file_tokens = 0
    file_token_details: dict[str, int] = {}
    if file_ids:
        files = await file_service.get_files_for_token_estimate(file_ids)
        accessible_ids = {file.id for file in files}
        missing_ids = [
            str(file_id) for file_id in file_ids if file_id not in accessible_ids
        ]
        if missing_ids:
            logger.debug(
                "Skipped token estimate for filtered file IDs: %s", missing_ids
            )

        total_file_size = sum(file.size for file in files if file.size is not None)
        if total_file_size > MAX_TOTAL_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Combined file content exceeds 50 MB limit. "
                    "Remove one or more files and try again."
                ),
            )

        for file in files:
            tokens = 0
            if file.text:
                try:
                    tokens = count_tokens(file.text, model_name)
                except Exception as exc:  # pragma: no cover - defensive logging path
                    logger.error("Failed to count tokens for file %s: %s", file.id, exc)
                    tokens = len(file.text) // 4

            file_tokens += tokens
            file_token_details[str(file.id)] = tokens

    total_tokens = prompt_tokens + text_tokens + file_tokens
    percentage = (total_tokens / token_limit) * 100 if token_limit > 0 else 0

    return TokenEstimateResponse(
        tokens=total_tokens,
        percentage=round(percentage, 2),
        limit=token_limit,
        breakdown=TokenEstimateBreakdown(
            prompt=prompt_tokens,
            text=text_tokens,
            files=file_tokens,
            file_details=file_token_details,
        ),
    )
