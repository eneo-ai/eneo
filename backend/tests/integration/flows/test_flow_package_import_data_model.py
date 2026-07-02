from __future__ import annotations

import base64
import json
import re
import zipfile
from collections.abc import Mapping
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import CheckConstraint, Index
from sqlalchemy.exc import IntegrityError

from eneo.actors.actors.space_actor import SpaceActor
from eneo.authentication.auth_dependencies import ScopeFilter
from eneo.database.tables.flow_tables import (
    FLOW_PACKAGE_IMPORT_SOURCE_VALUES,
    FLOW_PACKAGE_IMPORT_STATUS_VALUES,
    FlowPackageImports,
    Flows,
)
from eneo.flow_packages.api import flow_package_router
from eneo.flow_packages.api.flow_package_models import (
    FlowPackageExportRequest,
    FlowPackageImportRequest,
)
from eneo.flow_packages.application.flow_package_import_planner import (
    FlowPackageImportPlannerCandidates,
)
from eneo.flow_packages.domain.flow_package_checksum import (
    compose_content_checksum,
    hash_json_value,
)
from eneo.flow_packages.domain.flow_package_draft import FlowPackageFlowDraft
from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
)
from eneo.flow_packages.domain.flow_package_import_plan import (
    FlowPackageImportPlan,
    FlowPackageImportPlanSummary,
    FlowPackageModelCandidate,
)
from eneo.flow_packages.domain.flow_package_import_record import (
    FlowPackageImportFailurePayload,
    FlowPackageImportSelection,
    FlowPackageImportSource,
    FlowPackageImportStatus,
)
from eneo.flow_packages.domain.flow_package_manifest import (
    FLOW_PACKAGE_PAYLOAD_SCHEMA,
    EneoPackageKind,
    FlowPackageManifest,
)
from eneo.flow_packages.domain.flow_package_provenance import FlowPackageProvenance
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageModelIdentity,
    FlowPackageModelKind,
    FlowPackageModelRequirement,
    FlowPackageRequirementSet,
)
from eneo.flow_packages.infrastructure import flow_package_zip_reader as reader
from eneo.flows.api.flow_access_context import (
    FlowAccessContext,
    FlowSpaceAccessContext,
)
from eneo.flows.application.flow_authoring_command import (
    CreateFlowAuthoringCommand,
    FlowAuthoringCommandService,
    FlowPackageAuthoringOrigin,
)
from eneo.flows.flow_access_policy import FlowApiAction
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    StepSpec,
)
from eneo.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from eneo.json_types import JsonObject
from eneo.main.container.container import Container
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.spaces.api.space_models import SpaceRoleValue
from eneo.spaces.space import Space
from eneo.users.user import UserAdd, UserState


def _constraint_names(table: object) -> set[str]:
    return {
        constraint.name or ""
        for constraint in table.__table__.constraints
        if constraint.name is not None
    }


def _check_constraint_sql(table: object, constraint_name: str) -> str:
    for constraint in table.__table__.constraints:
        if (
            isinstance(constraint, CheckConstraint)
            and constraint.name == constraint_name
        ):
            return str(constraint.sqltext)
    raise AssertionError(f"Check constraint {constraint_name} was not found.")


def _check_constraint_values(table: object, constraint_name: str) -> tuple[str, ...]:
    return tuple(
        re.findall(r"'([^']+)'", _check_constraint_sql(table, constraint_name))
    )


def _index_by_name(table: object, index_name: str) -> Index:
    for index in table.__table__.indexes:
        if index.name == index_name:
            return index
    raise AssertionError(f"Index {index_name} was not found.")


async def _create_space(*, session, completion_model_factory, space_factory) -> object:
    model = await completion_model_factory(
        session,
        f"flow-package-import-model-{uuid4()}",
    )
    return await space_factory(
        session,
        f"Flow package import {uuid4()}",
        [model.id],
    )


async def _add_space_membership(
    *,
    session,
    space_id: UUID,
    user_id: UUID,
    role: SpaceRoleValue = SpaceRoleValue.ADMIN,
) -> None:
    await session.execute(
        sa.text(
            """
            INSERT INTO spaces_users (space_id, user_id, role)
            VALUES (:space_id, :user_id, :role)
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "space_id": str(space_id),
            "user_id": str(user_id),
            "role": role.value,
        },
    )


async def _user_with_flow_permissions_token(
    *,
    db_container,
    admin_user,
    permissions: tuple[Permission, ...],
) -> tuple[UUID, str]:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"flow-package-manage-{uuid4().hex[:8]}",
                permissions=list(permissions),
                tenant_id=admin_user.tenant_id,
            )
        )
        user = await container.user_repo().add(
            UserAdd(
                email=f"flow-package-manager-{uuid4().hex[:8]}@example.com",
                username=f"flow_package_manager_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=admin_user.tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )
        token = container.auth_service().create_access_token_for_user(user)
    return user.id, token


def _import_plan() -> FlowPackageImportPlan:
    return FlowPackageImportPlan(
        package_id="se.demo.flow",
        package_version="1.0.0",
        package_kind=EneoPackageKind.FLOW,
        payload_schema=FLOW_PACKAGE_PAYLOAD_SCHEMA,
        content_checksum="0" * 64,
        package_summary=FlowPackageImportPlanSummary(
            name="Demo Flow",
            description="Demo package import plan.",
            spec_hash="1" * 64,
            steps_count=1,
            requirements_count=0,
            requirements_by_kind={},
        ),
    )


def _selection() -> FlowPackageImportSelection:
    return FlowPackageImportSelection()


def _failure() -> FlowPackageImportFailurePayload:
    return FlowPackageImportFailurePayload(
        code="flow_package_import_unavailable_local_resource",
        message="Selected model is unavailable.",
        context={"slot_ref": "model.structured"},
    )


async def _assert_integrity_error(session, row: FlowPackageImports) -> None:
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(row)
            await session.flush()


class _FakeSpaceActor:
    def can_edit_flows(self) -> bool:
        return True


class _FakeTargetSpace:
    def get_default_transcription_model(self) -> None:
        return None


def _request() -> Request:
    return cast(Request, SimpleNamespace(headers={}))


def _package_base64() -> str:
    return base64.b64encode(_package_bytes()).decode("ascii")


def _package_base64_with_model_requirement() -> str:
    return base64.b64encode(_package_bytes(require_model=True)).decode("ascii")


def _package_bytes(*, require_model: bool = False) -> bytes:
    return _zip_docs(_package_docs(require_model=require_model))


def _package_docs(*, require_model: bool = False) -> dict[str, JsonObject]:
    model_slot_ref = _model_slot_ref()
    spec = FlowDraftSpecCore(
        flow_name="Route Import Demo",
        steps=[
            StepSpec(
                plan_step_ref="summarize",
                name="Summarize",
                assistant_spec=AssistantSpec(
                    instructions="Summarize the input.",
                    model_ref=model_slot_ref.ref if require_model else None,
                ),
                input_source=InputSource.FLOW_INPUT,
            )
        ],
    )
    requirements = FlowPackageRequirementSet(
        schema_version=1,
        requirements=[
            FlowPackageModelRequirement(slot_ref=model_slot_ref),
        ]
        if require_model
        else [],
    )
    draft = FlowPackageFlowDraft(schema_version=1, spec=spec)
    provenance = FlowPackageProvenance(
        schema_version=1,
        exported_at=datetime(2026, 5, 19, tzinfo=timezone.utc),
    )
    manifest = FlowPackageManifest(
        schema_version=1,
        package_id="se.demo.route-import",
        package_version="1.0.0",
        name="Route Import Demo",
        description="Integration package for route import tests.",
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


def _model_slot_ref() -> ResourceSlotRef:
    return ResourceSlotRef(
        kind=ResourceSlotKind.MODEL,
        slot="structured",
        label="Structured Model",
    )


def _model_binding(model_id: UUID) -> LocalResourceBinding:
    return LocalResourceBinding(
        slot_ref=_model_slot_ref(),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=model_id,
    )


def _model_binding_request(model_id: UUID) -> JsonObject:
    return cast(
        JsonObject,
        _model_binding(model_id).model_dump(
            mode="json",
            exclude={"slot_ref": {"ref"}},
        ),
    )


def _model_candidate(model_id: UUID) -> FlowPackageModelCandidate:
    return FlowPackageModelCandidate(
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=model_id,
        label="Structured Model",
        model_kind=FlowPackageModelKind.COMPLETION_MODEL,
        identity=FlowPackageModelIdentity(provider="test", model="structured"),
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


def _patch_import_access(
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_space_id: UUID,
    candidates: FlowPackageImportPlannerCandidates | None = None,
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
            space=cast(Space, _FakeTargetSpace()),
            actor=cast(SpaceActor, _FakeSpaceActor()),
            scope_filter=ScopeFilter(),
        )

    def fake_candidate_loader(space: Space) -> FlowPackageImportPlannerCandidates:
        return candidates or FlowPackageImportPlannerCandidates()

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


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_package_import_failed_record_survives_draft_savepoint_rollback(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with db_container() as container:
        session = container.session()
        valid_model = await completion_model_factory(
            session=session,
            name=f"flow-package-savepoint-model-{uuid4()}",
        )
        space = await space_factory(
            session,
            f"Flow package import savepoint {uuid4()}",
            [valid_model.id],
        )
        space_id = space.id
        await _add_space_membership(
            session=session,
            space_id=space_id,
            user_id=admin_user.id,
        )
        missing_model_id = uuid4()
        _patch_import_access(
            monkeypatch,
            target_space_id=space_id,
            candidates=FlowPackageImportPlannerCandidates(
                models=[_model_candidate(missing_model_id)]
            ),
        )

        response = await flow_package_router.import_flow_package_as_draft(
            id=space_id,
            import_request=FlowPackageImportRequest(
                package_base64=_package_base64_with_model_requirement(),
                selected_bindings=[_model_binding_request(missing_model_id)],
            ),
            request=_request(),
            container=cast(Container, container),
        )
        await session.flush()

        row = await session.scalar(
            sa.select(FlowPackageImports).where(
                FlowPackageImports.space_id == space_id,
                FlowPackageImports.package_id == "se.demo.route-import",
            )
        )
        draft_flow_count = await session.scalar(
            sa.select(sa.func.count(Flows.id)).where(Flows.space_id == space_id)
        )

        assert isinstance(response, JSONResponse)
        assert response.status_code == 400
        assert row is not None
        assert row.status == FlowPackageImportStatus.FAILED.value
        assert row.flow_id is None
        assert row.failure_json == {
            "code": "bad_request",
            "message": "The completion model is not enabled in the space.",
            "context": {},
        }
        assert draft_flow_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_package_import_route_persists_failed_install_record(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session=session,
            name=f"flow-package-roundtrip-model-{uuid4()}",
        )
        space = await space_factory(
            session,
            f"Flow package roundtrip {uuid4()}",
            [model.id],
        )
        await _add_space_membership(
            session=session,
            space_id=space.id,
            user_id=admin_user.id,
        )
        _patch_import_access(
            monkeypatch,
            target_space_id=space.id,
            candidates=FlowPackageImportPlannerCandidates(
                models=[_model_candidate(model.id)]
            ),
        )

        class FakeInstallService:
            async def install_as_draft(self, **kwargs: object) -> object:
                raise FlowPackageValidationError(
                    code=FlowPackageErrorCode.IMPORT_UNAVAILABLE_LOCAL_RESOURCE,
                    message="Selected model is unavailable.",
                    context={"slot_ref": "model.structured"},
                )

        monkeypatch.setattr(
            flow_package_router,
            "FlowPackageInstallService",
            FakeInstallService,
        )

        response = await flow_package_router.import_flow_package_as_draft(
            id=space.id,
            import_request=FlowPackageImportRequest(
                package_base64=_package_base64(),
                selected_bindings=[],
            ),
            request=_request(),
            container=cast(Container, container),
        )
        await session.flush()

        row = await session.scalar(
            sa.select(FlowPackageImports).where(
                FlowPackageImports.space_id == space.id,
                FlowPackageImports.package_id == "se.demo.route-import",
            )
        )

        assert isinstance(response, JSONResponse)
        assert response.status_code == 400
        assert row is not None
        assert row.tenant_id == admin_user.tenant_id
        assert row.status == FlowPackageImportStatus.FAILED.value
        assert row.flow_id is None
        assert row.failure_json == {
            "code": FlowPackageErrorCode.IMPORT_UNAVAILABLE_LOCAL_RESOURCE.value,
            "message": "Selected model is unavailable.",
            "context": {"slot_ref": "model.structured"},
        }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_package_import_route_creates_draft_flow_and_import_record(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session=session,
            name=f"flow-package-roundtrip-model-{uuid4()}",
        )
        space = await space_factory(
            session,
            f"Flow package roundtrip {uuid4()}",
            [model.id],
        )
        await _add_space_membership(
            session=session,
            space_id=space.id,
            user_id=admin_user.id,
        )
        _patch_import_access(
            monkeypatch,
            target_space_id=space.id,
            candidates=FlowPackageImportPlannerCandidates(
                models=[_model_candidate(model.id)]
            ),
        )
        logged_imports: list[UUID] = []

        async def fake_log_flow_package_import(**kwargs: object) -> None:
            logged_imports.append(cast(UUID, kwargs["import_id"]))

        monkeypatch.setattr(
            flow_package_router,
            "_log_flow_package_import",
            fake_log_flow_package_import,
        )

        response = await flow_package_router.import_flow_package_as_draft(
            id=space.id,
            import_request=FlowPackageImportRequest(
                package_base64=_package_base64(),
                selected_bindings=[],
            ),
            request=_request(),
            container=cast(Container, container),
        )
        await session.flush()

        assert not isinstance(response, JSONResponse)
        assert response.flow_name == "Route Import Demo"
        assert response.package_id == "se.demo.route-import"
        assert response.package_version == "1.0.0"
        assert response.steps_created == 1
        assert response.resource_bindings_count == 0

        imported_flow = await session.scalar(
            sa.select(Flows).where(Flows.id == response.flow_id)
        )
        import_record = await session.scalar(
            sa.select(FlowPackageImports).where(
                FlowPackageImports.id == response.import_id
            )
        )

        assert imported_flow is not None
        assert imported_flow.tenant_id == admin_user.tenant_id
        assert imported_flow.space_id == space.id
        assert imported_flow.name == "Route Import Demo"
        assert import_record is not None
        assert import_record.status == FlowPackageImportStatus.DRAFT_CREATED.value
        assert import_record.flow_id == response.flow_id
        assert import_record.failure_json is None
        assert import_record.package_id == response.package_id
        assert import_record.package_version == response.package_version
        assert import_record.content_checksum == response.content_checksum
        assert import_record.selected_mappings_json == {
            "selected_bindings": [],
        }
        assert logged_imports == [response.import_id]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_package_export_import_route_roundtrip_creates_second_draft(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session=session,
            name=f"flow-package-roundtrip-model-{uuid4()}",
        )
        space = await space_factory(
            session,
            f"Flow package roundtrip {uuid4()}",
            [model.id],
        )
        await _add_space_membership(
            session=session,
            space_id=space.id,
            user_id=admin_user.id,
        )
        _patch_import_access(
            monkeypatch,
            target_space_id=space.id,
            candidates=FlowPackageImportPlannerCandidates(
                models=[_model_candidate(model.id)]
            ),
        )

        async def fake_log_flow_package_import(**kwargs: object) -> None:
            return None

        async def fake_log_flow_package_export(**kwargs: object) -> None:
            return None

        monkeypatch.setattr(
            flow_package_router,
            "_log_flow_package_import",
            fake_log_flow_package_import,
        )
        monkeypatch.setattr(
            flow_package_router,
            "_log_flow_package_export",
            fake_log_flow_package_export,
        )

        ai_builder_spec = FlowDraftSpecCore(
            flow_name="Route Import Demo",
            steps=[
                StepSpec(
                    plan_step_ref="summarize",
                    name="Summarize",
                    assistant_spec=AssistantSpec(
                        instructions="Summarize the input.",
                        model_ref=_model_slot_ref().ref,
                    ),
                    input_source=InputSource.FLOW_INPUT,
                )
            ],
        )
        ai_builder_apply = await FlowAuthoringCommandService().apply(
            command=CreateFlowAuthoringCommand(
                space_id=space.id,
                spec=ai_builder_spec,
                origin=FlowPackageAuthoringOrigin(
                    package_id="se.demo.route-import",
                    package_version="1.0.0",
                    content_checksum="sha256:test",
                ),
                resource_bindings=(_model_binding(model.id),),
            ),
            flow_service=container.flow_service(),
        )
        await session.flush()

        exported_flow = await container.flow_service().get_flow(
            ai_builder_apply.flow_id
        )

        async def fake_require_flow_edit_access(
            request: Request,
            container: Container,
            *,
            flow_id: UUID,
            allow_service_key_principals: bool = False,
        ) -> FlowAccessContext:
            assert flow_id == ai_builder_apply.flow_id
            assert allow_service_key_principals is False
            return FlowAccessContext(
                flow=exported_flow,
                actor=cast(SpaceActor, _FakeSpaceActor()),
                scope_filter=ScopeFilter(),
            )

        monkeypatch.setattr(
            flow_package_router,
            "require_flow_edit_access",
            fake_require_flow_edit_access,
        )

        export_response = await flow_package_router.export_flow_package(
            id=ai_builder_apply.flow_id,
            export_request=FlowPackageExportRequest(
                package_id="se.demo.route-roundtrip",
                package_version="1.0.0",
                name="Route Roundtrip Demo",
                description="Exported by route-level roundtrip test.",
            ),
            request=_request(),
            container=cast(Container, container),
        )

        exported_package_base64 = base64.b64encode(export_response.body).decode("ascii")
        second_import = await flow_package_router.import_flow_package_as_draft(
            id=space.id,
            import_request=FlowPackageImportRequest(
                package_base64=exported_package_base64,
                selected_bindings=[_model_binding_request(model.id)],
            ),
            request=_request(),
            container=cast(Container, container),
        )
        await session.flush()

        assert not isinstance(second_import, JSONResponse)
        assert second_import.flow_id != ai_builder_apply.flow_id
        assert second_import.flow_name == "Route Import Demo (2)"
        assert second_import.package_id == "se.demo.route-roundtrip"
        assert second_import.package_version == "1.0.0"
        assert second_import.steps_created == 1
        assert second_import.resource_bindings_count == 1

        import_records = (
            await session.scalars(
                sa.select(FlowPackageImports)
                .where(
                    FlowPackageImports.space_id == space.id,
                    FlowPackageImports.status
                    == FlowPackageImportStatus.DRAFT_CREATED.value,
                )
                .order_by(FlowPackageImports.created_at)
            )
        ).all()

        assert [record.flow_id for record in import_records] == [second_import.flow_id]
        assert [record.package_id for record in import_records] == [
            "se.demo.route-roundtrip"
        ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_package_export_route_requires_space_edit_access(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
) -> None:
    _ = patch_auth_service_jwt
    _, owner_token = await _user_with_flow_permissions_token(
        db_container=db_container,
        admin_user=admin_user,
        permissions=(Permission.SHARED_SPACES, Permission.FLOWS_MANAGE),
    )
    viewer_user_id, viewer_token = await _user_with_flow_permissions_token(
        db_container=db_container,
        admin_user=admin_user,
        permissions=(Permission.FLOWS_MANAGE,),
    )

    space_response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"flow-package-export-auth-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert space_response.status_code == 201, space_response.text
    space_id = space_response.json()["id"]

    flow_response = await client.post(
        "/api/v1/flows/",
        json={
            "space_id": space_id,
            "name": "Export auth boundary",
            "description": "Export must require space edit access.",
            "steps": [],
        },
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert flow_response.status_code == 201, flow_response.text
    flow_id = flow_response.json()["id"]

    async with db_container() as container:
        await _add_space_membership(
            session=container.session(),
            space_id=UUID(space_id),
            user_id=viewer_user_id,
            role=SpaceRoleValue.VIEWER,
        )

    response = await client.post(
        f"/api/v1/flows/{flow_id}/package-exports/",
        json={
            "package_id": "se.demo.export-auth",
            "package_version": "1.0.0",
            "name": "Export Auth Boundary",
        },
        headers={"Authorization": f"Bearer {viewer_token}"},
    )

    assert response.status_code == 403, response.text
    body = response.json()
    assert body["code"] == "insufficient_space_permission"
    assert body["context"] == {"auth_layer": "space_membership"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_package_import_rejects_invalid_terminal_shapes(
    db_container,
    completion_model_factory,
    space_factory,
    admin_user,
) -> None:
    async with db_container() as container:
        session = container.session()
        space = await _create_space(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
        )

        await _assert_integrity_error(
            session,
            FlowPackageImports(
                tenant_id=admin_user.tenant_id,
                space_id=space.id,
                created_by_user_id=admin_user.id,
                package_id="se.demo.flow",
                package_version="1.0.0",
                content_checksum="0" * 64,
                source=FlowPackageImportSource.FILE_UPLOAD.value,
                status=FlowPackageImportStatus.DRAFT_CREATED.value,
                import_plan_json=_import_plan().model_dump(
                    mode="json",
                    exclude={"can_publish_after_import"},
                ),
                selected_mappings_json=_selection().model_dump(mode="json"),
                failure_json=None,
            ),
        )


def test_flow_package_import_metadata_matches_import_record_contract() -> None:
    assert FLOW_PACKAGE_IMPORT_SOURCE_VALUES == (
        FlowPackageImportSource.FILE_UPLOAD.value,
    )
    assert FLOW_PACKAGE_IMPORT_STATUS_VALUES == (
        FlowPackageImportStatus.DRAFT_CREATED.value,
        FlowPackageImportStatus.FAILED.value,
    )
    assert (
        _check_constraint_values(
            FlowPackageImports,
            "ck_flow_package_imports_source",
        )
        == FLOW_PACKAGE_IMPORT_SOURCE_VALUES
    )
    assert (
        _check_constraint_values(
            FlowPackageImports,
            "ck_flow_package_imports_status",
        )
        == FLOW_PACKAGE_IMPORT_STATUS_VALUES
    )
    assert "ck_flow_package_imports_content_checksum" in _constraint_names(
        FlowPackageImports
    )
    assert "ck_flow_package_imports_terminal_shape" in _constraint_names(
        FlowPackageImports
    )

    tenant_space_index = _index_by_name(
        FlowPackageImports,
        "ix_flow_package_imports_tenant_space_created",
    )
    assert tuple(column.name for column in tenant_space_index.columns) == (
        "tenant_id",
        "space_id",
        "created_at",
    )

    checksum_index = _index_by_name(
        FlowPackageImports,
        "ix_flow_package_imports_space_checksum_created",
    )
    assert tuple(column.name for column in checksum_index.columns) == (
        "space_id",
        "content_checksum",
        "created_at",
    )
