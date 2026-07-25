import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from pydantic import ValidationError

from eneo.authentication.auth_dependencies import (
    require_platform_admin,
    require_session_auth,
    require_user_identity,
)
from eneo.database.tables.object_content_policy_table import (
    ObjectContentDeploymentPolicy,
)
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import (
    ConstrainingSource,
    DeploymentPolicy,
    DeploymentPolicyConflict,
    DeploymentPolicyRepository,
    DeploymentPolicyUpdate,
    ObjectStoreTargetNotSelectable,
    PolicyActor,
    UploadAdmissionSnapshot,
    UploadLimitUseCase,
    load_upload_admission_snapshot,
    project_upload_limits,
)
from eneo.object_content.deployment_policy_router import (
    replace_deployment_policy,
    router,
)
from eneo.tenants.tenant import TenantState
from eneo.users.user import (
    UserAdd,
    UserAddAdmin,
    UserPublic,
    UserState,
    UserUpdate,
    UserUpdatePublic,
)
from tests.fixtures import TEST_USER


def _migration_module() -> ModuleType:
    path = (
        Path(__file__).parents[3]
        / "alembic"
        / "versions"
        / "202607251700_add_object_content_deployment_policy.py"
    )
    spec = importlib.util.spec_from_file_location("deployment_policy_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_seed_uses_defaults_only_for_absent_values() -> None:
    resolve_seed_limits = _migration_module().resolve_seed_limits
    assert resolve_seed_limits({}) == {
        "session_file_limit_bytes": 10 * 1024 * 1024,
        "session_image_limit_bytes": 10 * 1024 * 1024,
        "knowledge_file_limit_bytes": 10 * 1024 * 1024,
        "transcription_audio_limit_bytes": 200 * 1024 * 1024,
    }
    assert resolve_seed_limits(
        {
            "UPLOAD_FILE_TO_SESSION_MAX_SIZE": "11",
            "UPLOAD_IMAGE_TO_SESSION_MAX_SIZE": "12",
            "UPLOAD_MAX_FILE_SIZE": "13",
            "TRANSCRIPTION_MAX_FILE_SIZE": "14",
        }
    ) == {
        "session_file_limit_bytes": 11,
        "session_image_limit_bytes": 12,
        "knowledge_file_limit_bytes": 13,
        "transcription_audio_limit_bytes": 14,
    }


@pytest.mark.parametrize("value", ["", "abc", "0", "-1"])
def test_legacy_seed_rejects_invalid_present_value(value: str) -> None:
    resolve_seed_limits = _migration_module().resolve_seed_limits
    with pytest.raises(ValueError, match="UPLOAD_MAX_FILE_SIZE"):
        resolve_seed_limits({"UPLOAD_MAX_FILE_SIZE": value})


def test_policy_update_is_full_typed_positive_replacement() -> None:
    update = DeploymentPolicyUpdate(
        expected_revision=3,
        new_write_storage_target=StorageKind.POSTGRES_INLINE,
        session_file_limit_bytes=1,
        session_image_limit_bytes=2,
        knowledge_file_limit_bytes=3,
        transcription_audio_limit_bytes=4,
    )
    assert update.expected_revision == 3

    with pytest.raises(ValidationError):
        DeploymentPolicyUpdate(
            expected_revision=0,
            new_write_storage_target=StorageKind.POSTGRES_INLINE,
            session_file_limit_bytes=1,
            session_image_limit_bytes=2,
            knowledge_file_limit_bytes=3,
            transcription_audio_limit_bytes=0,
        )


def test_policy_conflicts_have_stable_machine_readable_codes() -> None:
    assert DeploymentPolicyConflict.code == "deployment_policy_revision_conflict"
    assert ObjectStoreTargetNotSelectable.code == "object_store_target_not_selectable"


def test_tenant_user_write_schema_cannot_escalate_platform_authority() -> None:
    for schema in (UserAdd, UserAddAdmin, UserUpdate, UserUpdatePublic):
        assert "is_platform_admin" not in schema.model_fields
    assert "is_platform_admin" in UserPublic.model_fields
    projected = UserPublic(
        **TEST_USER.model_copy(update={"is_platform_admin": True}).model_dump()
    )
    assert projected.is_platform_admin is True


@pytest.mark.asyncio
async def test_platform_authority_requires_current_active_eligibility() -> None:
    eligible = TEST_USER.model_copy(update={"is_platform_admin": True})
    await require_platform_admin(eligible)

    ineligible = (
        TEST_USER.model_copy(update={"is_platform_admin": False}),
        eligible.model_copy(update={"state": UserState.INACTIVE}),
        eligible.model_copy(update={"state": UserState.INVITED}),
        eligible.model_copy(update={"state": UserState.DELETED, "deleted_at": None}),
        eligible.model_copy(update={"deleted_at": datetime.now(timezone.utc)}),
        eligible.model_copy(
            update={
                "tenant": eligible.tenant.model_copy(
                    update={"state": TenantState.SUSPENDED}
                )
            }
        ),
        eligible.model_copy(update={"roles": []}),
    )
    for user in ineligible:
        with pytest.raises(HTTPException) as error:
            await require_platform_admin(user)
        assert error.value.status_code == 403


def test_policy_mutation_composes_existing_session_and_identity_fences() -> None:
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.endpoint is replace_deployment_policy
    )
    dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
    assert require_session_auth in dependency_calls
    assert require_user_identity in dependency_calls
    assert require_platform_admin in dependency_calls
    assert route.responses[403]["model"].__name__ == "GeneralError"
    assert route.responses[409]["model"].__name__ == "GeneralError"


def test_policy_router_is_registered_on_the_admin_surface() -> None:
    from eneo.server.routers import router as api_router

    app = FastAPI()
    app.include_router(api_router)
    methods = set(app.openapi()["paths"]["/admin/object-content-policy"])

    assert methods == {"get", "put"}


@pytest.mark.asyncio
async def test_policy_replace_uses_revision_compare_and_swap() -> None:
    row = ObjectContentDeploymentPolicy(
        id=1,
        revision=4,
        new_write_storage_target="postgres_inline",
        session_file_limit_bytes=1,
        session_image_limit_bytes=2,
        knowledge_file_limit_bytes=3,
        transcription_audio_limit_bytes=4,
        updated_by_actor="platform_admin",
        updated_by_user_id=uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session = AsyncMock()
    session.scalar.side_effect = [row, None]
    repository = DeploymentPolicyRepository(session)
    replacement = DeploymentPolicyUpdate(
        expected_revision=3,
        new_write_storage_target=StorageKind.POSTGRES_INLINE,
        session_file_limit_bytes=1,
        session_image_limit_bytes=2,
        knowledge_file_limit_bytes=3,
        transcription_audio_limit_bytes=4,
    )
    assert (await repository.replace(replacement, actor_user_id=uuid4())).revision == 4
    with pytest.raises(DeploymentPolicyConflict):
        await repository.replace(replacement, actor_user_id=uuid4())


def test_limit_projection_applies_inline_ceiling_only_to_session_content() -> None:
    policy = _policy(
        target=StorageKind.POSTGRES_INLINE,
        session_file=101,
        session_image=100,
        knowledge_file=103,
        transcription_audio=104,
    )

    projections = project_upload_limits(policy, inline_maximum_bytes=100)

    assert [projection.use_case for projection in projections] == [
        UploadLimitUseCase.SESSION_FILE,
        UploadLimitUseCase.SESSION_IMAGE,
        UploadLimitUseCase.SESSION_AUDIO,
        UploadLimitUseCase.KNOWLEDGE_FILE,
        UploadLimitUseCase.KNOWLEDGE_AUDIO,
    ]
    assert projections[0].effective_bytes == 100
    assert projections[0].constraining_source is ConstrainingSource.OPERATOR_CEILING
    assert projections[1].effective_bytes == 100
    assert projections[1].constraining_source is ConstrainingSource.ADMIN_POLICY
    assert projections[2].effective_bytes == 100
    assert projections[2].operator_ceiling_bytes == 100
    assert projections[3].effective_bytes == 103
    assert projections[3].operator_ceiling_bytes is None
    assert projections[3].storage_target is None
    assert projections[4].effective_bytes == 104
    assert projections[4].operator_ceiling_bytes is None


def test_limit_projection_has_no_inline_ceiling_for_object_store() -> None:
    projections = project_upload_limits(
        _policy(
            target=StorageKind.OBJECT_STORE,
            session_file=101,
            session_image=102,
            knowledge_file=103,
            transcription_audio=104,
        ),
        inline_maximum_bytes=1,
    )

    assert all(projection.operator_ceiling_bytes is None for projection in projections)
    assert all(
        projection.constraining_source is ConstrainingSource.ADMIN_POLICY
        for projection in projections
    )
    assert projections[0].storage_target is StorageKind.OBJECT_STORE
    assert projections[3].storage_target is None


async def test_load_upload_admission_snapshot_reads_one_effective_revision() -> None:
    policy = _policy(
        target=StorageKind.POSTGRES_INLINE,
        session_file=101,
        session_image=102,
        knowledge_file=103,
        transcription_audio=104,
    )
    session = AsyncMock()
    session.scalar.return_value = SimpleNamespace(
        revision=policy.revision,
        new_write_storage_target=policy.new_write_storage_target.value,
        session_file_limit_bytes=policy.session_file_limit_bytes,
        session_image_limit_bytes=policy.session_image_limit_bytes,
        knowledge_file_limit_bytes=policy.knowledge_file_limit_bytes,
        transcription_audio_limit_bytes=policy.transcription_audio_limit_bytes,
        updated_by_actor=policy.updated_by_actor.value,
        updated_by_user_id=policy.updated_by_user_id,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )

    snapshot = await load_upload_admission_snapshot(
        session,
        inline_maximum_bytes=100,
    )

    assert snapshot == UploadAdmissionSnapshot(
        policy_revision=1,
        session_storage_target=StorageKind.POSTGRES_INLINE,
        session_operator_ceiling_bytes=100,
        session_file_maximum_bytes=100,
        session_image_maximum_bytes=100,
        session_audio_maximum_bytes=100,
        knowledge_file_maximum_bytes=103,
        knowledge_audio_maximum_bytes=104,
    )
    session.scalar.assert_awaited_once()


def _policy(
    *,
    target: StorageKind,
    session_file: int,
    session_image: int,
    knowledge_file: int,
    transcription_audio: int,
) -> DeploymentPolicy:
    now = datetime.now(timezone.utc)

    return DeploymentPolicy(
        revision=1,
        new_write_storage_target=target,
        session_file_limit_bytes=session_file,
        session_image_limit_bytes=session_image,
        knowledge_file_limit_bytes=knowledge_file,
        transcription_audio_limit_bytes=transcription_audio,
        updated_by_actor=PolicyActor.MIGRATION,
        updated_by_user_id=None,
        created_at=now,
        updated_at=now,
    )
