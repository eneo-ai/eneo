from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query

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
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    space_creation_service = container.space_init_service()
    space_assembler = container.space_assembler()
    current_user = container.user()

    # Create space
    space = await space_creation_service.create_space(name=create_space_req.name)

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.SPACE_CREATED,
        entity_type=EntityType.SPACE,
        entity_id=space.id,
        description=f"Created space '{space.name}'",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "id": str(space.id),
                "name": space.name,
            },
        },
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
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.space_service()
    assembler = container.space_assembler()
    current_user = container.user()

    # Get old state
    old_space, _ = await service.get_space(id)

    def _get_model_ids_or_none(models: list[ModelId] | None):
        if models is None:
            return None

        return [model.id for model in models]

    # Get original request dict to check if security_classification_id was actually provided
    # (partial_model may have turned NOT_PROVIDED into None)
    original_request = update_space_req.model_dump(exclude_unset=True)

    if "security_classification" not in original_request:
        security_classification = NOT_PROVIDED
    else:
        security_classification = update_space_req.security_classification

    space = await service.update_space(
        id=id,
        name=update_space_req.name,
        description=update_space_req.description,
        embedding_model_ids=_get_model_ids_or_none(update_space_req.embedding_models),
        completion_model_ids=_get_model_ids_or_none(update_space_req.completion_models),
        transcription_model_ids=_get_model_ids_or_none(update_space_req.transcription_models),
        security_classification=security_classification,
    )

    # Track changes
    changes = {}
    if update_space_req.name and update_space_req.name != old_space.name:
        changes["name"] = {"old": old_space.name, "new": update_space_req.name}
    if update_space_req.description is not None:
        changes["description"] = {"old": old_space.description, "new": update_space_req.description}

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.SPACE_UPDATED,
        entity_type=EntityType.SPACE,
        entity_id=id,
        description=f"Updated space '{space.name}'",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "id": str(space.id),
                "name": space.name,
            },
            "changes": changes,
        },
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

    await service.delete_space(id=id)


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
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.assistant_service()
    assembler = container.assistant_assembler()
    current_user = container.user()

    # Create assistant
    assistant, permissions = await service.create_assistant(
        name=assistant_in.name, space_id=id, template_data=assistant_in.from_template
    )

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.ASSISTANT_CREATED,
        entity_type=EntityType.ASSISTANT,
        entity_id=assistant.id,
        description=f"Created assistant '{assistant.name}' in space",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "id": str(assistant.id),
                "name": assistant.name,
                "space_id": str(id),
            },
        },
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

    group_chat = await service.create_group_chat(space_id=id, name=group_chat_in.name)

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
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    space_service = container.space_service()
    app_service = container.app_service()
    assembler = container.app_assembler()
    current_user = container.user()

    # Create app
    space = await space_service.get_space(id)
    app, permissions = await app_service.create_app(
        name=create_service_req.name,
        space=space,
        template_data=create_service_req.from_template,
    )

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.APP_CREATED,
        entity_type=EntityType.APP,
        entity_id=app.id,
        description=f"Created app '{app.name}' in space",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "id": str(app.id),
                "name": app.name,
                "space_id": str(id),
            },
        },
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
    embedding_model_id = group.embedding_model.id if group.embedding_model else None

    created_collection = await svc.create_collection(
        name=group.name,
        space_id=id,
        embedding_model_id=embedding_model_id,
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

    website = await service.create_website(
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

    return WebsitePublic.from_domain(website)


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

    knowledge = await service.create_space_integration_knowledge(
        user_integration_id=user_integration_id,
        name=data.name,
        space_id=id,
        embedding_model_id=data.embedding_model.id,
        url=data.url,
        key=data.key,
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
    await service.remove_knowledge(space_id=id, integration_knowledge_id=integration_knowledge_id)


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
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.space_service()
    current_user = container.user()

    # Add member
    member = await service.add_member(
        id, member_id=add_space_member_req.id, role=add_space_member_req.role
    )

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.SPACE_MEMBER_ADDED,
        entity_type=EntityType.SPACE,
        entity_id=id,
        description=f"Added member to space (role: {add_space_member_req.role})",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "space_id": str(id),
                "member_id": str(add_space_member_req.id),
                "role": add_space_member_req.role,
            },
        },
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
    service = container.space_service()

    return await service.change_role_of_member(id, user_id, update_space_member_req.role)


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
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.space_service()
    current_user = container.user()

    # Remove member
    await service.remove_member(id, user_id)

    # Audit logging
    session = container.session()
    audit_repo = AuditLogRepositoryImpl(session)
    audit_service = AuditService(audit_repo)

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.SPACE_MEMBER_REMOVED,
        entity_type=EntityType.SPACE,
        entity_id=id,
        description="Removed member from space",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "space_id": str(id),
                "member_id": str(user_id),
            },
        },
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
