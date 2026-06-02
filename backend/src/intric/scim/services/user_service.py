import re
from datetime import datetime, timezone
from typing import Any, cast
from uuid import UUID

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.actor_types import ActorType
from intric.audit.domain.entity_types import EntityType
from intric.database.tables.users_table import Users as UserModel
from intric.main.logging import get_logger
from intric.scim.domain.errors import (
    ScimInvalidFilterError,
    ScimUserConflictError,
    ScimUserNotFoundError,
    ScimValidationError,
)
from intric.scim.repositories.user_repository import ScimUserRepository
from intric.scim.schemas.common import ScimFilter, ScimSort, clamp_count
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

    async def _log(
        self,
        action: ActionType,
        entity_id: UUID,
        description: str,
        target: dict[str, Any],
    ) -> None:
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
            # WARNING: cross-tenant collision is an unusual signal — could be a
            # legitimate misconfiguration (same person under two SCIM-managed
            # tenants), an org-wide email being added in two places, or worth
            # noting in any case. Without this log the operator only sees a
            # 409 in the request log with no explanation.
            logger.warning(
                "scim.user.cross_tenant_email_conflict",
                extra={
                    "tenant_id": str(self._tenant_id),
                    "email": email,
                },
            )
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
        existing = await self._repository.get_by_username(
            data.userName, tenant_id=self._tenant_id
        )
        if existing is None and "@" in data.userName:
            search_email = (
                next((e.value for e in data.emails if e.primary), None)
                or (data.emails[0].value if data.emails else None)
                or data.userName
            )
            existing = await self._repository.get_by_email(
                search_email, tenant_id=self._tenant_id
            )
            if existing is not None:
                # Reconciliation is the migration path for claiming a
                # pre-existing local user (manual/JIT, external_id IS NULL)
                # into SCIM management. If the matched user already carries an
                # external_id, silently rebinding it would let the SCIM client
                # take over an account that already belongs to a different
                # SCIM identity — refuse instead and let an operator resolve.
                if existing.external_id is not None:
                    logger.warning(
                        "scim.user.reconcile_refused_existing_external_id",
                        extra={
                            "tenant_id": str(self._tenant_id),
                            "user_id": str(existing.id),
                            "email": existing.email,
                            "existing_external_id": existing.external_id,
                            "incoming_external_id": data.externalId,
                            "incoming_username": data.userName,
                        },
                    )
                    raise ScimUserConflictError(
                        f"User with email '{existing.email}' already exists "
                        f"under a different external_id"
                    )
                if data.externalId is not None:
                    external_id_owner = await self._repository.get_by_external_id(
                        data.externalId, tenant_id=self._tenant_id
                    )
                    if _is_different_user(external_id_owner, existing.id):
                        raise ScimUserConflictError(
                            f"External ID '{data.externalId}' already exists"
                        )
                # WARNING (not INFO): reconciliation rebinds an existing local
                # account's identity to a SCIM-supplied externalId/username.
                # Bounded by who can authenticate as SCIM (sysadmin-minted
                # token, one IdP per tenant), but worth surfacing in operator
                # monitoring rather than only the audit archive.
                previous_username = existing.username
                existing.external_id = data.externalId
                existing.username = data.userName
                # Honour SCIM `active`: if the IdP claims this local account
                # while signalling it as inactive, the reconciled user must end
                # up deprovisioned rather than silently staying active.
                _set_active(existing, data.active)
                result = _to_scim_user(await self._repository.update(existing))
                logger.warning(
                    "scim.user.reconciled",
                    extra={
                        "tenant_id": str(self._tenant_id),
                        "user_id": str(existing.id),
                        "email": existing.email,
                        "previous_username": previous_username,
                        "new_username": data.userName,
                        "new_external_id": data.externalId,
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
            existing.external_id = data.externalId
            # Honour SCIM `active`: a create targeting an already soft-deleted
            # row must only reactivate it when the payload says active=true.
            # active=false keeps the row deprovisioned (it stays DELETED) while
            # still rebinding the externalId.
            _set_active(existing, data.active)
            result = _to_scim_user(await self._repository.update(existing))
            if data.active:
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
            else:
                logger.info(
                    "scim.user.reprovisioned_inactive",
                    extra={
                        "tenant_id": str(self._tenant_id),
                        "user_id": str(existing.id),
                        "username": existing.username,
                        "external_id": data.externalId,
                    },
                )
                await self._log(
                    ActionType.SCIM_USER_UPDATED,
                    existing.id,
                    f"SCIM re-provisioned user '{existing.username}' as inactive",
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
        # Honour SCIM `active`: an IdP that provisions a user as active=false
        # (e.g. a disabled account synced ahead of activation) must NOT result
        # in an active Eneo account. _set_active maps false → soft-deleted.
        _set_active(model, data.active)
        model = await self._repository.create(model)
        logger.info(
            "scim.user.created",
            extra={
                "tenant_id": str(self._tenant_id),
                "user_id": str(model.id),
                "username": model.username,
                "external_id": model.external_id,
                "active": data.active,
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
        scim_filter = None
        if filter_str:
            scim_filter = ScimFilter.parse(filter_str)
            if scim_filter is None:
                raise ScimInvalidFilterError(
                    f"Filter expression could not be parsed: '{filter_str}'"
                )
        scim_sort = ScimSort.parse(sort_by, sort_order)
        offset = max(0, start_index - 1)
        # Cap the page size to the advertised maxResults (clamp_count also
        # bounds an omitted count, so an unfiltered list never dumps the whole
        # tenant).
        limit = clamp_count(count)
        total = await self._repository.count(
            tenant_id=self._tenant_id, scim_filter=scim_filter
        )
        models = await self._repository.list(
            tenant_id=self._tenant_id,
            scim_filter=scim_filter,
            scim_sort=scim_sort,
            offset=offset,
            limit=limit,
        )
        logger.debug(
            "scim.user.list",
            extra={
                "tenant_id": str(self._tenant_id),
                "total": total,
                "returned": len(models),
            },
        )
        return [_to_scim_user(m) for m in models], total

    async def replace_user(self, user_id: UUID, data: ScimUserRequest) -> ScimUser:
        model = await self._repository.get_by_id(user_id, tenant_id=self._tenant_id)
        if model is None:
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
        _set_active(model, data.active)
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

    async def patch_user(
        self, user_id: UUID, operations: list[PatchOperation]
    ) -> ScimUser:
        model = await self._repository.get_by_id(user_id, tenant_id=self._tenant_id)
        if model is None:
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
            {
                **_user_target(model),
                "ops": [op.op + ":" + (op.path or "") for op in operations],
            },
        )
        return _to_scim_user(model)

    async def delete_user(self, user_id: UUID) -> None:
        model = await self._repository.get_by_id(user_id, tenant_id=self._tenant_id)
        if model is None:
            raise ScimUserNotFoundError(f"User '{user_id}' not found")
        if model.state == ScimUserState.DELETED:
            return
        _set_active(model, False)
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


def _set_active(model: UserModel, active: bool) -> None:
    """Map SCIM `active` boolean to Eneo soft-delete state idempotently.

    active=true  → state=ACTIVE,  deleted_at=NULL
    active=false → state=DELETED, deleted_at=now() (preserved if already DELETED)
    """
    if active:
        model.state = ScimUserState.ACTIVE
        model.deleted_at = None
    elif model.state != ScimUserState.DELETED:
        model.state = ScimUserState.DELETED
        model.deleted_at = datetime.now(timezone.utc)


_PATCH_PATH_BASE_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)")


def _parse_patch_path(path: str) -> str:
    """Extract the base attribute name from a SCIM PATCH path.

    SCIM RFC 7644 §3.5.2 allows paths like:
      - "userName"                       (simple)
      - "emails[type eq \"work\"].value" (filter + sub-attribute)
      - "name.givenName"                 (sub-attribute only)

    Azure Entra ID uses the filter-expression form for multi-valued attributes
    such as emails. Eneo's user model is flat (one email per user), so we only
    need the base attribute name to dispatch the update; the filter and
    sub-attribute selector are discarded.
    """
    match = _PATCH_PATH_BASE_RE.match(path)
    return match.group(1).lower() if match else path.lower()


def _coerce_active(value: Any) -> bool:
    """Coerce a SCIM `active` value to a Python bool.

    Azure Entra ID sends `active` as the string "True"/"False" in PATCH
    operations (documented quirk, not RFC-compliant but established). Python's
    bool() returns True for any non-empty string — including "False" — so
    without explicit handling a soft-delete from Azure would silently leave
    the user active and Azure (which gets 200 OK back) would never retry.
    """
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def _apply_user_attr(model: UserModel, attr: str, value: Any) -> None:
    if attr == "active":
        _set_active(model, _coerce_active(value))
    elif attr == "username":
        model.username = str(value) if value is not None else model.username
    elif attr == "externalid":
        model.external_id = str(value) if value is not None else None
    elif attr == "emails":
        # Scalar form: Azure sends `emails[type eq "work"].value = "x@y.com"`,
        # which after _parse_patch_path reduces to attr=emails, value=string.
        if isinstance(value, str):
            model.email = value
            return
        # Array form: PUT body or path-less PATCH passes a list of email dicts.
        raw_entries: list[Any] = (
            cast(list[Any], value) if isinstance(value, list) else [value]
        )
        entries: list[dict[str, Any]] = [
            cast(dict[str, Any], e) for e in raw_entries if isinstance(e, dict)
        ]
        primary: str | None = next(
            (str(e["value"]) for e in entries if e.get("primary")),
            None,
        ) or (str(entries[0]["value"]) if entries else None)
        if primary:
            model.email = primary


def _apply_patch_operation(model: UserModel, op: PatchOperation) -> None:
    if op.op.lower() not in {"replace", "add"}:
        return
    if op.path is None and isinstance(op.value, dict):
        for key, val in cast(dict[str, Any], op.value).items():  # pyright: ignore[reportUnknownMemberType]
            _apply_user_attr(model, key.lower(), val)
        return
    _apply_user_attr(model, _parse_patch_path(op.path or ""), op.value)  # pyright: ignore[reportUnknownMemberType]
