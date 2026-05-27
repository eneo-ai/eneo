from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeAlias, assert_never
from uuid import UUID

from intric.authentication.principal_types import PrincipalType
from intric.flows.principal import FlowPrincipal

FlowRunDispatchKwargs: TypeAlias = dict[str, str | None]


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
) -> FlowRunDispatchKwargs:
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
