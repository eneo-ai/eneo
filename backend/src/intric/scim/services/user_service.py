from typing import Any, cast
from uuid import UUID

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.database.tables.users_table import Users as UserModel
from intric.main.logging import get_logger
from intric.scim.domain.errors import (
    ScimUserConflictError,
    ScimUserNotFoundError,
    ScimValidationError,
)
from intric.scim.repositories.user_repository import ScimUserRepository
from intric.scim.schemas.common import ScimFilter, ScimSort
from intric.scim.schemas.user import (
    PatchOperation,
    ScimEmail,
    ScimMeta,
    ScimUser,
    ScimUserRequest,
    ScimUserState,
)

logger = get_logger(__name__)

_SCIM_ACTOR = {"type": "scim", "via": "bearer_token"}


def _resolve_email(data: ScimUserRequest) -> str:
    email = (
        next((e.value for e in data.emails if e.primary), None)
        or (data.emails[0].value if data.emails else None)
        or (data.userName if "@" in data.userName else None)
    )
    if email is None:
        raise ScimValidationError("An email address is required")
    return email


def _to_scim_user(model: UserModel) -> ScimUser:
    return ScimUser(
        id=str(model.id),
        externalId=model.external_id,
        userName=model.username or model.email,
        emails=[ScimEmail(value=model.email, primary=True)] if model.email else [],
        active=model.state == ScimUserState.ACTIVE,
        meta=ScimMeta(
            resourceType="User",
            created=model.created_at,
            lastModified=model.updated_at,
        ),
    )


def _user_target(model: UserModel) -> dict[str, Any]:
    return {
        "id": str(model.id),
        "username": model.username,
        "email": model.email,
        "external_id": model.external_id,
    }


def _is_different_user(model: UserModel | None, user_id: UUID | None) -> bool:
    return model is not None and (user_id is None or model.id != user_id)


class ScimUserService:
    def __init__(
        self,
        repository: ScimUserRepository,
        tenant_id: UUID,
        audit_service: AuditService | None = None,
    ) -> None:
        self._repository = repository
        self._tenant_id = tenant_id
        self._audit = audit_service

    async def _log(self, action: ActionType, entity_id: UUID, description: str, target: dict[str, Any]) -> None:
        if self._audit is None:
            return
        await self._audit.log(
            tenant_id=self._tenant_id,
            actor_id=None,
            actor_type=ActorType.SYSTEM,
            action=action,
            entity_type=EntityType.USER,
            entity_id=entity_id,
            description=description,
            metadata={"actor": _SCIM_ACTOR, "target": target},
        )

    async def _validate_unique_fields(
        self,
        *,
        user_id: UUID | None = None,
        username: str,
        email: str,
        external_id: str | None,
    ) -> None:
        username_owner = await self._repository.get_by_username(
            username, tenant_id=self._tenant_id
        )
        if _is_different_user(username_owner, user_id):
            raise ScimUserConflictError(f"User '{username}' already exists")

        email_owner = await self._repository.get_by_email(
            email, tenant_id=self._tenant_id
        )
        if _is_different_user(email_owner, user_id):
            raise ScimUserConflictError(f"Email '{email}' already exists")

        if await self._repository.email_exists_in_other_tenant(email, self._tenant_id):
            raise ScimUserConflictError(
                f"Email '{email}' is already in use by another tenant"
            )

        if external_id is not None:
            external_id_owner = await self._repository.get_by_external_id(
                external_id, tenant_id=self._tenant_id
            )
            if _is_different_user(external_id_owner, user_id):
                raise ScimUserConflictError(
                    f"External ID '{external_id}' already exists"
                )

    async def create_user(self, data: ScimUserRequest) -> ScimUser:
        existing = await self._repository.get_by_username(data.userName, tenant_id=self._tenant_id)
        if existing is None and "@" in data.userName:
            search_email = (
                next((e.value for e in data.emails if e.primary), None)
                or (data.emails[0].value if data.emails else None)
                or data.userName
            )
            existing = await self._repository.get_by_email(search_email, tenant_id=self._tenant_id)
            if existing is not None:
                if data.externalId is not None:
                    external_id_owner = await self._repository.get_by_external_id(
                        data.externalId, tenant_id=self._tenant_id
                    )
                    if _is_different_user(external_id_owner, existing.id):
                        raise ScimUserConflictError(
                            f"External ID '{data.externalId}' already exists"
                        )
                existing.external_id = data.externalId
                existing.username = data.userName
                result = _to_scim_user(await self._repository.update(existing))
                logger.info(
                    "scim.user.reconciled",
                    extra={
                        "tenant_id": str(self._tenant_id),
                        "user_id": str(existing.id),
                        "username": existing.username,
                        "external_id": data.externalId,
                    },
                )
                await self._log(
                    ActionType.SCIM_USER_RECONCILED,
                    existing.id,
                    f"SCIM reconciled existing user '{existing.username}' by email",
                    _user_target(existing),
                )
                return result
        if existing is not None:
            if existing.state == ScimUserState.ACTIVE:
                logger.warning(
                    "scim.user.conflict",
                    extra={
                        "tenant_id": str(self._tenant_id),
                        "username": data.userName,
                        "external_id": data.externalId,
                    },
                )
                raise ScimUserConflictError(f"User '{data.userName}' already exists")
            if data.externalId is not None:
                external_id_owner = await self._repository.get_by_external_id(
                    data.externalId, tenant_id=self._tenant_id
                )
                if _is_different_user(external_id_owner, existing.id):
                    raise ScimUserConflictError(
                        f"External ID '{data.externalId}' already exists"
                    )
            existing.state = ScimUserState.ACTIVE
            existing.external_id = data.externalId
            result = _to_scim_user(await self._repository.update(existing))
            logger.info(
                "scim.user.reactivated",
                extra={
                    "tenant_id": str(self._tenant_id),
                    "user_id": str(existing.id),
                    "username": existing.username,
                    "external_id": data.externalId,
                },
            )
            await self._log(
                ActionType.SCIM_USER_REACTIVATED,
                existing.id,
                f"SCIM reactivated user '{existing.username}'",
                _user_target(existing),
            )
            return result
        email = _resolve_email(data)
        await self._validate_unique_fields(
            username=data.userName,
            email=email,
            external_id=data.externalId,
        )
        model = UserModel(  # pyright: ignore[reportCallIssue]
            external_id=data.externalId,  # pyright: ignore[reportCallIssue]
            username=data.userName,  # pyright: ignore[reportCallIssue]
            email=email,  # pyright: ignore[reportCallIssue]
            state=ScimUserState.ACTIVE,  # pyright: ignore[reportCallIssue]
            tenant_id=self._tenant_id,  # pyright: ignore[reportCallIssue]
        )
        model = await self._repository.create(model)
        logger.info(
            "scim.user.created",
            extra={
                "tenant_id": str(self._tenant_id),
                "user_id": str(model.id),
                "username": model.username,
                "external_id": model.external_id,
            },
        )
        await self._log(
            ActionType.SCIM_USER_PROVISIONED,
            model.id,
            f"SCIM provisioned new user '{model.username}'",
            _user_target(model),
        )
        return _to_scim_user(model)

    async def get_user(self, user_id: UUID) -> ScimUser:
        model = await self._repository.get_by_id(user_id, tenant_id=self._tenant_id)
        if model is None:
            raise ScimUserNotFoundError(f"User '{user_id}' not found")
        logger.debug(
            "scim.user.get",
            extra={"tenant_id": str(self._tenant_id), "user_id": str(user_id)},
        )
        return _to_scim_user(model)

    async def list_users(
        self,
        filter_str: str | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
        start_index: int = 1,
        count: int | None = None,
    ) -> tuple[list[ScimUser], int]:
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
            "scim.user.list",
            extra={"tenant_id": str(self._tenant_id), "total": total, "returned": len(models)},
        )
        return [_to_scim_user(m) for m in models], total

    async def replace_user(self, user_id: UUID, data: ScimUserRequest) -> ScimUser:
        model = await self._repository.get_by_id(user_id, tenant_id=self._tenant_id)
        if model is None or model.state != ScimUserState.ACTIVE:
            raise ScimUserNotFoundError(f"User '{user_id}' not found")
        email = _resolve_email(data)
        await self._validate_unique_fields(
            user_id=model.id,
            username=data.userName,
            email=email,
            external_id=data.externalId,
        )
        model.external_id = data.externalId
        model.username = data.userName
        model.email = email
        model.state = ScimUserState.ACTIVE if data.active else ScimUserState.INACTIVE
        model = await self._repository.update(model)
        logger.info(
            "scim.user.replaced",
            extra={
                "tenant_id": str(self._tenant_id),
                "user_id": str(model.id),
                "username": model.username,
                "external_id": model.external_id,
                "active": data.active,
            },
        )
        await self._log(
            ActionType.SCIM_USER_UPDATED,
            model.id,
            f"SCIM replaced user '{model.username}' (PUT)",
            _user_target(model),
        )
        return _to_scim_user(model)

    async def patch_user(self, user_id: UUID, operations: list[PatchOperation]) -> ScimUser:
        model = await self._repository.get_by_id(user_id, tenant_id=self._tenant_id)
        if model is None or model.state != ScimUserState.ACTIVE:
            raise ScimUserNotFoundError(f"User '{user_id}' not found")
        for op in operations:
            _apply_patch_operation(model, op)
        await self._validate_unique_fields(
            user_id=model.id,
            username=model.username or model.email,
            email=model.email,
            external_id=model.external_id,
        )
        model = await self._repository.update(model)
        logger.info(
            "scim.user.patched",
            extra={
                "tenant_id": str(self._tenant_id),
                "user_id": str(model.id),
                "username": model.username,
                "ops": [op.op + ":" + (op.path or "") for op in operations],
            },
        )
        await self._log(
            ActionType.SCIM_USER_UPDATED,
            model.id,
            f"SCIM patched user '{model.username}' (PATCH)",
            {**_user_target(model), "ops": [op.op + ":" + (op.path or "") for op in operations]},
        )
        return _to_scim_user(model)

    async def delete_user(self, user_id: UUID) -> None:
        model = await self._repository.get_by_id(user_id, tenant_id=self._tenant_id)
        if model is None or model.state != ScimUserState.ACTIVE:
            raise ScimUserNotFoundError(f"User '{user_id}' not found")
        model.state = ScimUserState.INACTIVE
        await self._repository.update(model)
        logger.info(
            "scim.user.deprovisioned",
            extra={
                "tenant_id": str(self._tenant_id),
                "user_id": str(model.id),
                "username": model.username,
                "external_id": model.external_id,
            },
        )
        await self._log(
            ActionType.SCIM_USER_DEPROVISIONED,
            model.id,
            f"SCIM deprovisioned user '{model.username}'",
            _user_target(model),
        )


def _apply_user_attr(model: UserModel, attr: str, value: Any) -> None:
    if attr == "active":
        model.state = ScimUserState.ACTIVE if bool(value) else ScimUserState.INACTIVE
    elif attr == "username":
        model.username = str(value) if value is not None else model.username
    elif attr == "externalid":
        model.external_id = str(value) if value is not None else None
    elif attr == "emails":
        entries: list[Any] = value if isinstance(value, list) else [value]  # pyright: ignore[reportUnknownVariableType]
        primary: str | None = next(
            (str(e["value"]) for e in entries if isinstance(e, dict) and e.get("primary")),  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
            None,
        ) or (
            str(entries[0]["value"]) if entries and isinstance(entries[0], dict) else None  # pyright: ignore[reportUnknownArgumentType]
        )
        if primary:
            model.email = primary


def _apply_patch_operation(model: UserModel, op: PatchOperation) -> None:
    if op.op.lower() not in {"replace", "add"}:
        return
    if op.path is None and isinstance(op.value, dict):
        for key, val in cast(dict[str, Any], op.value).items():  # pyright: ignore[reportUnknownMemberType]
            _apply_user_attr(model, key.lower(), val)
        return
    _apply_user_attr(model, (op.path or "").lower(), op.value)  # pyright: ignore[reportUnknownMemberType]
