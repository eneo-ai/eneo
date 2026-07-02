from __future__ import annotations

from typing import Any, TypedDict
from uuid import UUID

from eneo.audit.domain.actor_types import ActorType
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.principal import FlowPrincipal
from eneo.main.exceptions import ErrorCodes
from eneo.main.models import GeneralError


class AuditActorKwargs(TypedDict):
    actor_id: UUID | None
    actor_type: ActorType
    actor_api_key_id: UUID | None


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
