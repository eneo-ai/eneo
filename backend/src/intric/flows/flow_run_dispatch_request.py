from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, TypeAlias, TypedDict, assert_never
from uuid import UUID

from intric.authentication.principal_types import PrincipalType
from intric.flows.principal import FlowPrincipal


class FlowRunDispatchSource(Protocol):
    id: UUID
    flow_id: UUID
    tenant_id: UUID


@dataclass(frozen=True)
class FlowRunUserDispatchRequest:
    run_id: UUID
    flow_id: UUID
    tenant_id: UUID
    principal_user_id: UUID


@dataclass(frozen=True)
class FlowRunServiceKeyDispatchRequest:
    run_id: UUID
    flow_id: UUID
    tenant_id: UUID
    principal_service_id: UUID
    principal_user_id: UUID | None = None


FlowRunDispatchRequest: TypeAlias = (
    FlowRunUserDispatchRequest | FlowRunServiceKeyDispatchRequest
)


class FlowRunDispatchTaskKwargs(TypedDict):
    run_id: str
    flow_id: str
    tenant_id: str
    principal_type: Literal["user", "service_key"]
    principal_user_id: str | None
    principal_service_id: str | None


class FlowRunDispatchMalformedReason(StrEnum):
    INVALID_RUN_ID = "invalid_run_id"
    INVALID_FLOW_ID = "invalid_flow_id"
    INVALID_TENANT_ID = "invalid_tenant_id"
    INVALID_PRINCIPAL_TYPE = "invalid_principal_type"
    INVALID_PRINCIPAL_USER_ID = "invalid_principal_user_id"
    INVALID_PRINCIPAL_SERVICE_ID = "invalid_principal_service_id"


@dataclass(frozen=True)
class FlowRunDispatchMissingPrincipal:
    run_id: UUID
    tenant_id: UUID


@dataclass(frozen=True)
class FlowRunDispatchMalformedPayload:
    reason: FlowRunDispatchMalformedReason


FlowRunDispatchParseResult: TypeAlias = (
    FlowRunDispatchRequest
    | FlowRunDispatchMissingPrincipal
    | FlowRunDispatchMalformedPayload
)


def build_flow_run_dispatch_request(
    run: FlowRunDispatchSource,
) -> FlowRunDispatchRequest:
    principal = FlowPrincipal.from_run(run)
    if principal.principal_type == PrincipalType.USER:
        if principal.principal_user_id is None:
            raise ValueError("principal_user_id required for user dispatch")
        return FlowRunUserDispatchRequest(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            principal_user_id=principal.principal_user_id,
        )
    if principal.principal_type == PrincipalType.SERVICE_KEY:
        if principal.principal_service_id is None:
            raise ValueError("principal_service_id required for service-key dispatch")
        return FlowRunServiceKeyDispatchRequest(
            run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            principal_user_id=principal.principal_user_id,
            principal_service_id=principal.principal_service_id,
        )
    assert_never(principal.principal_type)


def flow_run_dispatch_task_kwargs(
    request: FlowRunDispatchRequest,
) -> FlowRunDispatchTaskKwargs:
    match request:
        case FlowRunUserDispatchRequest():
            return {
                "run_id": str(request.run_id),
                "flow_id": str(request.flow_id),
                "tenant_id": str(request.tenant_id),
                "principal_type": PrincipalType.USER.value,
                "principal_user_id": str(request.principal_user_id),
                "principal_service_id": None,
            }
        case FlowRunServiceKeyDispatchRequest():
            return {
                "run_id": str(request.run_id),
                "flow_id": str(request.flow_id),
                "tenant_id": str(request.tenant_id),
                "principal_type": PrincipalType.SERVICE_KEY.value,
                "principal_user_id": (
                    str(request.principal_user_id)
                    if request.principal_user_id is not None
                    else None
                ),
                "principal_service_id": str(request.principal_service_id),
            }
        case _:
            assert_never(request)


def parse_flow_run_dispatch_task_kwargs(
    *,
    run_id: str,
    flow_id: str,
    tenant_id: str,
    principal_type: str | None = None,
    principal_user_id: str | None = None,
    principal_service_id: str | None = None,
) -> FlowRunDispatchParseResult:
    parsed_run_id = _parse_dispatch_uuid(run_id)
    if parsed_run_id is None:
        return FlowRunDispatchMalformedPayload(
            reason=FlowRunDispatchMalformedReason.INVALID_RUN_ID
        )

    parsed_tenant_id = _parse_dispatch_uuid(tenant_id)
    if parsed_tenant_id is None:
        return FlowRunDispatchMalformedPayload(
            reason=FlowRunDispatchMalformedReason.INVALID_TENANT_ID
        )

    parsed_flow_id = _parse_dispatch_uuid(flow_id)
    if parsed_flow_id is None:
        return FlowRunDispatchMalformedPayload(
            reason=FlowRunDispatchMalformedReason.INVALID_FLOW_ID
        )

    if principal_type is None:
        return FlowRunDispatchMissingPrincipal(
            run_id=parsed_run_id,
            tenant_id=parsed_tenant_id,
        )

    try:
        parsed_principal_type = PrincipalType(principal_type)
    except ValueError:
        return FlowRunDispatchMalformedPayload(
            reason=FlowRunDispatchMalformedReason.INVALID_PRINCIPAL_TYPE
        )

    if parsed_principal_type == PrincipalType.USER:
        if principal_user_id is None:
            return FlowRunDispatchMissingPrincipal(
                run_id=parsed_run_id,
                tenant_id=parsed_tenant_id,
            )
        parsed_user_id = _parse_dispatch_uuid(principal_user_id)
        if parsed_user_id is None:
            return FlowRunDispatchMalformedPayload(
                reason=FlowRunDispatchMalformedReason.INVALID_PRINCIPAL_USER_ID
            )
        return FlowRunUserDispatchRequest(
            run_id=parsed_run_id,
            flow_id=parsed_flow_id,
            tenant_id=parsed_tenant_id,
            principal_user_id=parsed_user_id,
        )

    if parsed_principal_type == PrincipalType.SERVICE_KEY:
        if principal_service_id is None:
            return FlowRunDispatchMissingPrincipal(
                run_id=parsed_run_id,
                tenant_id=parsed_tenant_id,
            )
        parsed_service_id = _parse_dispatch_uuid(principal_service_id)
        if parsed_service_id is None:
            return FlowRunDispatchMalformedPayload(
                reason=FlowRunDispatchMalformedReason.INVALID_PRINCIPAL_SERVICE_ID
            )
        parsed_user_id: UUID | None = None
        if principal_user_id is not None:
            parsed_user_id = _parse_dispatch_uuid(principal_user_id)
            if parsed_user_id is None:
                return FlowRunDispatchMalformedPayload(
                    reason=FlowRunDispatchMalformedReason.INVALID_PRINCIPAL_USER_ID
                )
        return FlowRunServiceKeyDispatchRequest(
            run_id=parsed_run_id,
            flow_id=parsed_flow_id,
            tenant_id=parsed_tenant_id,
            principal_user_id=parsed_user_id,
            principal_service_id=parsed_service_id,
        )

    assert_never(parsed_principal_type)


def _parse_dispatch_uuid(
    value: str,
) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None
