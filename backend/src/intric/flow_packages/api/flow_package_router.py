from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, NoReturn, assert_never, cast
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Path,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.flow_packages.api import flow_package_openapi_examples as openapi_examples
from intric.flow_packages.api.flow_package_models import (
    FlowPackageExportRequest,
    FlowPackageImportPublic,
    FlowPackageImportRequest,
    FlowPackageValidationPublic,
)
from intric.flow_packages.application.flow_package_candidate_loader import (
    build_flow_package_import_planner_candidates_for_space,
)
from intric.flow_packages.application.flow_package_export_service import (
    FlowPackageExportResult,
    FlowPackageExportService,
)
from intric.flow_packages.application.flow_package_import_planner import (
    build_flow_package_import_plan,
)
from intric.flow_packages.application.flow_package_install_service import (
    FlowPackageInstallResult,
    FlowPackageInstallService,
)
from intric.flow_packages.domain.flow_package_envelope import FlowPackageEnvelope
from intric.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageExportError,
    FlowPackageExportErrorCode,
    FlowPackageValidationError,
)
from intric.flow_packages.domain.flow_package_import_plan import FlowPackageImportPlan
from intric.flow_packages.domain.flow_package_import_record import (
    FlowPackageImportFailurePayload,
    FlowPackageImportSelection,
)
from intric.flow_packages.infrastructure.flow_package_import_repo import (
    FlowPackageImportRepository,
)
from intric.flow_packages.infrastructure.flow_package_zip_reader import (
    MAX_PACKAGE_UPLOAD_BYTES,
    read_flow_package,
)
from intric.flow_packages.infrastructure.flow_package_zip_writer import (
    write_flow_package,
)
from intric.flows.api import flow_router_common as common
from intric.flows.api.flow_api_common import error_response
from intric.flows.api.flow_definition_access import require_flow_edit_access
from intric.flows.domain.flow import Flow
from intric.flows.flow_access_policy import FlowApiAction, require_flow_action
from intric.flows.flow_authoring_spec import FlowDraftSpecCore, InputSource, InputType
from intric.flows.flow_resource_bindings import FlowResourceBindingResolutionError
from intric.main.container.container import Container
from intric.main.exceptions import (
    BadRequestException,
    ErrorCodes,
    FileTooLargeException,
    UnauthorizedException,
)
from intric.main.models import GeneralError
from intric.server.dependencies.container import get_container
from intric.server.exception_handlers import extract_request_id
from intric.spaces.space import Space

FLOW_PACKAGE_MEDIA_TYPE = "application/vnd.eneo.flow-package+zip"
MAX_PACKAGE_BASE64_CHARS = ((MAX_PACKAGE_UPLOAD_BYTES + 2) // 3) * 4

tenant_router = APIRouter()
space_router = APIRouter()
flow_router = APIRouter()


@dataclass(frozen=True, slots=True)
class _FlowImportAuditTarget:
    id: UUID
    name: str
    space_id: UUID


PackageUpload = Annotated[
    UploadFile,
    File(
        description=(
            "Portable `.eneo-flowpkg` bundle. The server validates the package "
            "structure, checksum, schema versions, and local-resource portability."
        )
    ),
]


@tenant_router.post(
    "/validate/",
    response_model=FlowPackageValidationPublic,
    status_code=status.HTTP_200_OK,
    operation_id="validate_flow_package",
    summary="Validate Flow Package",
    description=(
        "Upload a portable Flow package and validate its structure, schema versions, "
        "content checksum, and local-resource portability before a target space is "
        "chosen. Use this endpoint for tenant-level package inspection, upload "
        "preflight, or catalog review. Space-specific import wizards can call the "
        "import-plan endpoint directly because that response also contains the "
        "package summary needed by the setup UI."
    ),
    responses={
        400: error_response(
            description=("The uploaded package is not a valid portable Flow package."),
            examples=openapi_examples.PACKAGE_VALIDATION_ERROR_EXAMPLES,
        ),
        403: error_response(
            description=(
                "Caller lacks tenant Flow authoring permission or API-key scope."
            ),
            examples=openapi_examples.FLOW_PACKAGE_VALIDATE_FORBIDDEN_EXAMPLES,
        ),
        413: error_response(
            description="The uploaded package exceeds the package upload size cap.",
            examples=openapi_examples.FLOW_PACKAGE_TOO_LARGE_EXAMPLE,
        ),
    },
)
async def validate_flow_package(
    package_file: PackageUpload,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowPackageValidationPublic:
    require_flow_action(container.user(), FlowApiAction.EDIT)
    envelope = await _read_flow_package(package_file)
    return FlowPackageValidationPublic.from_envelope(envelope)


@space_router.post(
    "/import-plan/",
    response_model=FlowPackageImportPlan,
    status_code=status.HTTP_200_OK,
    operation_id="create_flow_package_import_plan",
    summary="Create Flow Package Import Plan",
    description=(
        "Upload a portable Flow package and preview how its model, knowledge, "
        "and unsupported template requirements resolve against one target space. The "
        "response is a side-effect-free setup checklist: it shows suggested local "
        "resources, unresolved required dependencies, sensitivity guidance, and whether "
        "the imported draft could be published after the mappings are confirmed."
    ),
    responses={
        400: error_response(
            description=("The uploaded package is not a valid portable Flow package."),
            examples=openapi_examples.PACKAGE_VALIDATION_ERROR_EXAMPLES,
        ),
        403: error_response(
            description=(
                "Caller lacks Flow authoring permission, target-space Flow edit "
                "permission, or API-key scope for the target space."
            ),
            examples=openapi_examples.FLOW_PACKAGE_IMPORT_PLAN_FORBIDDEN_EXAMPLES,
        ),
        404: error_response(
            description="Target space was not found in the current tenant.",
            message="Not found",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
        413: error_response(
            description="The uploaded package exceeds the package upload size cap.",
            examples=openapi_examples.FLOW_PACKAGE_TOO_LARGE_EXAMPLE,
        ),
    },
)
async def create_flow_package_import_plan(
    id: Annotated[
        UUID,
        Path(description="Identifier of the target space for dependency planning."),
    ],
    package_file: PackageUpload,
    request: Request,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowPackageImportPlan:
    access_context = await common.get_space_access_context_for_request(
        request,
        container,
        space_id=id,
        required_access=FlowApiAction.EDIT,
        scope_mismatch_message=openapi_examples.IMPORT_PLAN_SCOPE_MISMATCH_MESSAGE,
    )
    if not access_context.actor.can_edit_flows():
        raise UnauthorizedException(
            "You do not have permission to edit flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )

    envelope = await _read_flow_package(package_file)
    candidates = build_flow_package_import_planner_candidates_for_space(
        access_context.space
    )
    return build_flow_package_import_plan(envelope, candidates=candidates)


@space_router.post(
    "/imports/",
    response_model=FlowPackageImportPublic,
    status_code=status.HTTP_201_CREATED,
    operation_id="import_flow_package_as_draft",
    summary="Import Flow Package As Draft",
    description=(
        "Import a portable Flow package into a target space as a new draft Flow. "
        "The request uses typed selected resource bindings so API consumers can map "
        "package model and knowledge slots to local resources without parsing "
        "free-form JSON strings. The endpoint does not publish the Flow, does not "
        "persist package bytes, and records a compact import provenance row for "
        "successful draft creation or trusted-package install failures."
    ),
    responses={
        400: error_response(
            description=(
                "The package payload, selected mappings, or install attempt is invalid."
            ),
            examples=openapi_examples.FLOW_PACKAGE_IMPORT_BAD_REQUEST_EXAMPLES,
        ),
        403: error_response(
            description=(
                "Caller lacks Flow authoring permission, target-space Flow edit "
                "permission, or API-key scope for the target space."
            ),
            examples=openapi_examples.FLOW_PACKAGE_IMPORT_PLAN_FORBIDDEN_EXAMPLES,
        ),
        404: error_response(
            description="Target space was not found in the current tenant.",
            message="Not found",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
        413: error_response(
            description="The decoded package exceeds the package upload size cap.",
            examples=openapi_examples.FLOW_PACKAGE_TOO_LARGE_EXAMPLE,
        ),
    },
)
async def import_flow_package_as_draft(
    id: Annotated[
        UUID,
        Path(description="Identifier of the target space for package import."),
    ],
    import_request: FlowPackageImportRequest,
    request: Request,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> FlowPackageImportPublic | JSONResponse:
    """Return install failures as responses so the failed import record commits."""
    access_context = await common.get_space_access_context_for_request(
        request,
        container,
        space_id=id,
        required_access=FlowApiAction.EDIT,
        scope_mismatch_message=openapi_examples.IMPORT_PLAN_SCOPE_MISMATCH_MESSAGE,
    )
    if not access_context.actor.can_edit_flows():
        raise UnauthorizedException(
            "You do not have permission to edit flows in this space.",
            code="insufficient_space_permission",
            context={"auth_layer": "space_membership"},
        )

    envelope = _read_flow_package_base64(import_request.package_base64)
    candidates = build_flow_package_import_planner_candidates_for_space(
        access_context.space
    )
    import_plan = build_flow_package_import_plan(envelope, candidates=candidates)
    selection = import_request.import_selection()
    session = cast(AsyncSession, container.session())
    import_repo = FlowPackageImportRepository(session)
    default_transcription_model_id = _target_space_default_transcription_model_id(
        access_context.space
    )

    try:
        _require_audio_transcription_model(
            spec=envelope.spec,
            default_transcription_model_id=default_transcription_model_id,
        )
        async with session.begin_nested():
            install_result = await FlowPackageInstallService().install_as_draft(
                envelope=envelope,
                flow_service=container.flow_service(),
                space_id=id,
                selected_bindings=selection.bindings_tuple(),
                candidates=candidates,
                default_transcription_model_id=default_transcription_model_id,
            )
    except (
        BadRequestException,
        FlowPackageValidationError,
        FlowResourceBindingResolutionError,
    ) as exc:
        failure = _flow_package_import_failure_payload(exc)
        await _record_failed_flow_package_import(
            import_repo=import_repo,
            container=container,
            space_id=id,
            envelope=envelope,
            import_plan=import_plan,
            selection=selection,
            failure=failure,
        )
        return _flow_package_import_error_response(failure, request)

    import_id = await _record_successful_flow_package_import(
        import_repo=import_repo,
        container=container,
        space_id=id,
        result=install_result,
        import_plan=import_plan,
        selection=selection,
    )
    await _log_flow_package_import(
        container=container,
        space_id=id,
        result=install_result,
        import_id=import_id,
    )
    return FlowPackageImportPublic(
        import_id=import_id,
        flow_id=install_result.flow_id,
        flow_name=install_result.flow_name,
        package_id=install_result.package_id,
        package_version=install_result.package_version,
        content_checksum=install_result.content_checksum,
        steps_created=install_result.steps_created,
        resource_bindings_count=install_result.resource_bindings_count,
    )


@flow_router.post(
    "/package-exports/",
    response_class=Response,
    status_code=status.HTTP_200_OK,
    operation_id="export_flow_package",
    summary="Export Flow Package",
    description=(
        "Export a draft Flow as a portable `.eneo-flowpkg` bundle. The export "
        "contains a typed flow template and dependency requirements, never local "
        "database IDs, run history, secrets, or source-instance provenance. Use this "
        "endpoint for offline sharing first; future marketplace installs can consume "
        "the same package format. The endpoint requires human draft edit access so "
        "package metadata and dependency guidance are reviewed by the flow owner or "
        "an authorized space/tenant administrator before distribution."
    ),
    responses={
        200: openapi_examples.flow_package_binary_response(FLOW_PACKAGE_MEDIA_TYPE),
        400: error_response(
            description=(
                "The flow cannot be exported as a portable package until the reported "
                "authoring or dependency issue is fixed."
            ),
            examples=openapi_examples.FLOW_PACKAGE_EXPORT_BAD_REQUEST_EXAMPLES,
        ),
        403: error_response(
            description=(
                "Caller lacks Flow edit permission, flow-owner authority, or API-key "
                "scope for this flow."
            ),
            examples=openapi_examples.FLOW_PACKAGE_EXPORT_FORBIDDEN_EXAMPLES,
        ),
        404: error_response(
            description="Flow was not found in the current tenant.",
            message="Not found",
            intric_error_code=ErrorCodes.NOT_FOUND,
            code="not_found",
        ),
        413: error_response(
            description="The exported package exceeds the package export byte cap.",
            examples=openapi_examples.FLOW_PACKAGE_EXPORT_TOO_LARGE_EXAMPLE,
        ),
    },
)
async def export_flow_package(
    id: Annotated[UUID, Path(description="Identifier of the draft Flow to export.")],
    export_request: FlowPackageExportRequest,
    request: Request,
    container: Annotated[Container, Depends(get_container(with_user=True))],
) -> Response:
    access_context = await require_flow_edit_access(
        request,
        container,
        flow_id=id,
        allow_service_key_principals=False,
    )
    export_service = FlowPackageExportService(
        flow_service=container.flow_service(),
        package_writer=write_flow_package,
    )
    try:
        result = await export_service.export_to_bytes(
            flow_id=id,
            flow=access_context.flow,
            manifest_metadata=export_request.to_manifest_metadata(),
        )
    except FlowPackageExportError as exc:
        _raise_export_error(exc)

    await _log_flow_package_export(
        container=container,
        flow_id=id,
        flow=access_context.flow,
        result=result,
    )
    return Response(
        content=result.package_bytes,
        media_type=FLOW_PACKAGE_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{result.filename}"'},
    )


async def _read_flow_package(package_file: UploadFile) -> FlowPackageEnvelope:
    package_bytes = await _read_package_upload_bytes(package_file)
    return _read_flow_package_bytes(package_bytes)


def _read_flow_package_base64(package_base64: str) -> FlowPackageEnvelope:
    normalized = package_base64.strip()
    if len(normalized) > MAX_PACKAGE_BASE64_CHARS:
        raise FileTooLargeException(
            "Flow package upload exceeds the allowed size.",
            code="flow_package_file_too_large",
            context={"max_package_upload_bytes": MAX_PACKAGE_UPLOAD_BYTES},
            file_size=(len(normalized) * 3) // 4,
            max_size=MAX_PACKAGE_UPLOAD_BYTES,
            docs_hint=(
                "Flow package upload limits are fixed by the package reader safety boundary."
            ),
        )
    try:
        package_bytes = base64.b64decode(normalized, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise BadRequestException(
            "Flow package payload is not valid base64.",
            code=FlowPackageErrorCode.BASE64_INVALID.value,
        ) from exc
    if len(package_bytes) > MAX_PACKAGE_UPLOAD_BYTES:
        raise FileTooLargeException(
            "Flow package upload exceeds the allowed size.",
            code="flow_package_file_too_large",
            context={"max_package_upload_bytes": MAX_PACKAGE_UPLOAD_BYTES},
            file_size=len(package_bytes),
            max_size=MAX_PACKAGE_UPLOAD_BYTES,
            docs_hint=(
                "Flow package upload limits are fixed by the package reader safety boundary."
            ),
        )
    return _read_flow_package_bytes(package_bytes)


def _read_flow_package_bytes(package_bytes: bytes) -> FlowPackageEnvelope:
    try:
        return read_flow_package(package_bytes)
    except FlowPackageValidationError as exc:
        raise BadRequestException(
            str(exc),
            code=exc.code.value,
            context=dict(exc.context),
        ) from exc


def _target_space_default_transcription_model_id(space: Space) -> UUID | None:
    model = space.get_default_transcription_model()
    return None if model is None else model.id


def _require_audio_transcription_model(
    *,
    spec: FlowDraftSpecCore,
    default_transcription_model_id: UUID | None,
) -> None:
    if default_transcription_model_id is not None:
        return
    if not _spec_uses_audio_flow_input(spec):
        return
    raise BadRequestException(
        "A transcription model must be selected when using audio input steps.",
        code="transcription_model_required",
    )


def _spec_uses_audio_flow_input(spec: FlowDraftSpecCore) -> bool:
    return any(
        step.input_source == InputSource.FLOW_INPUT
        and step.input_type == InputType.AUDIO
        for step in spec.steps
    )


async def _record_successful_flow_package_import(
    *,
    import_repo: FlowPackageImportRepository,
    container: Container,
    space_id: UUID,
    result: FlowPackageInstallResult,
    import_plan: FlowPackageImportPlan,
    selection: FlowPackageImportSelection,
) -> UUID:
    user = container.user()
    return await import_repo.create_draft_created(
        tenant_id=user.tenant_id,
        space_id=space_id,
        flow_id=result.flow_id,
        created_by_user_id=user.id,
        package_id=result.package_id,
        package_version=result.package_version,
        content_checksum=result.content_checksum,
        import_plan=import_plan,
        selection=selection,
    )


async def _record_failed_flow_package_import(
    *,
    import_repo: FlowPackageImportRepository,
    container: Container,
    space_id: UUID,
    envelope: FlowPackageEnvelope,
    import_plan: FlowPackageImportPlan,
    selection: FlowPackageImportSelection,
    failure: FlowPackageImportFailurePayload,
) -> UUID:
    user = container.user()
    return await import_repo.create_failed(
        tenant_id=user.tenant_id,
        space_id=space_id,
        created_by_user_id=user.id,
        package_id=envelope.manifest.package_id,
        package_version=envelope.manifest.package_version,
        content_checksum=envelope.content_checksum,
        import_plan=import_plan,
        selection=selection,
        failure=failure,
    )


def _flow_package_import_failure_payload(
    exc: (
        BadRequestException
        | FlowPackageValidationError
        | FlowResourceBindingResolutionError
    ),
) -> FlowPackageImportFailurePayload:
    if isinstance(exc, FlowPackageValidationError):
        return FlowPackageImportFailurePayload(
            code=exc.code.value,
            message=str(exc),
            context=_safe_failure_context(exc.context),
        )
    if isinstance(exc, FlowResourceBindingResolutionError):
        return FlowPackageImportFailurePayload(
            code=exc.reason.value,
            message=str(exc),
            context=_safe_failure_context(exc.context()),
        )
    return FlowPackageImportFailurePayload(
        code=exc.code or "bad_request",
        message=str(exc) or "Bad request.",
        context=_safe_failure_context(exc.context),
    )


def _safe_failure_context(context: Mapping[str, object] | None) -> dict[str, str | int]:
    if not context:
        return {}
    safe_context: dict[str, str | int] = {}
    for key, value in context.items():
        # bool before int: Python treats bool as an int subclass, but public error
        # context should render booleans as strings rather than 1 or 0.
        if isinstance(value, bool):
            safe_context[key] = str(value).lower()
        elif isinstance(value, (str, int)):
            safe_context[key] = value
        else:
            safe_context[key] = str(value)
    return safe_context


def _flow_package_import_error_response(
    failure: FlowPackageImportFailurePayload,
    request: Request,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=GeneralError(
            message=failure.message,
            intric_error_code=ErrorCodes.BAD_REQUEST,
            code=failure.code,
            context=dict(failure.context) or None,
            request_id=extract_request_id(request),
        ).model_dump(mode="json", exclude_none=True),
    )


async def _read_package_upload_bytes(package_file: UploadFile) -> bytes:
    package_bytes = await package_file.read(MAX_PACKAGE_UPLOAD_BYTES + 1)
    if len(package_bytes) <= MAX_PACKAGE_UPLOAD_BYTES:
        return package_bytes
    raise FileTooLargeException(
        "Flow package upload exceeds the allowed size.",
        code="flow_package_file_too_large",
        context={"max_package_upload_bytes": MAX_PACKAGE_UPLOAD_BYTES},
        file_size=len(package_bytes),
        max_size=MAX_PACKAGE_UPLOAD_BYTES,
        docs_hint=(
            "Flow package upload limits are fixed by the package reader safety boundary."
        ),
    )


def _raise_export_error(exc: FlowPackageExportError) -> NoReturn:
    match exc.code:
        case (
            FlowPackageExportErrorCode.MISSING_ASSISTANT_SNAPSHOT
            | FlowPackageExportErrorCode.UNSUPPORTED_STEP_IO
            | FlowPackageExportErrorCode.UNMAPPED_RESOURCE_REF
            | FlowPackageExportErrorCode.DUPLICATE_RESOURCE_BINDING
            | FlowPackageExportErrorCode.MCP_EXPORT_UNSUPPORTED
            | FlowPackageExportErrorCode.TEMPLATE_ASSET_PAYLOAD_UNSUPPORTED
            | FlowPackageExportErrorCode.VARIABLE_REFERENCE_INVALID
            | FlowPackageExportErrorCode.JSON_PAYLOAD_TOO_DEEP
            | FlowPackageExportErrorCode.FORM_SCHEMA_INVALID
        ):
            raise _bad_export_request(exc) from exc
        case FlowPackageExportErrorCode.PACKAGE_BYTES_TOO_LARGE:
            raise FileTooLargeException(
                str(exc),
                code=exc.code.value,
                context=dict(exc.context),
                file_size=_int_context(exc, "package_size_bytes"),
                max_size=_int_context(exc, "max_package_export_bytes"),
                docs_hint=(
                    "Flow package export limits are fixed by the package writer "
                    "safety boundary."
                ),
            ) from exc
        case _:
            assert_never(exc.code)


def _bad_export_request(exc: FlowPackageExportError) -> BadRequestException:
    return BadRequestException(
        str(exc),
        code=exc.code.value,
        context=dict(exc.context),
    )


def _int_context(exc: FlowPackageExportError, key: str) -> int | None:
    value = exc.context.get(key)
    if isinstance(value, int):
        return value
    return None


async def _log_flow_package_export(
    *,
    container: Container,
    flow_id: UUID,
    flow: Flow,
    result: FlowPackageExportResult,
) -> None:
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_PACKAGE_EXPORTED,
        entity_type=EntityType.FLOW,
        entity_id=flow_id,
        description=(f"Exported Flow package '{result.envelope.manifest.package_id}'"),
        metadata=AuditMetadata.standard(
            actor=user,
            target=flow,
            extra={
                "package_id": result.envelope.manifest.package_id,
                "package_version": result.envelope.manifest.package_version,
                "content_checksum": result.envelope.content_checksum,
                "requirements_count": len(result.envelope.requirements.requirements),
                "payload_size_bytes": len(result.package_bytes),
            },
        ),
    )


async def _log_flow_package_import(
    *,
    container: Container,
    space_id: UUID,
    result: FlowPackageInstallResult,
    import_id: UUID,
) -> None:
    user = container.user()
    await container.audit_service().log_async(
        tenant_id=user.tenant_id,
        actor_id=user.id,
        action=ActionType.FLOW_PACKAGE_DRAFT_INSTALLED,
        entity_type=EntityType.FLOW,
        entity_id=result.flow_id,
        description=f"Imported Flow package '{result.package_id}' as draft",
        metadata=AuditMetadata.standard(
            actor=user,
            target=_FlowImportAuditTarget(
                id=result.flow_id,
                name=result.flow_name,
                space_id=space_id,
            ),
            extra={
                "import_id": str(import_id),
                "space_id": str(space_id),
                "package_id": result.package_id,
                "package_version": result.package_version,
                "content_checksum": result.content_checksum,
                "steps_created": result.steps_created,
                "resource_bindings_count": result.resource_bindings_count,
            },
        ),
    )
