from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.auth_dependencies import get_scope_filter
from intric.flows.api.flow_assembler import FlowAssembler
from intric.flows.api.flow_models import (
    FlowRunEvidenceResponse,
    FlowRunPublic,
    FlowRunRedispatchResponse,
)
from intric.main.container.container import Container
from intric.main.models import PaginatedResponse
from intric.server.dependencies.container import get_container

router = APIRouter()


def _raise_scope_mismatch() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "insufficient_scope",
            "message": "API key space scope does not match requested flow.",
            "context": {"auth_layer": "api_key_scope"},
        },
    )


async def _enforce_flow_scope(request: Request, container: Container, *, flow_id: UUID) -> None:
    scope_filter = get_scope_filter(request)
    if scope_filter.space_id is None:
        return

    flow = await container.flow_service().get_flow(flow_id)
    if scope_filter.space_id != flow.space_id:
        _raise_scope_mismatch()


@router.get("/", response_model=PaginatedResponse[FlowRunPublic], status_code=status.HTTP_200_OK)
async def list_flow_runs(
    request: Request,
    flow_id: UUID = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    container: Container = Depends(get_container(with_user=True)),
):
    # Preserve existing behavior: unknown flow_id should return 404 even when API key
    # scope filter is not active.
    flow = await container.flow_service().get_flow(flow_id)
    scope_filter = get_scope_filter(request)
    if scope_filter.space_id is not None and scope_filter.space_id != flow.space_id:
        _raise_scope_mismatch()

    flow_run_service = container.flow_run_service()
    runs = await flow_run_service.list_runs(
        flow_id=flow_id,
        limit=limit,
        offset=offset,
    )
    assembler = FlowAssembler()
    return {
        "count": len(runs),
        "items": [assembler.to_run_public(item) for item in runs],
    }


@router.get("/{id}/", response_model=FlowRunPublic, status_code=status.HTTP_200_OK)
async def get_flow_run(
    id: UUID,
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    flow_run_service = container.flow_run_service()
    run = await flow_run_service.get_run(run_id=id)
    await _enforce_flow_scope(request, container, flow_id=run.flow_id)
    return FlowAssembler().to_run_public(run)


@router.post("/{id}/cancel/", response_model=FlowRunPublic, status_code=status.HTTP_200_OK)
async def cancel_flow_run(
    id: UUID,
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    user = container.user()
    run_service = container.flow_run_service()
    run_before_cancel = await run_service.get_run(run_id=id)
    await _enforce_flow_scope(request, container, flow_id=run_before_cancel.flow_id)
    run = await run_service.cancel_run(run_id=id)

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_RUN_CANCELLED,
        entity_type=EntityType.FLOW_RUN,
        entity_id=run.id,
        description=f"Cancelled flow run {run.id}",
        metadata=AuditMetadata.standard(actor=user, target=run),
    )
    return FlowAssembler().to_run_public(run)


@router.post("/{id}/redispatch/", response_model=FlowRunRedispatchResponse, status_code=status.HTTP_200_OK)
async def redispatch_flow_run(
    id: UUID,
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    user = container.user()
    run_service = container.flow_run_service()
    run = await run_service.get_run(run_id=id)
    await _enforce_flow_scope(request, container, flow_id=run.flow_id)

    redispatched = await run_service.redispatch_stale_queued_runs(
        flow_id=run.flow_id,
        run_id=run.id,
        limit=1,
        execution_backend=container.flow_execution_backend(),
    )
    refreshed = await run_service.get_run(run_id=id)

    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_RUN_REDISPATCHED,
        entity_type=EntityType.FLOW_RUN,
        entity_id=refreshed.id,
        description=f"Redispatch requested for flow run {refreshed.id} (dispatch_count={redispatched})",
        metadata=AuditMetadata.standard(actor=user, target=refreshed),
    )
    return {
        "run": FlowAssembler().to_run_public(refreshed),
        "redispatched_count": redispatched,
    }


@router.get("/{id}/evidence/", response_model=FlowRunEvidenceResponse, status_code=status.HTTP_200_OK)
async def get_flow_run_evidence(
    id: UUID,
    request: Request,
    container: Container = Depends(get_container(with_user=True)),
):
    run_service = container.flow_run_service()
    run = await run_service.get_run(run_id=id)
    await _enforce_flow_scope(request, container, flow_id=run.flow_id)
    evidence = await run_service.get_evidence(run_id=id)
    return FlowRunEvidenceResponse(**evidence)
