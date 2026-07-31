from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from eneo.authentication.auth_dependencies import require_user_for_creation
from eneo.groups_legacy.api import group_router
from eneo.jobs.task_service import TaskService
from eneo.main.exceptions import ErrorCodes
from eneo.object_content.content import ObjectContentUnavailableError, StorageKind
from eneo.object_content.deployment_policy import UploadAdmissionSnapshot
from eneo.server.exception_handlers import add_exception_handlers
from tests.fixtures import TEST_USER


def _upload_app(task_service: TaskService) -> FastAPI:
    space_id = uuid4()

    class GroupService:
        @staticmethod
        async def get_group(_group_id):
            return SimpleNamespace(
                name="Upload contract collection",
                space_id=None,
            )

        @staticmethod
        async def add_file_to_group(
            group_id,
            file,
            mimetype,
            filename,
        ):
            return await task_service.queue_upload_file(
                group_id=group_id,
                space_id=space_id,
                file=file,
                mimetype=mimetype,
                filename=filename,
            )

    class Container:
        @staticmethod
        def group_service():
            return GroupService()

        @staticmethod
        def user():
            return TEST_USER

    route = next(
        route
        for route in group_router.router.routes
        if isinstance(route, APIRoute) and route.endpoint is group_router.upload_file
    )
    container_dependency = next(
        dependency
        for dependency in route.dependant.dependencies
        if dependency.name == "container"
    )
    app = FastAPI()
    add_exception_handlers(app)
    app.include_router(group_router.router)
    app.dependency_overrides[container_dependency.call] = Container
    app.dependency_overrides[require_user_for_creation] = lambda: None
    return app


def test_upload_rejects_invalid_filename_before_staging_or_job_creation(
    monkeypatch,
) -> None:
    file_size_service = MagicMock()
    job_service = AsyncMock()
    object_content = AsyncMock()
    staging = AsyncMock()
    monkeypatch.setattr(
        "eneo.jobs.task_service.stage_job_file",
        staging,
    )
    task_service = TaskService(
        user=TEST_USER,
        file_size_service=file_size_service,
        job_service=job_service,
        object_content=object_content,
        upload_admission=UploadAdmissionSnapshot(
            policy_revision=7,
            new_write_storage_target=StorageKind.POSTGRES_INLINE,
            session_file_maximum_bytes=1024,
            session_image_maximum_bytes=1024,
            session_audio_maximum_bytes=1024,
            knowledge_file_maximum_bytes=1024,
            knowledge_audio_maximum_bytes=1024,
        ),
    )

    app = _upload_app(task_service)
    group_id = uuid4()
    response = TestClient(app, raise_server_exceptions=False).post(
        f"/{group_id}/info-blobs/upload/",
        files={"file": ("   ", b"payload", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["eneo_error_code"] == ErrorCodes.INVALID_FILENAME
    assert (
        "400" in app.openapi()["paths"]["/{id}/info-blobs/upload/"]["post"]["responses"]
    )
    staging.assert_not_awaited()
    job_service.queue_durable_knowledge_job.assert_not_awaited()
    object_content.ensure_target_ready.assert_not_awaited()
    file_size_service.get_file_size.assert_not_called()


def test_upload_reports_unavailable_storage_before_staging_or_job_creation(
    monkeypatch,
) -> None:
    file_size_service = MagicMock()
    file_size_service.get_file_size.return_value = 7
    job_service = AsyncMock()
    object_content = AsyncMock()
    object_content.ensure_target_ready.side_effect = ObjectContentUnavailableError(
        "injected object-store outage"
    )
    staging = AsyncMock()
    monkeypatch.setattr(
        "eneo.jobs.task_service.stage_job_file",
        staging,
    )
    task_service = TaskService(
        user=TEST_USER,
        file_size_service=file_size_service,
        job_service=job_service,
        object_content=object_content,
        upload_admission=UploadAdmissionSnapshot(
            policy_revision=7,
            new_write_storage_target=StorageKind.OBJECT_STORE,
            session_file_maximum_bytes=1024,
            session_image_maximum_bytes=1024,
            session_audio_maximum_bytes=1024,
            knowledge_file_maximum_bytes=1024,
            knowledge_audio_maximum_bytes=1024,
        ),
    )

    app = _upload_app(task_service)
    response = TestClient(app, raise_server_exceptions=False).post(
        f"/{uuid4()}/info-blobs/upload/",
        files={"file": ("source.txt", b"payload", "text/plain")},
    )

    assert response.status_code == 503
    assert response.json()["eneo_error_code"] == ErrorCodes.RESOURCE_NOT_READY
    assert (
        "503" in app.openapi()["paths"]["/{id}/info-blobs/upload/"]["post"]["responses"]
    )
    staging.assert_not_awaited()
    job_service.queue_durable_knowledge_job.assert_not_awaited()
    object_content.ensure_target_ready.assert_awaited_once_with(
        StorageKind.OBJECT_STORE
    )
