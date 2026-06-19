from __future__ import annotations

import base64
import json
import zipfile
from collections.abc import Mapping
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException, Request, UploadFile
from pydantic import ValidationError

from intric.actors.actors.space_actor import SpaceActor
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.authentication.auth_dependencies import ScopeFilter
from intric.flow_packages.api import flow_package_router
from intric.flow_packages.api.flow_package_models import (
    FlowPackageExportRequest,
    FlowPackageImportRequest,
    FlowPackageValidationPublic,
)
from intric.flow_packages.application.flow_package_export_service import (
    FlowPackageExportResult,
)
from intric.flow_packages.application.flow_package_import_planner import (
    FlowPackageImportPlannerCandidates,
)
from intric.flow_packages.application.flow_package_install_service import (
    FlowPackageInstallResult,
)
from intric.flow_packages.domain.flow_package_checksum import (
    compose_content_checksum,
    hash_json_value,
)
from intric.flow_packages.domain.flow_package_draft import FlowPackageFlowDraft
from intric.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageExportError,
    FlowPackageExportErrorCode,
    FlowPackageValidationError,
    FlowPackageZipUnsafeReason,
)
from intric.flow_packages.domain.flow_package_import_plan import (
    FlowPackageImportPlanStatus,
    FlowPackageModelCandidate,
    FlowPackageModelDependencyResolution,
)
from intric.flow_packages.domain.flow_package_import_record import (
    FlowPackageImportFailurePayload,
    FlowPackageImportSelection,
)
from intric.flow_packages.domain.flow_package_manifest import (
    FlowPackageManifest,
)
from intric.flow_packages.domain.flow_package_provenance import FlowPackageProvenance
from intric.flow_packages.domain.flow_package_requirements import (
    FlowPackageModelIdentity,
    FlowPackageModelKind,
    FlowPackageModelMatchingPreferences,
    FlowPackageModelRequirement,
    FlowPackageRequirementKind,
    FlowPackageRequirementSet,
)
from intric.flow_packages.infrastructure import flow_package_zip_reader as reader
from intric.flows.api.flow_access_context import (
    FlowAccessContext,
    FlowSpaceAccessContext,
)
from intric.flows.domain.flow import Flow
from intric.flows.flow_access_policy import FlowApiAction
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from intric.json_types import JsonObject
from intric.main.container.container import Container
from intric.main.exceptions import (
    BadRequestException,
    FileTooLargeException,
    UnauthorizedException,
)
from intric.spaces.space import Space


@pytest.mark.anyio
async def test_validate_flow_package_returns_tenant_scoped_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_actions: list[FlowApiAction] = []

    def fake_require_flow_action(
        user: object,
        action: FlowApiAction,
        *,
        allow_service_key_principals: bool = False,
    ) -> None:
        captured_actions.append(action)

    monkeypatch.setattr(
        flow_package_router,
        "require_flow_action",
        fake_require_flow_action,
    )

    summary = await flow_package_router.validate_flow_package(
        package_file=_upload(_package_bytes()),
        container=cast(Container, _FakeContainer()),
    )

    assert captured_actions == [FlowApiAction.EDIT]
    assert summary.package_id == "se.demo.flow"
    assert summary.package_version == "1.0.0"
    assert summary.name == "Demo Flow"
    assert summary.steps_count == 1
    assert summary.requirements_count == 1
    assert summary.requirements_by_kind == {FlowPackageRequirementKind.MODEL: 1}


@pytest.mark.anyio
async def test_validate_flow_package_checks_permission_before_reading_upload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_require_flow_action(
        user: object,
        action: FlowApiAction,
        *,
        allow_service_key_principals: bool = False,
    ) -> None:
        raise UnauthorizedException(
            "You do not have permission to manage flows.",
            code="insufficient_tenant_permission",
        )

    def fail_read_flow_package(package_bytes: bytes) -> object:
        raise AssertionError(
            "validate should not parse package bytes without permission"
        )

    monkeypatch.setattr(
        flow_package_router,
        "require_flow_action",
        fake_require_flow_action,
    )
    monkeypatch.setattr(
        flow_package_router,
        "read_flow_package",
        fail_read_flow_package,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await flow_package_router.validate_flow_package(
            package_file=_upload(b"not a package"),
            container=cast(Container, _FakeContainer()),
        )

    assert exc_info.value.code == "insufficient_tenant_permission"


@pytest.mark.anyio
async def test_read_flow_package_upload_rejects_oversized_body_before_zip_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_read_flow_package(package_bytes: bytes) -> object:
        raise AssertionError("oversized package should be rejected before zip parsing")

    monkeypatch.setattr(
        flow_package_router,
        "read_flow_package",
        fail_read_flow_package,
    )

    with pytest.raises(FileTooLargeException) as exc_info:
        await flow_package_router._read_flow_package(
            _upload(b"x" * (reader.MAX_PACKAGE_UPLOAD_BYTES + 1))
        )

    assert exc_info.value.code == "flow_package_file_too_large"
    assert exc_info.value.max_size == reader.MAX_PACKAGE_UPLOAD_BYTES
    assert exc_info.value.context == {
        "max_package_upload_bytes": reader.MAX_PACKAGE_UPLOAD_BYTES
    }


@pytest.mark.anyio
async def test_read_flow_package_translates_validation_errors() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        await flow_package_router._read_flow_package(_upload(b"not a zip"))

    assert exc_info.value.code == FlowPackageErrorCode.ZIP_UNSAFE.value
    assert exc_info.value.context == {
        "reason": FlowPackageZipUnsafeReason.BAD_ZIP.value
    }


@pytest.mark.anyio
async def test_create_flow_package_import_plan_returns_typed_resolutions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_space_id: list[UUID] = []
    target_space_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    candidate = FlowPackageModelCandidate(
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=UUID("11111111-1111-4111-8111-111111111111"),
        label="Structured Mini",
        model_kind=FlowPackageModelKind.COMPLETION_MODEL,
        identity=FlowPackageModelIdentity(provider="openai", model="gpt-5.4-mini"),
    )

    async def fake_resolve_space_access_context(
        request: Request,
        container: Container,
        *,
        space_id: UUID,
        required_access: FlowApiAction = FlowApiAction.VIEW,
        scope_mismatch_message: str = "",
        allow_service_key_principals: bool = False,
    ) -> FlowSpaceAccessContext:
        captured_space_id.append(space_id)
        assert required_access is FlowApiAction.EDIT
        assert (
            scope_mismatch_message
            == "API key space scope does not match target package import space."
        )
        return FlowSpaceAccessContext(
            space=cast(Space, object()),
            actor=cast(SpaceActor, _FakeSpaceActor(can_edit=True)),
            scope_filter=ScopeFilter(),
        )

    def fake_candidate_loader(space: Space) -> FlowPackageImportPlannerCandidates:
        return FlowPackageImportPlannerCandidates(models=[candidate])

    monkeypatch.setattr(
        flow_package_router.flow_access_context,
        "resolve_space_access_context",
        fake_resolve_space_access_context,
    )
    monkeypatch.setattr(
        flow_package_router,
        "build_flow_package_import_planner_candidates_for_space",
        fake_candidate_loader,
    )

    plan = await flow_package_router.create_flow_package_import_plan(
        id=target_space_id,
        package_file=_upload(_package_bytes()),
        request=cast(Request, object()),
        container=cast(Container, _FakeContainer()),
    )

    assert captured_space_id == [target_space_id]
    assert plan.can_publish_after_import is True
    resolution = plan.dependency_resolutions[0]
    assert isinstance(resolution, FlowPackageModelDependencyResolution)
    assert resolution.status is FlowPackageImportPlanStatus.RESOLVED_EXACT
    assert resolution.suggestions == [candidate]


@pytest.mark.anyio
async def test_create_flow_package_import_plan_rejects_space_without_flow_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve_space_access_context(
        request: Request,
        container: Container,
        *,
        space_id: UUID,
        required_access: FlowApiAction = FlowApiAction.VIEW,
        scope_mismatch_message: str = "",
        allow_service_key_principals: bool = False,
    ) -> FlowSpaceAccessContext:
        return FlowSpaceAccessContext(
            space=cast(Space, object()),
            actor=cast(SpaceActor, _FakeSpaceActor(can_edit=False)),
            scope_filter=ScopeFilter(),
        )

    def fail_read_flow_package(package_bytes: bytes) -> object:
        raise AssertionError(
            "import-plan should not parse package bytes without space edit"
        )

    monkeypatch.setattr(
        flow_package_router.flow_access_context,
        "resolve_space_access_context",
        fake_resolve_space_access_context,
    )
    monkeypatch.setattr(
        flow_package_router,
        "read_flow_package",
        fail_read_flow_package,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await flow_package_router.create_flow_package_import_plan(
            id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            package_file=_upload(b"not a package"),
            request=cast(Request, object()),
            container=cast(Container, _FakeContainer()),
        )

    assert exc_info.value.code == "insufficient_space_permission"
    assert exc_info.value.context == {"auth_layer": "space_membership"}


@pytest.mark.anyio
async def test_create_flow_package_import_plan_bubbles_scope_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve_space_access_context(
        request: Request,
        container: Container,
        *,
        space_id: UUID,
        required_access: FlowApiAction = FlowApiAction.VIEW,
        scope_mismatch_message: str = "",
        allow_service_key_principals: bool = False,
    ) -> FlowSpaceAccessContext:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "insufficient_scope",
                "message": scope_mismatch_message,
                "context": {"auth_layer": "api_key_scope"},
            },
        )

    def fail_read_flow_package(package_bytes: bytes) -> object:
        raise AssertionError(
            "import-plan should not parse package bytes on scope mismatch"
        )

    monkeypatch.setattr(
        flow_package_router.flow_access_context,
        "resolve_space_access_context",
        fake_resolve_space_access_context,
    )
    monkeypatch.setattr(
        flow_package_router,
        "read_flow_package",
        fail_read_flow_package,
    )

    with pytest.raises(HTTPException) as exc_info:
        await flow_package_router.create_flow_package_import_plan(
            id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            package_file=_upload(b"not a package"),
            request=cast(Request, object()),
            container=cast(Container, _FakeContainer()),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "code": "insufficient_scope",
        "message": "API key space scope does not match target package import space.",
        "context": {"auth_layer": "api_key_scope"},
    }


@pytest.mark.anyio
async def test_import_flow_package_as_draft_returns_typed_response_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_space_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    import_id = UUID("99999999-9999-4999-8999-999999999999")
    flow_id = UUID("88888888-8888-4888-8888-888888888888")
    selected_binding = _selected_model_binding()
    captured_repo_selection: list[FlowPackageImportSelection] = []
    captured_install_bindings: list[tuple[LocalResourceBinding, ...]] = []

    _patch_import_access(
        monkeypatch,
        target_space_id=target_space_id,
        space=_FakeSpace(default_transcription_model_id=uuid4()),
    )

    class FakeInstallService:
        async def install_as_draft(
            self,
            *,
            envelope: object,
            flow_service: object,
            space_id: UUID,
            selected_bindings: tuple[LocalResourceBinding, ...],
            candidates: FlowPackageImportPlannerCandidates,
            default_transcription_model_id: UUID | None = None,
        ) -> FlowPackageInstallResult:
            captured_install_bindings.append(selected_bindings)
            assert default_transcription_model_id is not None
            return FlowPackageInstallResult(
                flow_id=flow_id,
                flow_name="Demo",
                package_id="se.demo.flow",
                package_version="1.0.0",
                content_checksum=reader.read_flow_package(
                    _package_bytes()
                ).content_checksum,
                steps_created=1,
                resource_bindings_count=1,
            )

    class FakeImportRepo:
        def __init__(self, session: object) -> None:
            assert isinstance(session, _FakeSession)

        async def create_draft_created(
            self,
            *,
            selection: FlowPackageImportSelection,
            **kwargs: object,
        ) -> UUID:
            captured_repo_selection.append(selection)
            assert kwargs["flow_id"] == flow_id
            assert kwargs["space_id"] == target_space_id
            return import_id

    audit_service = _FakeAuditService()
    monkeypatch.setattr(
        flow_package_router, "FlowPackageInstallService", FakeInstallService
    )
    monkeypatch.setattr(
        flow_package_router, "FlowPackageImportRepository", FakeImportRepo
    )

    response = await flow_package_router.import_flow_package_as_draft(
        id=target_space_id,
        import_request=_import_request(selected_binding),
        request=cast(Request, object()),
        container=cast(
            Container,
            _FakeContainer(
                audit_service=audit_service,
                session=_FakeSession(),
            ),
        ),
    )

    assert not isinstance(response, flow_package_router.JSONResponse)
    assert response.import_id == import_id
    assert response.flow_id == flow_id
    assert response.resource_bindings_count == 1
    assert captured_install_bindings == [(selected_binding,)]
    assert captured_repo_selection[0].selected_bindings == [selected_binding]
    assert audit_service.events[0]["action"] is ActionType.FLOW_PACKAGE_DRAFT_INSTALLED
    assert audit_service.events[0]["entity_id"] == flow_id
    assert audit_service.events[0]["metadata"]["extra"]["import_id"] == str(import_id)


@pytest.mark.anyio
async def test_import_flow_package_records_failed_attempt_and_returns_general_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_space_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    import_id = UUID("99999999-9999-4999-8999-999999999999")
    selected_binding = _selected_model_binding()
    captured_failure: list[FlowPackageImportFailurePayload] = []
    fake_session = _FakeSession()

    _patch_import_access(
        monkeypatch,
        target_space_id=target_space_id,
        space=_FakeSpace(default_transcription_model_id=uuid4()),
    )

    class FakeInstallService:
        async def install_as_draft(self, **kwargs: object) -> FlowPackageInstallResult:
            raise FlowPackageValidationError(
                code=FlowPackageErrorCode.IMPORT_UNAVAILABLE_LOCAL_RESOURCE,
                message="Selected model is unavailable.",
                context={"slot_ref": "model.structured"},
            )

    class FakeImportRepo:
        def __init__(self, session: object) -> None:
            assert session is fake_session

        async def create_failed(
            self,
            *,
            failure: FlowPackageImportFailurePayload,
            **kwargs: object,
        ) -> UUID:
            captured_failure.append(failure)
            assert kwargs["space_id"] == target_space_id
            return import_id

    monkeypatch.setattr(
        flow_package_router, "FlowPackageInstallService", FakeInstallService
    )
    monkeypatch.setattr(
        flow_package_router, "FlowPackageImportRepository", FakeImportRepo
    )

    response = await flow_package_router.import_flow_package_as_draft(
        id=target_space_id,
        import_request=_import_request(selected_binding),
        request=_request(),
        container=cast(Container, _FakeContainer(session=fake_session)),
    )

    assert isinstance(response, flow_package_router.JSONResponse)
    payload = json.loads(response.body)
    assert (
        payload["code"] == FlowPackageErrorCode.IMPORT_UNAVAILABLE_LOCAL_RESOURCE.value
    )
    assert payload["message"] == "Selected model is unavailable."
    assert payload["context"] == {"slot_ref": "model.structured"}
    assert captured_failure[0].code == payload["code"]
    assert fake_session.nested_transactions == ["rolled_back"]


@pytest.mark.anyio
async def test_import_flow_package_rejects_invalid_base64_without_import_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_space_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    _patch_import_access(
        monkeypatch,
        target_space_id=target_space_id,
        space=_FakeSpace(default_transcription_model_id=uuid4()),
    )

    class FailImportRepo:
        def __init__(self, session: object) -> None:
            raise AssertionError("invalid base64 must not create an import record")

    monkeypatch.setattr(
        flow_package_router, "FlowPackageImportRepository", FailImportRepo
    )

    with pytest.raises(BadRequestException) as exc_info:
        await flow_package_router.import_flow_package_as_draft(
            id=target_space_id,
            import_request=FlowPackageImportRequest(
                package_base64="not base64!",
                selected_bindings=[],
            ),
            request=cast(Request, object()),
            container=cast(Container, _FakeContainer(session=_FakeSession())),
        )

    assert exc_info.value.code == FlowPackageErrorCode.BASE64_INVALID.value


@pytest.mark.anyio
async def test_import_flow_package_audio_requires_target_transcription_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_space_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    captured_failure: list[FlowPackageImportFailurePayload] = []
    _patch_import_access(
        monkeypatch,
        target_space_id=target_space_id,
        space=_FakeSpace(default_transcription_model_id=None),
    )

    class FailInstallService:
        async def install_as_draft(self, **kwargs: object) -> FlowPackageInstallResult:
            raise AssertionError(
                "audio package without transcription model must not install"
            )

    class FakeImportRepo:
        def __init__(self, session: object) -> None:
            pass

        async def create_failed(
            self,
            *,
            failure: FlowPackageImportFailurePayload,
            **kwargs: object,
        ) -> UUID:
            captured_failure.append(failure)
            return UUID("99999999-9999-4999-8999-999999999999")

    monkeypatch.setattr(
        flow_package_router, "FlowPackageInstallService", FailInstallService
    )
    monkeypatch.setattr(
        flow_package_router, "FlowPackageImportRepository", FakeImportRepo
    )

    response = await flow_package_router.import_flow_package_as_draft(
        id=target_space_id,
        import_request=FlowPackageImportRequest(
            package_base64=_package_base64(spec=_audio_spec()),
            selected_bindings=[],
        ),
        request=_request(),
        container=cast(Container, _FakeContainer(session=_FakeSession())),
    )

    assert isinstance(response, flow_package_router.JSONResponse)
    payload = json.loads(response.body)
    assert payload["code"] == "transcription_model_required"
    assert captured_failure[0].code == "transcription_model_required"


def test_validation_response_forbids_extra_fields() -> None:
    payload = FlowPackageValidationPublic.from_envelope(
        reader.read_flow_package(_package_bytes())
    ).model_dump(mode="json")
    payload["unexpected"] = "value"

    with pytest.raises(ValidationError):
        FlowPackageValidationPublic.model_validate(payload)


def test_export_request_reuses_manifest_validation_rules() -> None:
    with pytest.raises(ValidationError):
        FlowPackageExportRequest(
            package_id="Invalid Package",
            package_version="1.0.0",
            name="Demo",
        )


def test_import_request_accepts_json_resource_bindings_at_http_boundary() -> None:
    import_request = FlowPackageImportRequest.model_validate(
        {
            "package_base64": "UEsDBBQAAAAIA...",
            "selected_bindings": [
                {
                    "slot_ref": {
                        "kind": "model",
                        "slot": "structured",
                        "label": "Structured",
                    },
                    "local_kind": "completion_model",
                    "local_id": "11111111-1111-4111-8111-111111111111",
                }
            ],
        }
    )

    import_selection = import_request.import_selection()

    assert import_selection.selected_bindings == [_selected_model_binding()]


def test_import_request_rejects_invalid_json_resource_binding() -> None:
    with pytest.raises(ValidationError):
        FlowPackageImportRequest.model_validate(
            {
                "package_base64": "UEsDBBQAAAAIA...",
                "selected_bindings": [
                    {
                        "slot_ref": {
                            "kind": "model",
                            "slot": "structured",
                            "label": "Structured",
                        },
                        "local_kind": "collection",
                        "local_id": "22222222-2222-4222-8222-222222222222",
                    }
                ],
            }
        )


@pytest.mark.anyio
async def test_export_flow_package_checks_access_before_exporting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access_calls: list[bool] = []
    export_calls: list[UUID] = []
    flow_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    result = _export_result()

    async def fake_require_flow_edit_access(
        request: Request,
        container: Container,
        *,
        flow_id: UUID,
        allow_service_key_principals: bool = False,
    ) -> FlowAccessContext:
        access_calls.append(allow_service_key_principals)
        return FlowAccessContext(
            flow=_flow(flow_id=flow_id),
            actor=cast(SpaceActor, _FakeSpaceActor(can_edit=True)),
            scope_filter=ScopeFilter(),
        )

    class FakeExportService:
        def __init__(self, *, flow_service: object, package_writer: object) -> None:
            assert flow_service is _FLOW_SERVICE_SENTINEL

        async def export_to_bytes(
            self,
            *,
            flow_id: UUID,
            flow: Flow,
            manifest_metadata: object,
        ) -> FlowPackageExportResult:
            export_calls.append(flow_id)
            return result

    audit_service = _FakeAuditService()
    monkeypatch.setattr(
        flow_package_router,
        "require_flow_edit_access",
        fake_require_flow_edit_access,
    )
    monkeypatch.setattr(
        flow_package_router, "FlowPackageExportService", FakeExportService
    )

    response = await flow_package_router.export_flow_package(
        id=flow_id,
        export_request=_export_request(),
        request=cast(Request, object()),
        container=cast(Container, _FakeContainer(audit_service=audit_service)),
    )

    assert access_calls == [False]
    assert export_calls == [flow_id]
    assert response.body == result.package_bytes
    assert response.media_type == flow_package_router.FLOW_PACKAGE_MEDIA_TYPE
    assert response.headers["content-disposition"] == (
        'attachment; filename="demo.eneo-flowpkg"'
    )
    assert len(audit_service.events) == 1
    event = audit_service.events[0]
    assert event["action"] is ActionType.FLOW_PACKAGE_EXPORTED
    assert event["entity_type"] is EntityType.FLOW
    assert event["entity_id"] == flow_id
    assert event["description"] == "Exported Flow package 'se.demo.flow'"
    assert event["metadata"]["extra"] == {
        "package_id": "se.demo.flow",
        "package_version": "1.0.0",
        "content_checksum": result.envelope.content_checksum,
        "requirements_count": 1,
        "payload_size_bytes": len(result.package_bytes),
    }


@pytest.mark.anyio
async def test_export_flow_package_translates_export_errors_without_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    export_error = FlowPackageExportError(
        code=FlowPackageExportErrorCode.MISSING_ASSISTANT_SNAPSHOT,
        message="Assistant authoring snapshot is missing.",
        context={"step_order": 2},
    )

    _patch_export_access(monkeypatch, flow_id=flow_id)

    class FakeExportService:
        def __init__(self, *, flow_service: object, package_writer: object) -> None:
            pass

        async def export_to_bytes(
            self,
            *,
            flow_id: UUID,
            flow: Flow,
            manifest_metadata: object,
        ) -> FlowPackageExportResult:
            raise export_error

    audit_service = _FakeAuditService()
    monkeypatch.setattr(
        flow_package_router, "FlowPackageExportService", FakeExportService
    )

    with pytest.raises(BadRequestException) as exc_info:
        await flow_package_router.export_flow_package(
            id=flow_id,
            export_request=_export_request(),
            request=cast(Request, object()),
            container=cast(Container, _FakeContainer(audit_service=audit_service)),
        )

    assert exc_info.value.code == export_error.code.value
    assert exc_info.value.context == {"step_order": 2}
    assert audit_service.events == []


@pytest.mark.anyio
async def test_export_flow_package_translates_oversized_exports_without_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow_id = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    export_error = FlowPackageExportError(
        code=FlowPackageExportErrorCode.PACKAGE_BYTES_TOO_LARGE,
        message="Flow package export exceeds the allowed size.",
        context={"package_size_bytes": 6, "max_package_export_bytes": 5},
    )

    _patch_export_access(monkeypatch, flow_id=flow_id)

    class FakeExportService:
        def __init__(self, *, flow_service: object, package_writer: object) -> None:
            pass

        async def export_to_bytes(
            self,
            *,
            flow_id: UUID,
            flow: Flow,
            manifest_metadata: object,
        ) -> FlowPackageExportResult:
            raise export_error

    audit_service = _FakeAuditService()
    monkeypatch.setattr(
        flow_package_router, "FlowPackageExportService", FakeExportService
    )

    with pytest.raises(FileTooLargeException) as exc_info:
        await flow_package_router.export_flow_package(
            id=flow_id,
            export_request=_export_request(),
            request=cast(Request, object()),
            container=cast(Container, _FakeContainer(audit_service=audit_service)),
        )

    assert exc_info.value.code == export_error.code.value
    assert exc_info.value.file_size == 6
    assert exc_info.value.max_size == 5
    assert audit_service.events == []


_FLOW_SERVICE_SENTINEL = object()


class _FakeContainer:
    def __init__(
        self,
        *,
        user: "_FakeUser | None" = None,
        audit_service: "_FakeAuditService | None" = None,
        flow_service: object = _FLOW_SERVICE_SENTINEL,
        session: "_FakeSession | None" = None,
    ) -> None:
        self._user = user or _FakeUser()
        self._audit_service = audit_service or _FakeAuditService()
        self._flow_service = flow_service
        self._session = session or _FakeSession()

    def user(self) -> "_FakeUser":
        return self._user

    def audit_service(self) -> "_FakeAuditService":
        return self._audit_service

    def flow_service(self) -> object:
        return self._flow_service

    def session(self) -> "_FakeSession":
        return self._session


class _FakeUser:
    id = UUID("11111111-1111-4111-8111-111111111111")
    tenant_id = UUID("22222222-2222-4222-8222-222222222222")
    username = "exporter"
    email = "exporter@example.com"
    permissions: list[object] = []


class _FakeAuditService:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def log_async(self, **kwargs: object) -> None:
        self.events.append(kwargs)


class _FakeSpaceActor:
    def __init__(self, *, can_edit: bool) -> None:
        self._can_edit = can_edit

    def can_edit_flows(self) -> bool:
        return self._can_edit


class _FakeTranscriptionModel:
    def __init__(self, model_id: UUID) -> None:
        self.id = model_id


class _FakeSpace:
    def __init__(self, *, default_transcription_model_id: UUID | None) -> None:
        self._default_transcription_model_id = default_transcription_model_id

    def get_default_transcription_model(self) -> _FakeTranscriptionModel | None:
        if self._default_transcription_model_id is None:
            return None
        return _FakeTranscriptionModel(self._default_transcription_model_id)


class _FakeNestedTransaction:
    def __init__(self, session: "_FakeSession") -> None:
        self._session = session

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool:
        self._session.nested_transactions.append(
            "rolled_back" if exc is not None else "committed"
        )
        return False


class _FakeSession:
    def __init__(self) -> None:
        self.nested_transactions: list[str] = []

    def begin_nested(self) -> _FakeNestedTransaction:
        return _FakeNestedTransaction(self)


def _patch_export_access(
    monkeypatch: pytest.MonkeyPatch,
    *,
    flow_id: UUID,
) -> None:
    async def fake_require_flow_edit_access(
        request: Request,
        container: Container,
        *,
        flow_id: UUID,
        allow_service_key_principals: bool = False,
    ) -> FlowAccessContext:
        return FlowAccessContext(
            flow=_flow(flow_id=flow_id),
            actor=cast(SpaceActor, _FakeSpaceActor(can_edit=True)),
            scope_filter=ScopeFilter(),
        )

    monkeypatch.setattr(
        flow_package_router,
        "require_flow_edit_access",
        fake_require_flow_edit_access,
    )


def _patch_import_access(
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_space_id: UUID,
    space: _FakeSpace,
) -> None:
    async def fake_resolve_space_access_context(
        request: Request,
        container: Container,
        *,
        space_id: UUID,
        required_access: FlowApiAction = FlowApiAction.VIEW,
        scope_mismatch_message: str = "",
        allow_service_key_principals: bool = False,
    ) -> FlowSpaceAccessContext:
        assert space_id == target_space_id
        assert required_access is FlowApiAction.EDIT
        return FlowSpaceAccessContext(
            space=cast(Space, space),
            actor=cast(SpaceActor, _FakeSpaceActor(can_edit=True)),
            scope_filter=ScopeFilter(),
        )

    def fake_candidate_loader(space: Space) -> FlowPackageImportPlannerCandidates:
        return FlowPackageImportPlannerCandidates(models=[_model_candidate()])

    monkeypatch.setattr(
        flow_package_router.flow_access_context,
        "resolve_space_access_context",
        fake_resolve_space_access_context,
    )
    monkeypatch.setattr(
        flow_package_router,
        "build_flow_package_import_planner_candidates_for_space",
        fake_candidate_loader,
    )


def _export_request() -> FlowPackageExportRequest:
    return FlowPackageExportRequest(
        package_id="se.demo.flow",
        package_version="1.0.0",
        name="Demo Flow",
        description="Demo package",
    )


def _export_result() -> FlowPackageExportResult:
    envelope = reader.read_flow_package(_package_bytes())
    return FlowPackageExportResult(
        package_bytes=b"flow package bytes",
        envelope=envelope,
        filename="demo.eneo-flowpkg",
    )


def _flow(*, flow_id: UUID) -> Flow:
    return Flow(
        id=flow_id,
        tenant_id=UUID("22222222-2222-4222-8222-222222222222"),
        space_id=UUID("33333333-3333-4333-8333-333333333333"),
        name="Demo Flow",
        description="Demo flow",
        created_by_user_id=UUID("11111111-1111-4111-8111-111111111111"),
        owner_user_id=UUID("11111111-1111-4111-8111-111111111111"),
        published_version=None,
        metadata_json=None,
        data_retention_days=30,
        created_at=None,
        updated_at=None,
        steps=[],
    )


def _upload(content: bytes) -> UploadFile:
    return UploadFile(filename="demo.eneo-flowpkg", file=BytesIO(content))


def _request() -> Request:
    return cast(Request, SimpleNamespace(headers={}))


def _package_bytes(*, spec: FlowDraftSpecCore | None = None) -> bytes:
    return _zip_docs(_package_docs(spec=spec))


def _package_base64(*, spec: FlowDraftSpecCore | None = None) -> str:
    return base64.b64encode(_package_bytes(spec=spec)).decode("ascii")


def _package_docs(*, spec: FlowDraftSpecCore | None = None) -> dict[str, JsonObject]:
    spec = spec or FlowDraftSpecCore(
        flow_name="Demo",
        steps=[
            StepSpec(
                plan_step_ref="extract",
                name="Extract",
                assistant_spec=AssistantSpec(
                    instructions="Extract facts.",
                    model_ref="model.structured",
                ),
                input_source=InputSource.FLOW_INPUT,
            )
        ],
    )
    requirements = FlowPackageRequirementSet(
        schema_version=1,
        requirements=[
            FlowPackageModelRequirement(
                slot_ref=ResourceSlotRef(
                    kind=ResourceSlotKind.MODEL,
                    slot="structured",
                    label="Structured",
                ),
                matching_preferences=FlowPackageModelMatchingPreferences(
                    tested_with=[
                        FlowPackageModelIdentity(
                            provider="openai",
                            model="gpt-5.4-mini",
                        )
                    ]
                ),
            )
        ],
    )
    draft = FlowPackageFlowDraft(schema_version=1, spec=spec)
    provenance = FlowPackageProvenance(
        schema_version=1,
        exported_at=datetime(2026, 5, 18, tzinfo=timezone.utc),
    )
    manifest = FlowPackageManifest(
        schema_version=1,
        package_id="se.demo.flow",
        package_version="1.0.0",
        name="Demo Flow",
        description="Demo package",
        content_checksum="0" * 64,
    )
    content_checksum = compose_content_checksum(
        spec_hash=spec.spec_hash(),
        manifest_hash=hash_json_value(manifest.canonical_hash_input()),
        requirements_hash=hash_json_value(
            cast(JsonObject, requirements.model_dump(mode="json"))
        ),
        provenance_hash=hash_json_value(
            cast(JsonObject, provenance.model_dump(mode="json"))
        ),
    )
    manifest = manifest.model_copy(update={"content_checksum": content_checksum})
    return {
        reader.MANIFEST_PATH: cast(JsonObject, manifest.model_dump(mode="json")),
        reader.FLOW_DRAFT_PATH: cast(JsonObject, draft.model_dump(mode="json")),
        reader.REQUIREMENTS_PATH: cast(
            JsonObject, requirements.model_dump(mode="json")
        ),
        reader.PROVENANCE_PATH: cast(JsonObject, provenance.model_dump(mode="json")),
    }


def _audio_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Audio Demo",
        steps=[
            StepSpec(
                plan_step_ref="transcribe",
                name="Transcribe",
                assistant_spec=AssistantSpec(instructions="Transcribe audio."),
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.AUDIO,
                output_mode=OutputMode.TRANSCRIBE_ONLY,
                output_type=OutputType.TEXT,
            )
        ],
    )


def _selected_model_binding() -> LocalResourceBinding:
    return LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind.MODEL,
            slot="structured",
            label="Structured",
        ),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=UUID("11111111-1111-4111-8111-111111111111"),
    )


def _import_request(
    selected_binding: LocalResourceBinding,
) -> FlowPackageImportRequest:
    return FlowPackageImportRequest.model_validate(
        {
            "package_base64": _package_base64(),
            "selected_bindings": [
                selected_binding.model_dump(
                    mode="json",
                    exclude={"slot_ref": {"ref"}},
                )
            ],
        }
    )


def _model_candidate() -> FlowPackageModelCandidate:
    return FlowPackageModelCandidate(
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=UUID("11111111-1111-4111-8111-111111111111"),
        label="Structured Mini",
        model_kind=FlowPackageModelKind.COMPLETION_MODEL,
        identity=FlowPackageModelIdentity(provider="openai", model="gpt-5.4-mini"),
    )


def _zip_docs(docs: Mapping[str, JsonObject]) -> bytes:
    payloads = {
        path: json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
        for path, value in docs.items()
    }
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for path, payload in payloads.items():
            package.writestr(path, payload)
    return buffer.getvalue()
