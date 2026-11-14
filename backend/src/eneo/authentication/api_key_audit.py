"""The audit entry for an API key that was refused."""

from enum import Enum
from typing import TYPE_CHECKING

from starlette.requests import Request

from eneo.audit.application.audit_metadata import AuditMetadata
from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.actor_types import ActorType
from eneo.audit.domain.entity_types import EntityType
from eneo.audit.domain.outcome import Outcome
from eneo.authentication.api_key_resolver import ApiKeyValidationError
from eneo.authentication.auth_models import ApiKeyV2InDB
from eneo.main.logging import get_logger

if TYPE_CHECKING:
    from eneo.users.user import UserInDB

logger = get_logger(__name__)


async def log_api_key_auth_failed(
    audit_service: AuditService | None,
    user: "UserInDB",
    key: ApiKeyV2InDB,
    exc: ApiKeyValidationError,
    *,
    request: Request | None = None,
) -> None:
    if audit_service is None:
        return

    extra: dict[str, object] = {
        "code": exc.code,
        "error_message": exc.message,
        "scope_type": key.scope_type,
        "scope_id": str(key.scope_id) if key.scope_id else None,
        "permission": key.permission,
        "key_type": key.key_type,
        "key_prefix": key.key_prefix,
    }
    if exc.context is not None:
        extra.update(exc.context)
    if request is not None:
        route = request.scope.get("route")
        extra["request_path"] = route.path if route else request.url.path
        extra["method"] = request.method
        origin = request.headers.get("origin")
        if origin:
            extra["origin"] = origin

    ownership_raw = getattr(key, "ownership", "user")
    ownership = (
        ownership_raw.value if isinstance(ownership_raw, Enum) else str(ownership_raw)
    )
    is_service = ownership == "service"

    if is_service:
        metadata = AuditMetadata.system_action(
            description="Service API key auth failed",
            target=key,
            extra=extra,
        )
    else:
        metadata = AuditMetadata.standard(actor=user, target=key, extra=extra)

    await audit_service.log_async(
        tenant_id=user.tenant_id,
        actor_id=None if is_service else user.id,
        actor_type=ActorType.SYSTEM if is_service else ActorType.USER,
        action=ActionType.API_KEY_AUTH_FAILED,
        entity_type=EntityType.API_KEY,
        entity_id=key.id,
        description="Service API key auth failed"
        if is_service
        else "API key authentication failed",
        metadata=metadata,
        outcome=Outcome.FAILURE,
        error_message=exc.message,
    )

    logger.warning(
        "API key authentication failed",
        extra={
            "tenant_id": str(user.tenant_id),
            "user_id": str(user.id),
            "api_key_id": str(key.id),
            "code": exc.code,
            "error_message": exc.message,
        },
    )
