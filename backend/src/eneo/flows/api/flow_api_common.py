from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, TypedDict, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.audit.domain.actor_types import ActorType
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.principal import FlowPrincipal
from eneo.main.container.container import Container
from eneo.main.exceptions import ErrorCodes
from eneo.main.models import GeneralError


class AuditActorKwargs(TypedDict):
    actor_id: UUID | None
    actor_type: ActorType
    actor_api_key_id: UUID | None


FLOW_RUN_FORBIDDEN_DESCRIPTION = (
    "Forbidden. Caller scope, tenant or space permission, and run visibility are "
    "evaluated before returning Flow runtime data. Machine-readable codes include "
    "`insufficient_scope`, `flow_run_access_denied`, and "
    "`flow_service_key_principal_not_supported`."
)

FLOW_RUN_SERVICE_KEY_REVIEW_CLAUSE = (
    "Service-key human-review clients should use a service-owned `sk_` key with "
    "`resource_permissions.flows = write`; inspect `steps_requiring_review`, "
    "then expect review checkpoints to pause at `awaiting_review` rather than "
    "auto-approve, and use the same key to mutate only checkpoints for runs it "
    "created."
)

FLOW_RUN_COMMIT_BEFORE_RESPONSE_CLAUSE = (
    "Successful runtime mutations are committed before the response is returned, "
    "so clients can immediately use the returned id or revision in the next "
    "poll/edit/approve/resume request."
)


@asynccontextmanager
async def commit_flow_runtime_write_before_response(
    container: Container,
) -> AsyncGenerator[None, None]:
    session = cast(AsyncSession, container.session())
    async with session.begin():
        yield


def error_response(
    *,
    description: str,
    message: str | None = None,
    eneo_error_code: ErrorCodes | None = None,
    code: FlowApiErrorCode | str | None = None,
    context: dict[str, object] | None = None,
    examples: dict[str, dict[str, object]] | None = None,
) -> dict[str, Any]:
    if examples is not None:
        if (
            message is not None
            or eneo_error_code is not None
            or code is not None
            or context is not None
        ):
            raise ValueError("examples mode must not pass single error example fields")
        return {
            "model": GeneralError,
            "description": description,
            "content": {"application/json": {"examples": examples}},
        }
    if message is None or eneo_error_code is None:
        raise ValueError(
            "message and eneo_error_code are required for single error examples"
        )
    example: dict[str, Any] = {
        "message": message,
        "eneo_error_code": int(eneo_error_code),
    }
    if code is not None:
        example["code"] = code.value if isinstance(code, FlowApiErrorCode) else code
    if context is not None:
        example["context"] = context
    return {
        "model": GeneralError,
        "description": description,
        "content": {"application/json": {"example": example}},
    }


def audit_actor_kwargs(user: Any) -> AuditActorKwargs:
    fields = FlowPrincipal.from_user(user).audit_actor_fields()
    return {
        "actor_id": fields["actor_id"],
        "actor_type": fields["actor_type"],
        "actor_api_key_id": fields["actor_api_key_id"],
    }
