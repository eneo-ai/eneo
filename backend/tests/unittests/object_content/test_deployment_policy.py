import asyncio
import importlib.util
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

import eneo.object_content.deployment_policy_router as deployment_policy_router
from eneo.authentication.auth_dependencies import (
    require_platform_admin,
)
from eneo.database.database import get_session, get_session_with_transaction
from eneo.database.tables.object_content_policy_table import (
    ObjectContentDeploymentPolicy,
)
from eneo.object_content.content import StorageKind
from eneo.object_content.deployment_policy import (
    ConstrainingSource,
    DeploymentPolicy,
    DeploymentPolicyConflict,
    DeploymentPolicyPauseUpdate,
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
    get_deployment_policy,
    replace_deployment_policy,
    router,
)
from eneo.object_content.runtime import (
    ObjectContentReadinessCode,
    StorageCapability,
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


def test_legacy_seed_accepts_json_safe_maximum_and_rejects_next_value() -> None:
    resolve_seed_limits = _migration_module().resolve_seed_limits
    maximum = 9_007_199_254_740_991

    assert (
        resolve_seed_limits({"UPLOAD_MAX_FILE_SIZE": str(maximum)})[
            "knowledge_file_limit_bytes"
        ]
        == maximum
    )
    with pytest.raises(ValueError, match="UPLOAD_MAX_FILE_SIZE"):
        resolve_seed_limits({"UPLOAD_MAX_FILE_SIZE": str(maximum + 1)})


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


def test_move_pause_update_is_a_separate_typed_compare_and_swap() -> None:
    update = DeploymentPolicyPauseUpdate(
        expected_revision=3,
        moves_paused=True,
    )
    assert update.moves_paused is True

    with pytest.raises(ValidationError):
        DeploymentPolicyPauseUpdate(expected_revision=0, moves_paused=True)
    with pytest.raises(ValidationError):
        DeploymentPolicyPauseUpdate(
            expected_revision=3,
            moves_paused=True,
            new_write_storage_target=StorageKind.OBJECT_STORE,
        )


def test_policy_update_accepts_json_safe_maximum_and_rejects_next_value() -> None:
    maximum = 9_007_199_254_740_991
    accepted = DeploymentPolicyUpdate(
        expected_revision=3,
        new_write_storage_target=StorageKind.POSTGRES_INLINE,
        session_file_limit_bytes=maximum,
        session_image_limit_bytes=maximum,
        knowledge_file_limit_bytes=maximum,
        transcription_audio_limit_bytes=maximum,
    )
    assert accepted.session_file_limit_bytes == maximum

    with pytest.raises(ValidationError):
        DeploymentPolicyUpdate(
            expected_revision=3,
            new_write_storage_target=StorageKind.POSTGRES_INLINE,
            session_file_limit_bytes=maximum + 1,
            session_image_limit_bytes=maximum,
            knowledge_file_limit_bytes=maximum,
            transcription_audio_limit_bytes=maximum,
        )


def test_policy_put_boundary_accepts_json_safe_maximum_and_rejects_next_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    maximum = 9_007_199_254_740_991
    stored = _policy(
        target=StorageKind.POSTGRES_INLINE,
        session_file=maximum,
        session_image=maximum,
        knowledge_file=maximum,
        transcription_audio=maximum,
    )

    class Session:
        @asynccontextmanager
        async def begin(self):
            yield

    session = Session()
    user = TEST_USER.model_copy(update={"is_platform_admin": True})

    class Container:
        @staticmethod
        def session():
            return session

        @staticmethod
        def user():
            return user

    class Repository:
        def __init__(self, _session) -> None:
            pass

        async def get(self) -> DeploymentPolicy:
            return stored

        async def replace(
            self,
            _replacement: DeploymentPolicyUpdate,
            *,
            actor_user_id,
        ) -> DeploymentPolicy:
            del actor_user_id
            return stored

    projection = {
        "policy": {
            "revision": stored.revision,
            "new_write_storage_target": stored.new_write_storage_target,
            "session_file_limit_bytes": maximum,
            "session_image_limit_bytes": maximum,
            "knowledge_file_limit_bytes": maximum,
            "transcription_audio_limit_bytes": maximum,
            "moves_paused": stored.moves_paused,
            "updated_by_actor": stored.updated_by_actor,
            "created_at": stored.created_at,
            "updated_at": stored.updated_at,
        },
        "limits": [],
        "capabilities": [],
    }
    monkeypatch.setattr(
        deployment_policy_router,
        "DeploymentPolicyRepository",
        Repository,
    )
    monkeypatch.setattr(
        deployment_policy_router,
        "_read_projection",
        AsyncMock(return_value=projection),
    )

    app = FastAPI()
    app.include_router(router, prefix="/admin")
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.endpoint is replace_deployment_policy
    )
    for dependency in route.dependant.dependencies:
        if dependency.name == "container":
            app.dependency_overrides[dependency.call] = Container
        else:
            app.dependency_overrides[dependency.call] = lambda: None

    client = TestClient(app)
    payload = {
        "expected_revision": 1,
        "new_write_storage_target": "postgres_inline",
        "session_file_limit_bytes": maximum,
        "session_image_limit_bytes": maximum,
        "knowledge_file_limit_bytes": maximum,
        "transcription_audio_limit_bytes": maximum,
    }

    assert client.put("/admin/object-content-policy", json=payload).status_code == 200
    payload["session_file_limit_bytes"] = maximum + 1
    assert client.put("/admin/object-content-policy", json=payload).status_code == 422

    schema = app.openapi()["components"]["schemas"]["DeploymentPolicyUpdate"]
    assert schema["properties"]["session_file_limit_bytes"]["maximum"] == maximum


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
    assert deployment_policy_router._require_policy_session_auth in dependency_calls
    assert deployment_policy_router._require_policy_user_identity in dependency_calls
    assert deployment_policy_router._require_policy_platform_admin in dependency_calls
    assert route.responses[403]["model"].__name__ == "GeneralError"
    assert route.responses[409]["model"].__name__ == "GeneralError"


def test_inventory_read_composes_existing_platform_authority_fences() -> None:
    endpoint = getattr(
        deployment_policy_router,
        "get_object_content_inventory",
        None,
    )
    assert endpoint is not None
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.endpoint is endpoint
    )
    dependency_calls = {dependency.call for dependency in route.dependant.dependencies}
    assert deployment_policy_router._require_policy_session_auth in dependency_calls
    assert deployment_policy_router._require_policy_user_identity in dependency_calls
    assert deployment_policy_router._require_policy_platform_admin in dependency_calls
    assert route.responses[403]["model"].__name__ == "GeneralError"


@pytest.mark.parametrize(
    "endpoint",
    [
        replace_deployment_policy,
        deployment_policy_router.get_object_content_inventory,
        deployment_policy_router.get_object_content_moves,
        deployment_policy_router.queue_object_content_moves,
        deployment_policy_router.set_object_content_moves_paused,
    ],
)
def test_privileged_policy_routes_use_one_non_transactional_session(endpoint) -> None:
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.endpoint is endpoint
    )
    dependencies = list(route.dependant.dependencies)
    dependency_calls = set()
    while dependencies:
        dependency = dependencies.pop()
        dependency_calls.add(dependency.call)
        dependencies.extend(dependency.dependencies)

    assert get_session in dependency_calls
    assert get_session_with_transaction not in dependency_calls


def test_policy_get_uses_a_non_transactional_request_session() -> None:
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.endpoint is get_deployment_policy
    )
    dependencies = list(route.dependant.dependencies)
    dependency_calls = set()
    while dependencies:
        dependency = dependencies.pop()
        dependency_calls.add(dependency.call)
        dependencies.extend(dependency.dependencies)

    assert get_session in dependency_calls
    assert get_session_with_transaction not in dependency_calls


def test_policy_put_resolves_shared_container_once_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy(
        target=StorageKind.OBJECT_STORE,
        session_file=101,
        session_image=102,
        knowledge_file=103,
        transcription_audio=104,
    )

    class Session:
        def __init__(self) -> None:
            self.active = False

        def in_transaction(self) -> bool:
            return self.active

        @asynccontextmanager
        async def begin(self):
            assert not self.active
            self.active = True
            try:
                yield
            finally:
                self.active = False

    session = Session()
    resolutions = 0

    class Runtime:
        inline_maximum_bytes = 100
        object_store_maximum_bytes = 1_000

        async def storage_capabilities(self) -> tuple[StorageCapability, ...]:
            assert resolutions == 1
            assert not session.in_transaction()
            await asyncio.sleep(0)
            assert not session.in_transaction()
            return (
                StorageCapability(
                    target=StorageKind.OBJECT_STORE,
                    configured=True,
                    selectable=True,
                    readiness_code=ObjectContentReadinessCode.READY,
                ),
            )

    class Repository:
        def __init__(self, repository_session: Session) -> None:
            assert repository_session is session

        async def get(self) -> DeploymentPolicy:
            assert session.in_transaction()
            return policy

        async def replace(
            self,
            _replacement: DeploymentPolicyUpdate,
            *,
            actor_user_id,
        ) -> DeploymentPolicy:
            del actor_user_id
            assert session.in_transaction()
            return policy

    user = TEST_USER.model_copy(update={"is_platform_admin": True})
    container = SimpleNamespace(session=lambda: session, user=lambda: user)

    async def resolve_container():
        nonlocal resolutions
        resolutions += 1
        return container

    projection = {
        "policy": {
            "revision": policy.revision,
            "new_write_storage_target": policy.new_write_storage_target,
            "session_file_limit_bytes": policy.session_file_limit_bytes,
            "session_image_limit_bytes": policy.session_image_limit_bytes,
            "knowledge_file_limit_bytes": policy.knowledge_file_limit_bytes,
            "transcription_audio_limit_bytes": policy.transcription_audio_limit_bytes,
            "moves_paused": policy.moves_paused,
            "updated_by_actor": policy.updated_by_actor,
            "created_at": policy.created_at,
            "updated_at": policy.updated_at,
        },
        "limits": [],
        "capabilities": [],
    }
    monkeypatch.setattr(
        deployment_policy_router,
        "object_content_runtime",
        Runtime(),
    )
    monkeypatch.setattr(
        deployment_policy_router,
        "DeploymentPolicyRepository",
        Repository,
    )
    monkeypatch.setattr(
        deployment_policy_router,
        "_read_projection",
        AsyncMock(return_value=projection),
    )

    app = FastAPI()
    app.include_router(router, prefix="/admin")
    app.dependency_overrides[
        deployment_policy_router._policy_admin_container_dependency
    ] = resolve_container

    response = TestClient(app).put(
        "/admin/object-content-policy",
        json={
            "expected_revision": 1,
            "new_write_storage_target": "object_store",
            "session_file_limit_bytes": 101,
            "session_image_limit_bytes": 102,
            "knowledge_file_limit_bytes": 103,
            "transcription_audio_limit_bytes": 104,
        },
    )

    assert response.status_code == 200, response.text
    assert resolutions == 1


@pytest.mark.asyncio
async def test_concurrent_policy_projections_close_transactions_before_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy(
        target=StorageKind.POSTGRES_INLINE,
        session_file=101,
        session_image=102,
        knowledge_file=103,
        transcription_audio=104,
    )

    class Session:
        def __init__(self) -> None:
            self._transaction_active = False

        def in_transaction(self) -> bool:
            return self._transaction_active

        @asynccontextmanager
        async def begin(self):
            assert not self._transaction_active
            self._transaction_active = True
            try:
                yield
            finally:
                self._transaction_active = False

    request_session: ContextVar[Session] = ContextVar("policy_projection_session")

    class PolicyRepository:
        def __init__(self, session: Session) -> None:
            self._session = session

        async def get(self) -> DeploymentPolicy:
            assert self._session.in_transaction()
            await asyncio.sleep(0)
            return policy

    class Runtime:
        inline_maximum_bytes = 100
        object_store_maximum_bytes = None

        async def storage_capabilities(self) -> tuple[StorageCapability, ...]:
            session = request_session.get()
            assert not session.in_transaction()
            await asyncio.sleep(0)
            assert not session.in_transaction()
            return (
                StorageCapability(
                    target=StorageKind.POSTGRES_INLINE,
                    configured=True,
                    selectable=True,
                    readiness_code=ObjectContentReadinessCode.READY,
                ),
            )

    async def request_projection() -> None:
        session = Session()
        token = request_session.set(session)
        container = SimpleNamespace(
            session=lambda: session,
            user=lambda: TEST_USER,
        )
        try:
            await get_deployment_policy(container)
        finally:
            request_session.reset(token)

    monkeypatch.setattr(
        deployment_policy_router,
        "DeploymentPolicyRepository",
        PolicyRepository,
    )
    monkeypatch.setattr(
        deployment_policy_router,
        "object_content_runtime",
        Runtime(),
    )

    await asyncio.gather(*(request_projection() for _ in range(6)))


@pytest.mark.asyncio
async def test_policy_put_projects_after_its_compare_and_swap_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy(
        target=StorageKind.POSTGRES_INLINE,
        session_file=101,
        session_image=102,
        knowledge_file=103,
        transcription_audio=104,
    )

    class Session:
        def __init__(self) -> None:
            self._transaction_active = False

        def in_transaction(self) -> bool:
            return self._transaction_active

        @asynccontextmanager
        async def begin(self):
            assert not self._transaction_active
            self._transaction_active = True
            try:
                yield
            finally:
                self._transaction_active = False

    session = Session()

    class Repository:
        def __init__(self, repository_session: Session) -> None:
            assert repository_session is session

        async def get(self) -> DeploymentPolicy:
            assert session.in_transaction()
            return policy

        async def replace(
            self,
            _replacement: DeploymentPolicyUpdate,
            *,
            actor_user_id,
        ) -> DeploymentPolicy:
            del actor_user_id
            assert session.in_transaction()
            return policy

    projection = SimpleNamespace(policy=policy)

    async def read_projection(projection_session: Session) -> SimpleNamespace:
        assert projection_session is session
        assert not projection_session.in_transaction()
        return projection

    monkeypatch.setattr(
        deployment_policy_router,
        "DeploymentPolicyRepository",
        Repository,
    )
    monkeypatch.setattr(
        deployment_policy_router,
        "_read_projection",
        read_projection,
    )

    result = await replace_deployment_policy(
        DeploymentPolicyUpdate(
            expected_revision=1,
            new_write_storage_target=StorageKind.POSTGRES_INLINE,
            session_file_limit_bytes=101,
            session_image_limit_bytes=102,
            knowledge_file_limit_bytes=103,
            transcription_audio_limit_bytes=104,
        ),
        SimpleNamespace(
            session=lambda: session,
            user=lambda: TEST_USER.model_copy(update={"is_platform_admin": True}),
        ),
    )

    assert result is projection


def test_policy_router_is_registered_on_the_admin_surface() -> None:
    from eneo.server.routers import router as api_router

    app = FastAPI()
    app.include_router(api_router)
    methods = set(app.openapi()["paths"]["/admin/object-content-policy"])

    assert methods == {"get", "put"}
    assert set(app.openapi()["paths"]["/admin/object-content-inventory"]) == {"get"}
    assert set(app.openapi()["paths"]["/admin/object-content-moves"]) == {
        "get",
        "post",
    }
    assert set(app.openapi()["paths"]["/admin/object-content-moves/pause"]) == {"put"}


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
        moves_paused=False,
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


@pytest.mark.asyncio
async def test_move_pause_uses_the_policy_revision_compare_and_swap() -> None:
    row = ObjectContentDeploymentPolicy(
        id=1,
        revision=5,
        new_write_storage_target="postgres_inline",
        session_file_limit_bytes=1,
        session_image_limit_bytes=2,
        knowledge_file_limit_bytes=3,
        transcription_audio_limit_bytes=4,
        moves_paused=True,
        updated_by_actor="platform_admin",
        updated_by_user_id=uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session = AsyncMock()
    session.scalar.side_effect = [row, None]
    repository = DeploymentPolicyRepository(session)
    replacement = DeploymentPolicyPauseUpdate(
        expected_revision=4,
        moves_paused=True,
    )

    paused = await repository.set_moves_paused(
        replacement,
        actor_user_id=uuid4(),
    )
    assert paused.revision == 5
    assert paused.moves_paused is True
    with pytest.raises(DeploymentPolicyConflict):
        await repository.set_moves_paused(replacement, actor_user_id=uuid4())


def test_limit_projection_applies_inline_ceiling_only_to_session_content() -> None:
    policy = _policy(
        target=StorageKind.POSTGRES_INLINE,
        session_file=101,
        session_image=100,
        knowledge_file=103,
        transcription_audio=104,
    )

    projections = project_upload_limits(
        policy,
        inline_maximum_bytes=100,
        object_store_maximum_bytes=None,
    )

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


def test_limit_projection_applies_portable_ceiling_to_object_store_sessions() -> None:
    projections = project_upload_limits(
        _policy(
            target=StorageKind.OBJECT_STORE,
            session_file=101,
            session_image=102,
            knowledge_file=103,
            transcription_audio=104,
        ),
        inline_maximum_bytes=1,
        object_store_maximum_bytes=100,
    )

    assert [projection.effective_bytes for projection in projections[:3]] == [
        100,
        100,
        100,
    ]
    assert all(
        projection.operator_ceiling_bytes == 100 for projection in projections[:3]
    )
    assert all(
        projection.constraining_source is ConstrainingSource.OPERATOR_CEILING
        for projection in projections[:3]
    )
    assert projections[0].storage_target is StorageKind.OBJECT_STORE
    assert projections[3].effective_bytes == 103
    assert projections[3].operator_ceiling_bytes is None
    assert projections[3].constraining_source is ConstrainingSource.ADMIN_POLICY
    assert projections[3].storage_target is None


def test_object_store_projection_without_capability_keeps_admin_policy_limits() -> None:
    projections = project_upload_limits(
        _policy(
            target=StorageKind.OBJECT_STORE,
            session_file=101,
            session_image=102,
            knowledge_file=103,
            transcription_audio=104,
        ),
        inline_maximum_bytes=1,
        object_store_maximum_bytes=None,
    )

    assert [projection.effective_bytes for projection in projections[:3]] == [
        101,
        102,
        104,
    ]
    assert all(
        projection.storage_target is StorageKind.OBJECT_STORE
        for projection in projections[:3]
    )
    assert all(
        projection.operator_ceiling_bytes is None for projection in projections[:3]
    )
    assert all(
        projection.constraining_source is ConstrainingSource.ADMIN_POLICY
        for projection in projections[:3]
    )


async def test_object_store_admission_snapshot_uses_portable_ceiling() -> None:
    policy = _policy(
        target=StorageKind.OBJECT_STORE,
        session_file=101,
        session_image=99,
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
        moves_paused=policy.moves_paused,
        updated_by_actor=policy.updated_by_actor.value,
        updated_by_user_id=policy.updated_by_user_id,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )

    snapshot = await load_upload_admission_snapshot(
        session,
        inline_maximum_bytes=1,
        object_store_maximum_bytes=100,
    )

    assert snapshot.session_storage_target is StorageKind.OBJECT_STORE
    assert snapshot.session_operator_ceiling_bytes == 100
    assert snapshot.session_file_maximum_bytes == 100
    assert snapshot.session_image_maximum_bytes == 99
    assert snapshot.session_audio_maximum_bytes == 100


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
        moves_paused=policy.moves_paused,
        updated_by_actor=policy.updated_by_actor.value,
        updated_by_user_id=policy.updated_by_user_id,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
    )

    snapshot = await load_upload_admission_snapshot(
        session,
        inline_maximum_bytes=100,
        object_store_maximum_bytes=None,
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
        moves_paused=False,
        updated_by_actor=PolicyActor.MIGRATION,
        updated_by_user_id=None,
        created_at=now,
        updated_at=now,
    )
