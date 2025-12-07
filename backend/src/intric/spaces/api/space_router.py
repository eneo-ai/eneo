from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query

# Audit logging - module level imports for consistency
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType

from intric.apps.apps.api.app_models import AppPublic
from intric.assistants.api.assistant_models import AssistantPublic
from intric.authentication.auth_dependencies import require_permission
from intric.collections.presentation.collection_models import CollectionPublic
from intric.group_chat.presentation.models import GroupChatCreate, GroupChatPublic
from intric.main.container.container import Container
from intric.main.models import NOT_PROVIDED, ModelId, PaginatedResponse
from intric.server import protocol
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.spaces.api.space_models import (
    AddSpaceMemberRequest,
    Applications,
    CreateSpaceAppRequest,
    CreateSpaceAssistantRequest,
    CreateSpaceGroupsRequest,
    CreateSpaceIntegrationKnowledge,
    CreateSpaceRequest,
    CreateSpaceServiceRequest,
    CreateSpaceServiceResponse,
    Knowledge,
    SpaceMember,
    SpacePublic,
    SpaceSparse,
    UpdateSpaceDryRunResponse,
    UpdateSpaceMemberRequest,
    UpdateSpaceRequest,
)

from intric.websites.presentation.website_models import WebsiteCreate, WebsitePublic
from intric.roles.permissions import Permission
router = APIRouter()

async def forbid_org_space(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    space = await container.space_service().get_space(id)
    if space.user_id is None and space.tenant_space_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return True
    
@router.post("/", response_model=SpacePublic, status_code=201)
async def create_space(
    create_space_req: CreateSpaceRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    space_creation_service = container.space_init_service()
    space_assembler = container.space_assembler()
    current_user = container.user()

    # Create space
    space = await space_creation_service.create_space(name=create_space_req.name)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.SPACE_CREATED,
        entity_type=EntityType.SPACE,
        entity_id=space.id,
        description=f"Created space '{space.name}'",
        metadata=AuditMetadata.standard(actor=current_user, target=space),
    )

    return space_assembler.from_space_to_model(space)


@router.get(
    "/{id}/",
    response_model=SpacePublic,
    status_code=200,
    responses=responses.get_responses([404]),
)
async def get_space(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.space_init_service()
    assembler = container.space_assembler()

    space = await service.get_space(id)

    return assembler.from_space_to_model(space)


@router.patch(
    "/{id}/",
    response_model=SpacePublic,
    status_code=200,
    responses=responses.get_responses([400, 403, 404]),
)
async def update_space(
    id: UUID,
    update_space_req: UpdateSpaceRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.space_service()
    assembler = container.space_assembler()
    current_user = container.user()

    # Get old state
    old_space = await service.get_space(id)

    def _get_model_ids_or_none(models: list[ModelId] | None):
        if models is None:
            return None

        return [model.id for model in models]

    # Get original request dict to check if fields were actually provided
    # (partial_model may have turned NOT_PROVIDED into None)
    original_request = update_space_req.model_dump(exclude_unset=True)

    if "security_classification" not in original_request:
        security_classification = NOT_PROVIDED
    else:
        security_classification = update_space_req.security_classification

    if "data_retention_days" not in original_request:
        data_retention_days = NOT_PROVIDED
    else:
        data_retention_days = update_space_req.data_retention_days

    space = await service.update_space(
        id=id,
        name=update_space_req.name,
        description=update_space_req.description,
        embedding_model_ids=_get_model_ids_or_none(update_space_req.embedding_models),
        completion_model_ids=_get_model_ids_or_none(update_space_req.completion_models),
        transcription_model_ids=_get_model_ids_or_none(update_space_req.transcription_models),
        security_classification=security_classification,
        data_retention_days=data_retention_days,
    )

    # Track changes
    changes = {}
    if update_space_req.name and update_space_req.name != old_space.name:
        changes["name"] = {"old": old_space.name, "new": update_space_req.name}
    if update_space_req.description is not None and update_space_req.description != old_space.description:
        changes["description"] = {"old": old_space.description, "new": update_space_req.description}
    if data_retention_days is not NOT_PROVIDED and data_retention_days != old_space.data_retention_days:
        changes["data_retention_days"] = {
            "old": old_space.data_retention_days,
            "new": data_retention_days
        }

    # Track model changes using SET comparison (avoids false positives from ordering)
    if update_space_req.completion_models is not None:
        old_model_set = {(str(m.id), m.name) for m in (old_space.completion_models or [])}
        new_model_set = {(str(m.id), m.name) for m in (space.completion_models or [])}
        if old_model_set != new_model_set:
            changes["completion_models"] = {
                "old": [{"id": str(m.id), "name": m.name} for m in (old_space.completion_models or [])],
                "new": [{"id": str(m.id), "name": m.name} for m in (space.completion_models or [])]
            }

    if update_space_req.embedding_models is not None:
        old_model_set = {(str(m.id), m.name) for m in (old_space.embedding_models or [])}
        new_model_set = {(str(m.id), m.name) for m in (space.embedding_models or [])}
        if old_model_set != new_model_set:
            changes["embedding_models"] = {
                "old": [{"id": str(m.id), "name": m.name} for m in (old_space.embedding_models or [])],
                "new": [{"id": str(m.id), "name": m.name} for m in (space.embedding_models or [])]
            }

    if update_space_req.transcription_models is not None:
        old_model_set = {(str(m.id), m.name) for m in (old_space.transcription_models or [])}
        new_model_set = {(str(m.id), m.name) for m in (space.transcription_models or [])}
        if old_model_set != new_model_set:
            changes["transcription_models"] = {
                "old": [{"id": str(m.id), "name": m.name} for m in (old_space.transcription_models or [])],
                "new": [{"id": str(m.id), "name": m.name} for m in (space.transcription_models or [])]
            }

    # Track security classification changes
    if security_classification is not NOT_PROVIDED:
        old_sc = old_space.security_classification.name if old_space.security_classification else None
        new_sc = space.security_classification.name if space.security_classification else None
        if old_sc != new_sc:
            changes["security_classification"] = {"old": old_sc, "new": new_sc}

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.SPACE_UPDATED,
        entity_type=EntityType.SPACE,
        entity_id=id,
        description=f"Updated space '{space.name}'",
        metadata=AuditMetadata.standard(actor=current_user, target=space, changes=changes),
    )

    return assembler.from_space_to_model(space)


@router.get(
    "/{id}/security_classification/{security_classification_id}/impact-analysis/",
    response_model=UpdateSpaceDryRunResponse,
    status_code=200,
    description="Get a preview of the impact of changing the security classification of a space.",
)
async def get_security_classification_impact_analysis(
    id: UUID,
    security_classification_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.space_service()
    assembler = container.space_assembler()

    result = await service.security_classification_impact_analysis(
        id=id,
        security_classification_id=security_classification_id,
    )

    return assembler.from_security_classification_impact_analysis_to_model(result)


@router.delete(
    "/{id}/",
    status_code=204,
    responses=responses.get_responses([403, 404]),
    dependencies=[Depends(forbid_org_space)],
)
async def delete_space(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.space_service()
    user = container.user()

    # Get space info before deletion (for audit log context)
    space = await service.get_space(id)

    # Delete space
    await service.delete_space(id=id)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.SPACE_DELETED,
        entity_type=EntityType.SPACE,
        entity_id=id,
        description=f"Deleted space '{space.name}'",
        metadata=AuditMetadata.standard(actor=user, target=space),
    )


@router.get(
    "/",
    response_model=PaginatedResponse[SpaceSparse],
    status_code=200,
)
async def get_spaces(
    include_applications: bool = Query(default=False, description="Includes published applications on each space"),
    include_personal: bool = Query(default=False,  description="Includes your personal space"),
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.space_service()
    assembler = container.space_assembler()

    spaces = await service.get_spaces(include_personal=include_personal)
    spaces = [assembler.from_space_to_sparse_model(space, include_applications=include_applications) for space in spaces]

    return protocol.to_paginated_response(spaces)

@router.get(
    "/{id}/applications/",
    response_model=Applications,
    responses=responses.get_responses([404]),
    dependencies=[Depends(forbid_org_space)],
)
async def get_space_applications(
    id: UUID, container: Container = Depends(get_container(with_user=True))
):
    service = container.space_service()
    assembler = container.space_assembler()

    space = await service.get_space(id)

    return assembler.from_space_to_model(space).applications


@router.post(
    "/{id}/applications/assistants/",
    response_model=AssistantPublic,
    status_code=201,
    responses=responses.get_responses([400, 403, 404]),
    dependencies=[Depends(forbid_org_space)],
)
async def create_space_assistant(
    id: UUID,
    assistant_in: CreateSpaceAssistantRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.assistant_service()
    assembler = container.assistant_assembler()
    current_user = container.user()

    # Create assistant
    assistant, permissions = await service.create_assistant(
        name=assistant_in.name, space_id=id, template_data=assistant_in.from_template
    )

    # Get space for context (graceful degradation if space fetch fails)
    space = None
    try:
        space_service = container.space_service()
        space = await space_service.get_space(id)
    except Exception:
        pass

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.ASSISTANT_CREATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=assistant.id,
        description=f"Created assistant '{assistant.name}' in space '{space.name if space else 'unknown'}'",
        metadata=AuditMetadata.standard(actor=current_user, target=assistant, space=space),
    )

    return assembler.from_assistant_to_model(assistant, permissions=permissions)


@router.post(
    "/{id}/applications/group-chats/",
    response_model=GroupChatPublic,
    description="Creates a group chat.",
    response_description="Successful Response.",
    status_code=201,
    responses=responses.get_responses([400, 403, 404]),
    dependencies=[Depends(forbid_org_space)],
)
async def create_group_chat(
    id: UUID,
    group_chat_in: GroupChatCreate,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.group_chat_service()
    assembler = container.group_chat_assembler()
    user = container.user()

    # Create group chat
    group_chat = await service.create_group_chat(space_id=id, name=group_chat_in.name)

    # Get space for context (graceful degradation if space fetch fails)
    space = None
    try:
        space_service = container.space_service()
        space = await space_service.get_space(id)
    except Exception:
        pass

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.GROUP_CHAT_CREATED,
        entity_type=EntityType.GROUP_CHAT,
        entity_id=group_chat.id,
        description=f"Created group chat '{group_chat.name}' in space '{space.name if space else 'unknown'}'",
        metadata=AuditMetadata.standard(actor=user, target=group_chat, space=space),
    )

    return assembler.from_domain_to_model(group_chat=group_chat)


@router.post(
    "/{id}/applications/apps/",
    response_model=AppPublic,
    status_code=201,
    responses=responses.get_responses([400, 403, 404]),
    dependencies=[Depends(forbid_org_space)],
)
async def create_app(
    id: UUID,
    create_service_req: CreateSpaceAppRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    space_service = container.space_service()
    app_service = container.app_service()
    assembler = container.app_assembler()
    current_user = container.user()

    # Create app (space is fetched first for the creation process)
    space = await space_service.get_space(id)
    app, permissions = await app_service.create_app(
        name=create_service_req.name,
        space=space,
        template_data=create_service_req.from_template,
    )

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.APP_CREATED,
        entity_type=EntityType.APP,
        entity_id=app.id,
        description=f"Created app '{app.name}' in space '{space.name}'",
        metadata=AuditMetadata.standard(actor=current_user, target=app, space=space),
    )

    return assembler.from_app_to_model(app, permissions=permissions)


@router.post(
    "/{id}/applications/services/",
    response_model=CreateSpaceServiceResponse,
    status_code=201,
    responses=responses.get_responses([400, 403, 404]),
    dependencies=[Depends(forbid_org_space)],
)
async def create_space_services(
    id: UUID,
    service_in: CreateSpaceServiceRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.service_service()
    assembler = container.space_assembler()

    service, permissions = await service.create_space_service(name=service_in.name, space_id=id)

    return assembler.from_service_to_model(service=service, permissions=permissions)


@router.get(
    "/{id}/knowledge/",
    response_model=Knowledge,
    responses=responses.get_responses([404]),
)
async def get_space_knowledge(
    id: UUID, container: Container = Depends(get_container(with_user=True))
):
    space_service = container.space_service()
    assembler = container.space_assembler()

    space = await space_service.get_space(id)
    groups, websites, integrations = await space_service.get_knowledge_for_space(id)

    space.collections = groups
    space.websites = websites
    space.integration_knowledge_list = integrations

    return assembler.from_space_to_model(space).knowledge

@router.post(
    "/{id}/knowledge/groups/",
    response_model=CollectionPublic,
    status_code=201,
    responses=responses.get_responses([400, 403, 404]),
)
async def create_space_groups(
    id: UUID,
    group: CreateSpaceGroupsRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    svc = container.collection_crud_service()
    user = container.user()
    embedding_model_id = group.embedding_model.id if group.embedding_model else None

    # Create collection
    created_collection = await svc.create_collection(
        name=group.name,
        space_id=id,
        embedding_model_id=embedding_model_id,
    )

    # Get space for context (graceful degradation if space fetch fails)
    space = None
    try:
        space_service = container.space_service()
        space = await space_service.get_space(id)
    except Exception:
        pass

    # Build extra context for embedding model if provided
    extra = None
    if group.embedding_model:
        extra = {
            "embedding_model": {
                "id": str(group.embedding_model.id),
                "name": getattr(group.embedding_model, "name", None),
            }
        }

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.COLLECTION_CREATED,
        entity_type=EntityType.COLLECTION,
        entity_id=created_collection.id,
        description=f"Created collection '{created_collection.name}' in space '{space.name if space else 'unknown'}'",
        metadata=AuditMetadata.standard(actor=user, target=created_collection, space=space, extra=extra),
    )

    return CollectionPublic.from_domain(created_collection)
  

@router.post(
    "/{id}/knowledge/websites/",
    response_model=WebsitePublic,
    status_code=201,
    responses=responses.get_responses([400, 403, 404]),
    summary="Create a website crawler",
    description="""
    Create a new website crawler that will extract content and make it available to assistants in this space.

    **Update Intervals:**
    - `never` (default): Manual crawls only
    - `daily`: Automatic recrawl every day at 3 AM Swedish time
    - `every_other_day`: Recrawl every 2 days
    - `weekly`: Recrawl every Friday

    **Example Request Body:**
    ```json
    {
      "name": "Company Documentation",
      "url": "https://docs.example.com",
      "crawl_type": "crawl",
      "download_files": true,
      "update_interval": "daily"
    }
    ```

    The crawl will start immediately upon creation.
    """,
)
async def create_space_websites(
    id: UUID,
    website: WebsiteCreate,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.website_crud_service()
    user = container.user()

    # Create website
    created_website = await service.create_website(
        space_id=id,
        name=website.name,
        url=website.url,
        download_files=website.download_files,
        crawl_type=website.crawl_type,
        update_interval=website.update_interval,
        embedding_model_id=(website.embedding_model.id if website.embedding_model else None),
        http_auth_username=website.http_auth_username,
        http_auth_password=website.http_auth_password,
    )

    # Get space for context (graceful degradation if space fetch fails)
    space = None
    try:
        space_service = container.space_service()
        space = await space_service.get_space(id)
    except Exception:
        pass

    # Build extra context with URL, crawl settings, and optional embedding model
    extra = {
        "url": created_website.url,
        "crawl_type": str(website.crawl_type) if website.crawl_type else None,
        "update_interval": str(website.update_interval) if website.update_interval else None,
    }
    if website.embedding_model:
        extra["embedding_model"] = {
            "id": str(website.embedding_model.id),
            "name": getattr(website.embedding_model, "name", None),
        }

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.WEBSITE_CREATED,
        entity_type=EntityType.WEBSITE,
        entity_id=created_website.id,
        description=f"Created website crawler '{created_website.name}' ({created_website.url}) in space '{space.name if space else 'unknown'}'",
        metadata=AuditMetadata.standard(actor=user, target=created_website, space=space, extra=extra),
    )

    return WebsitePublic.from_domain(created_website)


@router.post(
    "/{id}/knowledge/integrations/{user_integration_id}/",
    status_code=200,
)
async def create_space_integration_knowledge(
    id: UUID,
    user_integration_id: UUID,
    data: CreateSpaceIntegrationKnowledge,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.integration_knowledge_service()
    assembler = container.integration_knowledge_assembler()
    user = container.user()

    # Create integration knowledge
    knowledge = await service.create_space_integration_knowledge(
        user_integration_id=user_integration_id,
        name=data.name,
        space_id=id,
        embedding_model_id=data.embedding_model.id,
        url=data.url,
        key=data.key,
    )

    # Get space for context (graceful degradation if space fetch fails)
    space = None
    try:
        space_service = container.space_service()
        space = await space_service.get_space(id)
    except Exception:
        pass

    # Build extra context with integration-specific information
    extra = {
        "integration_type": knowledge.integration_type,
        "url": knowledge.url,
        "embedding_model": {
            "id": str(data.embedding_model.id),
            "name": getattr(data.embedding_model, "name", None),
        },
    }

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.INTEGRATION_KNOWLEDGE_CREATED,
        entity_type=EntityType.INTEGRATION_KNOWLEDGE,
        entity_id=knowledge.id,
        description=f"Added {knowledge.integration_type} knowledge '{knowledge.name}' to space '{space.name if space else 'unknown'}'",
        metadata=AuditMetadata.standard(actor=user, target=knowledge, space=space, extra=extra),
    )

    return assembler.to_space_knowledge_model(item=knowledge)


@router.delete(
    "/{id}/knowledge/{integration_knowledge_id}/",
    status_code=204,
)
async def delete_space_integration_knowledge(
    id: UUID,
    integration_knowledge_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.integration_knowledge_service()
    user = container.user()

    # Get integration knowledge info BEFORE deletion (for audit log context)
    space_repo = container.space_repo()
    space = await space_repo.one(id=id)
    knowledge = space.get_integration_knowledge(integration_knowledge_id=integration_knowledge_id)

    # Delete integration knowledge
    await service.remove_knowledge(space_id=id, integration_knowledge_id=integration_knowledge_id)

    # Build extra context with integration-specific information
    extra = {
        "integration_type": knowledge.integration_type,
    }

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.INTEGRATION_KNOWLEDGE_DELETED,
        entity_type=EntityType.INTEGRATION_KNOWLEDGE,
        entity_id=integration_knowledge_id,
        description=f"Removed {knowledge.integration_type} knowledge '{knowledge.name}' from space '{space.name}'",
        metadata=AuditMetadata.standard(actor=user, target=knowledge, space=space, extra=extra),
    )


@router.post(
    "/{id}/members/",
    response_model=SpaceMember,
    responses=responses.get_responses([403, 404]),
    dependencies=[Depends(forbid_org_space)],
)
async def add_space_member(
    id: UUID,
    add_space_member_req: AddSpaceMemberRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.space_service()
    current_user = container.user()

    # Add member
    member = await service.add_member(
        id, member_id=add_space_member_req.id, role=add_space_member_req.role
    )

    # Get space for context (graceful degradation if space fetch fails)
    space = None
    try:
        space = await service.get_space(id)
    except Exception:
        pass

    # Get member info for context (graceful degradation if member fetch fails)
    member_user = None
    try:
        user_service = container.user_service()
        member_user = await user_service.get_user(add_space_member_req.id)
    except Exception:
        pass

    # Build extra context with member-specific information
    extra = {
        "member": {
            "id": str(add_space_member_req.id),
            "name": member_user.username if member_user else None,
            "email": member_user.email if member_user else None,
        },
        "role": add_space_member_req.role,
    }

    # Audit logging
    member_display = member_user.username or member_user.email if member_user else "member"
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.SPACE_MEMBER_ADDED,
        entity_type=EntityType.SPACE,
        entity_id=id,
        description=f"Added {member_display} to space '{space.name if space else 'unknown'}' with role '{add_space_member_req.role}'",
        metadata=AuditMetadata.standard(actor=current_user, target=space if space else member, space=space, extra=extra),
    )

    return member


@router.patch(
    "/{id}/members/{user_id}/",
    response_model=SpaceMember,
    responses=responses.get_responses([403, 404, 400]),
    dependencies=[Depends(forbid_org_space)],
)
async def change_role_of_member(
    id: UUID,
    user_id: UUID,
    update_space_member_req: UpdateSpaceMemberRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    import logging
    logger = logging.getLogger(__name__)

    service = container.space_service()
    current_user = container.user()

    # Snapshot context for audit log (graceful degradation pattern)
    space = None
    member_user = None

    try:
        space = await service.get_space(id)
    except Exception as e:
        logger.warning(f"Failed to fetch space context for audit log: {e}")

    try:
        user_service = container.user_service()
        member_user = await user_service.get_user(user_id)
    except Exception as e:
        logger.warning(f"Failed to fetch member context for audit log: {e}")

    # Get current member to track old role
    current_member = await service.get_space_member(id, user_id)
    old_role = current_member.role

    # Change role
    updated_member = await service.change_role_of_member(id, user_id, update_space_member_req.role)

    # Build extra context with member-specific information
    extra = {
        "member": {
            "id": str(user_id),
            "name": member_user.username if member_user else None,
            "email": member_user.email if member_user else None,
        },
    }

    # Build changes dict for role change
    changes = {
        "role": {
            "old": old_role,
            "new": update_space_member_req.role,
        },
    }

    # Audit logging with full context
    member_display = member_user.username if member_user else "member"
    space_display = space.name if space else "space"

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.ROLE_MODIFIED,
        entity_type=EntityType.SPACE,
        entity_id=id,
        description=f"Changed role of {member_display} in {space_display} from {old_role} to {update_space_member_req.role}",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=space if space else updated_member,
            space=space,
            changes=changes,
            extra=extra,
        ),
    )

    return updated_member


@router.delete(
    "/{id}/members/{user_id}/",
    status_code=204,
    responses=responses.get_responses([403, 404, 400]),
    dependencies=[Depends(forbid_org_space)],
)
async def remove_space_member(
    id: UUID,
    user_id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    import logging

    logger = logging.getLogger(__name__)

    service = container.space_service()
    current_user = container.user()

    # 1. Snapshot data BEFORE deletion (graceful degradation pattern)
    member_snapshot = {"id": str(user_id), "name": None, "email": None}
    space = None

    try:
        space = await service.get_space(id)
    except Exception as e:
        logger.warning(f"Failed to fetch space context for audit log: {e}")

    try:
        user_service = container.user_service()
        member_user = await user_service.get_user(user_id)
        if member_user:
            member_snapshot = {
                "id": str(member_user.id),
                "name": member_user.username,
                "email": member_user.email,
            }
    except Exception as e:
        logger.warning(f"Failed to fetch member context for audit log: {e}")

    # 2. Perform the actual deletion
    await service.remove_member(id, user_id)

    # 3. Audit logging with full context (snapshot pattern)
    space_name = space.name if space else "space"
    member_name = member_snapshot["name"] or "member"

    # Build extra context for member being removed
    extra = {
        "member": member_snapshot,
    }

    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.SPACE_MEMBER_REMOVED,
        entity_type=EntityType.SPACE,
        entity_id=id,
        description=f"Removed {member_name} from {space_name}",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=space if space else type("FallbackTarget", (), {"id": id, "name": None})(),
            space=space,
            extra=extra,
        ),
    )


@router.get("/type/personal/", response_model=SpacePublic)
async def get_personal_space(
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.space_init_service()
    assembler = container.space_assembler()

    space = await service.get_personal_space()

    return assembler.from_space_to_model(space)

@router.get("/type/organization/", response_model=SpacePublic, dependencies=[Depends(require_permission(Permission.ADMIN))])
async def get_organization_space(
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.space_init_service()
    assembler = container.space_assembler()

    space = await service.get_or_create_tenant_space()

    return assembler.from_space_to_model(space)
