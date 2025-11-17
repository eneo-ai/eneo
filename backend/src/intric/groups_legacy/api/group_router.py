from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile

from intric.ai_models.embedding_models.datastore.datastore_models import (
    SemanticSearchRequest,
    SemanticSearchResponse,
)
from intric.authentication.auth_dependencies import get_current_active_user
from intric.collections.presentation.collection_models import (
    CollectionPublic,
    CollectionUpdate,
)
from intric.groups_legacy.api import group_protocol
from intric.groups_legacy.api.group_models import (
    CreateGroupRequest,
    GroupPublicWithMetadata,
)
from intric.info_blobs import info_blob_protocol
from intric.info_blobs.info_blob import (
    InfoBlobAdd,
    InfoBlobPublic,
    InfoBlobPublicNoText,
)
from intric.jobs.job_models import JobPublic
from intric.main.container.container import Container
from intric.main.exceptions import BadRequestException
from intric.main.models import PaginatedResponse
from intric.server import protocol
from intric.server.dependencies.container import get_container
from intric.server.models.api import InfoBlobUpsertRequest
from intric.server.protocol import responses
from intric.spaces.api.space_models import TransferRequest
from intric.users.user import UserInDB
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get(
    "/",
    response_model=PaginatedResponse[GroupPublicWithMetadata],
    deprecated=True,
)
async def get_groups(container: Container = Depends(get_container(with_user=True))):
    service = container.group_service()
    groups = await service.get_groups_for_user()
    counts = await service.get_counts_for_groups(groups)
    groups_public = group_protocol.to_groups_public_with_metadata(groups, counts)

    return protocol.to_paginated_response(groups_public)


@router.get(
    "/{id}/",
    response_model=CollectionPublic,
    responses=responses.get_responses([404]),
)
async def get_group_by_id(id: UUID, container: Container = Depends(get_container(with_user=True))):
    service = container.collection_crud_service()
    collection = await service.get_collection(id)

    return CollectionPublic.from_domain(collection=collection)


@router.post("/", response_model=GroupPublicWithMetadata, deprecated=True)
async def create_group(
    group: CreateGroupRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    """
    Valid values for `embedding_model` are the provided by `GET /api/v1/settings/models/`.
    Use the `name` field of the response from this endpoint.
    """
    service = container.group_service()
    group = await service.create_group(group)

    return group_protocol.to_group_public_with_metadata(group, num_info_blobs=0)


@router.post(
    "/{id}/",
    response_model=CollectionPublic,
    responses=responses.get_responses([404]),
)
async def update_group(
    id: UUID,
    group: CollectionUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    service = container.collection_crud_service()
    current_user = container.user()

    # Update collection
    collection_updated = await service.update_collection(collection_id=id, name=group.name)

    # Audit logging
    audit_service = container.audit_service()

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.COLLECTION_UPDATED,
        entity_type=EntityType.COLLECTION,
        entity_id=collection_updated.id,
        description=f"Updated collection '{collection_updated.name}'",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "collection_id": str(collection_updated.id),
                "collection_name": collection_updated.name,
                "space_id": str(collection_updated.space_id),
            },
            "changes": {
                "name": group.name,
            },
        },
    )

    return CollectionPublic.from_domain(collection=collection_updated)


@router.delete(
    "/{id}/",
    responses=responses.get_responses([404]),
)
async def delete_group_by_id(
    id: UUID, container: Container = Depends(get_container(with_user=True))
):
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    # Get collection info BEFORE deletion
    collection_service = container.collection_crud_service()
    current_user = container.user()
    collection = await collection_service.get_collection(id)

    # Delete collection
    service = container.group_service()
    await service.delete_group(group_id=id)

    # Audit logging
    audit_service = container.audit_service()

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.COLLECTION_DELETED,
        entity_type=EntityType.COLLECTION,
        entity_id=id,
        description=f"Deleted collection '{collection.name}'",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "collection_id": str(id),
                "collection_name": collection.name,
                "space_id": str(collection.space_id),
            },
        },
    )

    return JSONResponse({"id": str(id), "deletion_info": {"success": True}}, status_code=200)

@router.post(
    "/{id}/info-blobs/",
    response_model=PaginatedResponse[InfoBlobPublic],
    responses=responses.get_responses([400, 404, 403, 503]),
)
async def add_info_blobs(
    id: UUID,
    info_blobs: InfoBlobUpsertRequest,
    container: Container = Depends(get_container(with_user=True)),
    current_user: UserInDB = Depends(get_current_active_user),
):
    """Maximum allowed simultaneous upload is 128.

    Will be embedded using the embedding model of the group.
    """
    if len(info_blobs.info_blobs) > 128:
        raise BadRequestException("Too many info-blobs!")

    datastore = container.datastore()
    group_service = container.group_service()
    group = await group_service.get_group(id)

    info_blobs_to_add = [
        InfoBlobAdd(
            **blob.model_dump(),
            **blob.metadata.model_dump() if blob.metadata else {},
            user_id=current_user.id,
            group_id=id,
            tenant_id=current_user.tenant_id,
        )
        for blob in info_blobs.info_blobs
    ]

    service = container.info_blob_service()
    info_blobs_added = await service.add_info_blobs(group_id=id, info_blobs=info_blobs_to_add)

    # Add to datastore
    info_blobs_updated = []
    for info_blob in info_blobs_added:
        await datastore.add(info_blob=info_blob, embedding_model=group.embedding_model)
        info_blob_updated = await service.update_info_blob_size(info_blob.id)
        info_blobs_updated.append(info_blob_updated)

    # Audit logging for info blob additions
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    audit_service = container.audit_service()

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.FILE_UPLOADED,
        entity_type=EntityType.FILE,
        entity_id=id,  # Group ID
        description=f"Added {len(info_blobs_updated)} info blobs to collection/group",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "group_id": str(id),
                "blobs_count": len(info_blobs_updated),
            },
        },
    )

    info_blobs_public = [
        info_blob_protocol.to_info_blob_public(blob) for blob in info_blobs_updated
    ]

    return protocol.to_paginated_response(info_blobs_public)


@router.get(
    "/{id}/info-blobs/",
    response_model=PaginatedResponse[InfoBlobPublicNoText],
    responses=responses.get_responses([400, 404]),
)
async def get_info_blobs(
    id: UUID,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.info_blob_service()
    info_blobs_in_db = await service.get_by_group(id)

    info_blobs_public = [
        info_blob_protocol.to_info_blob_public_no_text(blob) for blob in info_blobs_in_db
    ]

    return protocol.to_paginated_response(info_blobs_public)


@router.post(
    "/{id}/info-blobs/upload/",
    response_model=JobPublic,
    status_code=202,
)
async def upload_file(
    id: UUID,
    file: UploadFile,
    container: Container = Depends(get_container(with_user=True)),
):
    """Starts a job, use the job operations to keep track of this job"""
    from intric.audit.application.audit_service import AuditService
    from intric.audit.domain.action_types import ActionType
    from intric.audit.domain.entity_types import EntityType
    from intric.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    group_service = container.group_service()
    current_user = container.user()

    # Upload file to group
    result = await group_service.add_file_to_group(
        group_id=id, file=file.file, mimetype=file.content_type, filename=file.filename
    )

    # Audit logging
    audit_service = container.audit_service()

    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.FILE_UPLOADED,
        entity_type=EntityType.FILE,
        entity_id=id,  # Use group ID as entity
        description=f"Uploaded file '{file.filename}' to collection/group",
        metadata={
            "actor": {
                "id": str(current_user.id),
                "name": current_user.username,
                "email": current_user.email,
            },
            "target": {
                "group_id": str(id),
                "filename": file.filename,
                "content_type": file.content_type,
            },
        },
    )

    return result


@router.post(
    "/{id}/searches/",
    response_model=PaginatedResponse[SemanticSearchResponse],
)
async def run_semantic_search(
    id: UUID,
    search_parameters: SemanticSearchRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.collection_crud_service()
    datastore = container.datastore()

    collection = await service.get_collection(id)

    results = await datastore.semantic_search(
        search_string=search_parameters.search_string,
        embedding_model=collection.embedding_model,
        collections=[collection],
        num_chunks=search_parameters.num_chunks,
        autocut_cutoff=search_parameters.autocut_cutoff,
    )

    return protocol.to_paginated_response(results)


@router.post("/{id}/transfer/", status_code=204)
async def transfer_group_to_space(
    id: UUID,
    transfer_req: TransferRequest,
    container: Container = Depends(get_container(with_user=True)),
):
    service = container.resource_mover_service()
    await service.move_collection_to_space(collection_id=id, space_id=transfer_req.target_space_id)
