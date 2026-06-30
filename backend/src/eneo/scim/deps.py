from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.application.audit_service import AuditService
from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.database.database import get_session_with_transaction
from eneo.scim.auth import require_scim_auth
from eneo.scim.repositories.group_repository import ScimGroupRepository
from eneo.scim.repositories.user_repository import ScimUserRepository
from eneo.scim.services.group_service import ScimGroupService
from eneo.scim.services.user_service import ScimUserService


def get_scim_audit_service(
    session: AsyncSession = Depends(get_session_with_transaction),
) -> AuditService:
    return AuditService(repository=AuditLogRepositoryImpl(session=session))


def get_scim_user_repository(
    session: AsyncSession = Depends(get_session_with_transaction),
) -> ScimUserRepository:
    return ScimUserRepository(session=session)


def get_scim_user_service(
    tenant_id: UUID = Depends(require_scim_auth),
    repository: ScimUserRepository = Depends(get_scim_user_repository),
    audit_service: AuditService = Depends(get_scim_audit_service),
) -> ScimUserService:
    return ScimUserService(
        repository=repository, tenant_id=tenant_id, audit_service=audit_service
    )


def get_scim_group_repository(
    session: AsyncSession = Depends(get_session_with_transaction),
) -> ScimGroupRepository:
    return ScimGroupRepository(session=session)


def get_scim_group_service(
    tenant_id: UUID = Depends(require_scim_auth),
    repository: ScimGroupRepository = Depends(get_scim_group_repository),
    audit_service: AuditService = Depends(get_scim_audit_service),
) -> ScimGroupService:
    return ScimGroupService(
        repository=repository, tenant_id=tenant_id, audit_service=audit_service
    )
