from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

from eneo.flows.api.flow_api_common import error_response
from eneo.flows.application.flow_run_audit_outbox_delivery import (
    FlowRunAuditOutboxGenerationConflictError,
    FlowRunAuditOutboxNotFoundError,
    FlowRunAuditOutboxStateConflictError,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.container.container import Container
from eneo.main.exceptions import ConflictException, ErrorCodes, NotFoundException
from eneo.main.models import OffsetPaginatedResponse
from eneo.server.dependencies.container import (
    get_container,
    get_container_for_explicit_transaction,
)

router = APIRouter()
__all__ = ["router"]


class FlowRunAuditOutboxDeadLetterResponse(BaseModel):
    outbox_id: UUID = Field(description="Audit outbox row identifier used for redrive.")
    tenant_id: UUID = Field(description="Tenant that owns the lifecycle audit row.")
    flow_id: UUID = Field(description="Flow whose run emitted the lifecycle audit.")
    flow_run_id: UUID = Field(description="Flow run whose lifecycle audit is pending.")
    action: str = Field(description="Lifecycle audit action awaiting delivery.")
    source: str = Field(description="Runtime source that emitted the lifecycle audit.")
    delivery_attempts: int = Field(
        ge=0,
        description="Delivery attempts charged in this dead-letter generation.",
    )
    dead_lettered_at: AwareDatetime = Field(
        description="Generation token required by the redrive operation."
    )
    delivery_last_error: str | None = Field(
        description="Bounded, secret-redacted diagnostic from the final attempt."
    )
    created_at: AwareDatetime = Field(
        description="Time the durable lifecycle audit outbox row was created."
    )


class FlowRunAuditOutboxRedriveRequest(BaseModel):
    expected_dead_lettered_at: AwareDatetime = Field(
        description="Exact dead_lettered_at generation token returned by the list."
    )
    reason: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
        Field(description="Operator diagnosis recorded in the mandatory audit row."),
    ]


class FlowRunAuditOutboxRedriveResponse(BaseModel):
    outbox_id: UUID = Field(description="Redriven audit outbox row identifier.")
    flow_run_id: UUID = Field(description="Flow run whose audit row was redriven.")
    delivery_status: Literal["pending"] = Field(
        description="Post-redrive state consumed by the normal delivery worker."
    )
    delivery_attempts: Literal[0] = Field(
        description="Fresh delivery-attempt budget starts at zero."
    )
    next_delivery_at: AwareDatetime = Field(
        description="Time from which the normal delivery worker may claim the row."
    )
    operator_audit_id: UUID = Field(
        description="Tenant-scoped mandatory audit record for this redrive."
    )


@router.get(
    "/flows/audit-outbox/dead-letters/",
    response_model=OffsetPaginatedResponse[FlowRunAuditOutboxDeadLetterResponse],
    status_code=status.HTTP_200_OK,
    operation_id="list_flow_run_audit_outbox_dead_letters",
    summary="List dead-lettered Flow audit deliveries",
    description=(
        "Requires the configured super API key. List a bounded, oldest-first window "
        "of dead-lettered Flow lifecycle audit deliveries. Use each row's "
        "dead_lettered_at as the generation token for redrive."
    ),
    responses={
        401: error_response(
            description="The configured super API key is required.",
            message="Authentication required.",
            eneo_error_code=ErrorCodes.AUTHENTICATION_ERROR,
            code="authentication_error",
        )
    },
)
async def list_flow_run_audit_outbox_dead_letters(
    container: Annotated[Container, Depends(get_container())],
    limit: Annotated[
        int,
        Query(ge=1, le=200, description="Maximum number of rows to return."),
    ] = 50,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of dead-lettered rows to skip."),
    ] = 0,
) -> OffsetPaginatedResponse[FlowRunAuditOutboxDeadLetterResponse]:
    page = await container.flow_run_audit_outbox_delivery_service().list_dead_letters(
        limit=limit,
        offset=offset,
    )
    return OffsetPaginatedResponse(
        items=[
            FlowRunAuditOutboxDeadLetterResponse(
                outbox_id=row.outbox_id,
                tenant_id=row.tenant_id,
                flow_id=row.flow_id,
                flow_run_id=row.flow_run_id,
                action=row.action,
                source=row.source,
                delivery_attempts=row.delivery_attempts,
                dead_lettered_at=row.dead_lettered_at,
                delivery_last_error=row.delivery_last_error,
                created_at=row.created_at,
            )
            for row in page.items
        ],
        has_more=page.has_more,
    )


@router.post(
    "/flows/audit-outbox/{outbox_id}/redrive/",
    response_model=FlowRunAuditOutboxRedriveResponse,
    status_code=status.HTTP_200_OK,
    operation_id="redrive_flow_run_audit_outbox_delivery",
    summary="Redrive dead-lettered Flow audit delivery",
    description=(
        "Requires the configured super API key. Atomically reset one listed "
        "dead-letter generation to pending with a fresh five-attempt budget and "
        "record the required tenant audit. A stale generation token is rejected; "
        "the normal delivery worker performs delivery. Poll Flow runtime health and "
        "list dead letters again to verify recovery."
    ),
    responses={
        401: error_response(
            description="The configured super API key is required.",
            message="Authentication required.",
            eneo_error_code=ErrorCodes.AUTHENTICATION_ERROR,
            code="authentication_error",
        ),
        404: error_response(
            description="The requested audit outbox row does not exist.",
            message="Audit outbox row not found.",
            eneo_error_code=ErrorCodes.NOT_FOUND,
            code=FlowApiErrorCode.AUDIT_OUTBOX_DELIVERY_NOT_FOUND,
        ),
        409: error_response(
            description=(
                "The row is not dead-lettered or its dead-letter generation token is stale."
            ),
            message="Audit outbox row is not eligible for redrive.",
            eneo_error_code=ErrorCodes.CONFLICT,
            code=FlowApiErrorCode.AUDIT_OUTBOX_REDRIVE_CONFLICT,
        ),
    },
)
async def redrive_flow_run_audit_outbox_delivery(
    outbox_id: UUID,
    request: FlowRunAuditOutboxRedriveRequest,
    container: Annotated[
        Container,
        Depends(get_container_for_explicit_transaction()),
    ],
) -> FlowRunAuditOutboxRedriveResponse:
    service = container.flow_run_audit_outbox_delivery_service()
    try:
        result = await service.redrive_dead_lettered(
            outbox_id=outbox_id,
            expected_dead_lettered_at=request.expected_dead_lettered_at,
            reason=request.reason,
            now=datetime.now(timezone.utc),
        )
    except FlowRunAuditOutboxNotFoundError as exc:
        raise NotFoundException(
            "Audit outbox row not found.",
            code=FlowApiErrorCode.AUDIT_OUTBOX_DELIVERY_NOT_FOUND.value,
            context={"outbox_id": str(outbox_id)},
        ) from exc
    except (
        FlowRunAuditOutboxStateConflictError,
        FlowRunAuditOutboxGenerationConflictError,
    ) as exc:
        raise ConflictException(
            "Audit outbox row is not eligible for redrive.",
            code=FlowApiErrorCode.AUDIT_OUTBOX_REDRIVE_CONFLICT.value,
            context={"outbox_id": str(outbox_id)},
        ) from exc

    return FlowRunAuditOutboxRedriveResponse(
        outbox_id=result.outbox_id,
        flow_run_id=result.flow_run_id,
        delivery_status=result.delivery_status,
        delivery_attempts=result.delivery_attempts,
        next_delivery_at=result.next_delivery_at,
        operator_audit_id=result.operator_audit_id,
    )
