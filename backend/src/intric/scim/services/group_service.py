import re
from uuid import UUID

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.database.tables.user_groups_table import UserGroups as GroupModel
from intric.main.logging import get_logger
from intric.scim.domain.errors import (
    ScimGroupConflictError,
    ScimGroupNotFoundError,
    ScimValidationError,
)
from intric.scim.repositories.group_repository import ScimGroupRepository
from intric.scim.schemas.common import ScimFilter, ScimSort
from intric.scim.schemas.group import ScimGroup, ScimGroupMember, ScimGroupRequest
from intric.scim.schemas.user import PatchOperation, ScimMeta

logger = get_logger(__name__)

_MEMBER_VALUE_RE = re.compile(r'members\[value\s+eq\s+"([^"]+)"\]', re.IGNORECASE)
_SCIM_ACTOR = {"type": "scim", "via": "bearer_token"}


def _to_scim_group(model: GroupModel) -> ScimGroup:
    return ScimGroup(
        id=str(model.id),
        externalId=model.external_id,
        displayName=model.name,
        members=[
            ScimGroupMember(value=str(m.id), display=m.username)
            for m in model.users
        ],
        meta=ScimMeta(
            resourceType="Group",
            created=model.created_at,
            lastModified=model.updated_at,
        ),
    )


def _group_target(model: GroupModel) -> dict:
    return {
        "id": str(model.id),
        "display_name": model.name,
        "external_id": model.external_id,
    }


def _is_different_group(model: GroupModel | None, group_id: UUID | None) -> bool:
    return model is not None and (group_id is None or model.id != group_id)


async def _validate_member_ids(
    repo: ScimGroupRepository,
    tenant_id: UUID,
    member_ids: list[UUID],
) -> None:
    if not member_ids:
        return

    valid_member_ids = await repo.get_user_ids_in_tenant(member_ids, tenant_id)
    invalid_member_ids = sorted(
        set(member_ids) - valid_member_ids,
        key=str,
    )
    if invalid_member_ids:
        raise ScimValidationError(
            "Group members must belong to the authenticated tenant: "
            + ", ".join(str(member_id) for member_id in invalid_member_ids)
        )


class ScimGroupService:
    def __init__(
        self,
        repository: ScimGroupRepository,
        tenant_id: UUID,
        audit_service: AuditService | None = None,
    ) -> None:
        self._repository = repository
        self._tenant_id = tenant_id
        self._audit = audit_service

    async def _log(self, action: ActionType, entity_id: UUID, description: str, target: dict) -> None:
        if self._audit is None:
            return
        await self._audit.log(
            tenant_id=self._tenant_id,
            actor_id=None,
            actor_type=ActorType.SYSTEM,
            action=action,
            entity_type=EntityType.USER_GROUP,
            entity_id=entity_id,
            description=description,
            metadata={"actor": _SCIM_ACTOR, "target": target},
        )

    async def _validate_unique_display_name(
        self,
        display_name: str,
        group_id: UUID | None = None,
    ) -> None:
        existing = await self._repository.get_by_name(
            display_name, tenant_id=self._tenant_id
        )
        if _is_different_group(existing, group_id):
            raise ScimGroupConflictError(f"Group '{display_name}' already exists")

    async def create_group(self, data: ScimGroupRequest) -> ScimGroup:
        try:
            await self._validate_unique_display_name(data.displayName)
        except ScimGroupConflictError:
            logger.warning(
                "scim.group.conflict",
                extra={
                    "tenant_id": str(self._tenant_id),
                    "display_name": data.displayName,
                    "external_id": data.externalId,
                },
            )
            raise
        model = GroupModel(
            external_id=data.externalId,
            name=data.displayName,
            tenant_id=self._tenant_id,
        )
        member_ids = [UUID(m.value) for m in data.members]
        await _validate_member_ids(self._repository, self._tenant_id, member_ids)
        model = await self._repository.create(model)
        if data.members:
            await self._repository.set_members(model.id, member_ids)
        model = await self._repository.get_by_id(model.id, tenant_id=self._tenant_id)
        logger.info(
            "scim.group.created",
            extra={
                "tenant_id": str(self._tenant_id),
                "group_id": str(model.id),
                "display_name": model.name,
                "external_id": model.external_id,
                "member_count": len(data.members),
            },
        )
        await self._log(
            ActionType.SCIM_GROUP_CREATED,
            model.id,
            f"SCIM created group '{model.name}'",
            {**_group_target(model), "member_count": len(data.members)},
        )
        return _to_scim_group(model)

    async def get_group(self, group_id: UUID) -> ScimGroup:
        model = await self._repository.get_by_id(group_id, tenant_id=self._tenant_id)
        if model is None:
            raise ScimGroupNotFoundError(f"Group '{group_id}' not found")
        logger.debug(
            "scim.group.get",
            extra={"tenant_id": str(self._tenant_id), "group_id": str(group_id)},
        )
        return _to_scim_group(model)

    async def list_groups(
        self,
        filter_str: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        start_index: int = 1,
        count: int | None = None,
    ) -> tuple[list[ScimGroup], int]:
        scim_filter = ScimFilter.parse(filter_str) if filter_str else None
        scim_sort = ScimSort.parse(sort_by, sort_order)
        offset = max(0, start_index - 1)
        total = await self._repository.count(tenant_id=self._tenant_id, scim_filter=scim_filter)
        models = await self._repository.list(
            tenant_id=self._tenant_id,
            scim_filter=scim_filter,
            scim_sort=scim_sort,
            offset=offset,
            limit=count,
        )
        logger.debug(
            "scim.group.list",
            extra={"tenant_id": str(self._tenant_id), "total": total, "returned": len(models)},
        )
        return [_to_scim_group(m) for m in models], total

    async def replace_group(self, group_id: UUID, data: ScimGroupRequest) -> ScimGroup:
        model = await self._repository.get_by_id(group_id, tenant_id=self._tenant_id)
        if model is None:
            raise ScimGroupNotFoundError(f"Group '{group_id}' not found")
        await self._validate_unique_display_name(data.displayName, group_id=model.id)
        model.external_id = data.externalId
        model.name = data.displayName
        member_ids = [UUID(m.value) for m in data.members]
        await _validate_member_ids(self._repository, self._tenant_id, member_ids)
        await self._repository.set_members(group_id, member_ids)
        await self._repository.update(model)
        model = await self._repository.get_by_id(group_id, tenant_id=self._tenant_id)
        logger.info(
            "scim.group.replaced",
            extra={
                "tenant_id": str(self._tenant_id),
                "group_id": str(model.id),
                "display_name": model.name,
                "external_id": model.external_id,
                "member_count": len(data.members),
            },
        )
        await self._log(
            ActionType.SCIM_GROUP_UPDATED,
            model.id,
            f"SCIM replaced group '{model.name}' (PUT)",
            {**_group_target(model), "member_count": len(data.members)},
        )
        return _to_scim_group(model)

    async def patch_group(self, group_id: UUID, operations: list[PatchOperation]) -> ScimGroup:
        model = await self._repository.get_by_id(group_id, tenant_id=self._tenant_id)
        if model is None:
            raise ScimGroupNotFoundError(f"Group '{group_id}' not found")
        for op in operations:
            await _apply_patch_operation(
                self._repository,
                self._tenant_id,
                group_id,
                model,
                op,
            )
        await self._repository.update(model)
        model = await self._repository.get_by_id(group_id, tenant_id=self._tenant_id)
        logger.info(
            "scim.group.patched",
            extra={
                "tenant_id": str(self._tenant_id),
                "group_id": str(model.id),
                "display_name": model.name,
                "ops": [op.op + ":" + (op.path or "") for op in operations],
            },
        )
        await self._log(
            ActionType.SCIM_GROUP_UPDATED,
            model.id,
            f"SCIM patched group '{model.name}' (PATCH)",
            {**_group_target(model), "ops": [op.op + ":" + (op.path or "") for op in operations]},
        )
        return _to_scim_group(model)

    async def delete_group(self, group_id: UUID) -> None:
        model = await self._repository.get_by_id(group_id, tenant_id=self._tenant_id)
        if model is None:
            raise ScimGroupNotFoundError(f"Group '{group_id}' not found")
        await self._repository.delete(group_id)
        logger.info(
            "scim.group.deleted",
            extra={
                "tenant_id": str(self._tenant_id),
                "group_id": str(group_id),
                "display_name": model.name,
                "external_id": model.external_id,
            },
        )
        await self._log(
            ActionType.SCIM_GROUP_DELETED,
            group_id,
            f"SCIM deleted group '{model.name}'",
            _group_target(model),
        )


async def _apply_patch_operation(
    repo: ScimGroupRepository,
    tenant_id: UUID,
    group_id: UUID,
    model: GroupModel,
    op: PatchOperation,
) -> None:
    op_lower = op.op.lower()
    path = (op.path or "").lower()

    if path == "displayname" and op_lower in {"replace", "add"}:
        display_name = str(op.value)
        existing = await repo.get_by_name(display_name, tenant_id=tenant_id)
        if _is_different_group(existing, group_id):
            raise ScimGroupConflictError(f"Group '{display_name}' already exists")
        model.name = display_name
        return

    if path == "members" and op_lower == "add":
        values = op.value if isinstance(op.value, list) else [op.value]
        member_ids = [
            UUID(entry["value"] if isinstance(entry, dict) else entry.value)
            for entry in values
        ]
        await _validate_member_ids(repo, tenant_id, member_ids)
        for user_id in member_ids:
            await repo.add_member(group_id, user_id)
        return

    if op_lower == "remove" and op.path:
        match = _MEMBER_VALUE_RE.match(op.path)
        if match:
            await repo.remove_member(group_id, UUID(match.group(1)))
