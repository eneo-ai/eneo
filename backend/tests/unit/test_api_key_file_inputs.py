"""A chat capability must not turn the key owner's files into public inputs.

A user-owned API key acts as its owner. Its ``files`` grant decides two
things: whether a request may name uploads (refused without it), and whether
the uploads earlier turns attached travel with a conversation (left out
without it, so the key reads its conversations with no trace of them).
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from dependency_injector import providers
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from eneo.apps.app_runs.app_run_service import AppRunService
from eneo.apps.apps.app_service import AppService
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.outcome import Outcome
from eneo.authentication import api_key_resolver
from eneo.authentication.auth_models import (
    ApiKeyHashVersion,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
    ResourcePermissionLevel,
    ResourcePermissions,
)
from eneo.conversations.application.conversation_service import ConversationService
from eneo.files.file_content_loader import FileAttachmentGroup
from eneo.files.file_models import File, FileMetadata, FileType
from eneo.files.file_service import FileService, require_requested_files
from eneo.files.upload_access import may_read_user_uploads
from eneo.main.container.container import Container
from eneo.main.container.request_container import request_container
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.main.models import ModelId
from eneo.questions.question import Question, QuestionsFiles, ToolCallInfo
from eneo.server.exception_handlers import add_exception_handlers
from eneo.services.service_runner import ServiceRunner
from eneo.sessions.session import SessionFeedback, SessionInDB, SessionUpdate
from eneo.sessions.session_service import SessionService
from eneo.sessions.sessions_repo import SessionOwnership
from eneo.users.user import UserInDB
from tests.fixtures import TEST_USER
from tests.unit.assistants.test_assistant_turn_preparation import (
    TurnFixture,
)

pytest_plugins = ["tests.unit.assistants.test_assistant_turn_preparation"]


@pytest.fixture(autouse=True)
def resource_enforcement(monkeypatch: pytest.MonkeyPatch):
    settings = SimpleNamespace(api_key_enforce_resource_permissions=True)
    monkeypatch.setattr(api_key_resolver, "get_settings", lambda: settings)
    return settings


def _key(
    user: UserInDB,
    level: ResourcePermissionLevel | None = ResourcePermissionLevel.NONE,
    *,
    key_type: ApiKeyType = ApiKeyType.PK,
    scope_id: UUID | None = None,
) -> ApiKeyV2InDB:
    return ApiKeyV2InDB(
        id=uuid4(),
        tenant_id=user.tenant_id,
        owner_user_id=user.id,
        key_prefix=key_type.value,
        key_suffix="12345678",
        key_type=key_type,
        name="Embedded assistant",
        permission=(
            ApiKeyPermission(level.value)
            if level in {ResourcePermissionLevel.WRITE, ResourcePermissionLevel.ADMIN}
            else ApiKeyPermission.READ
        ),
        scope_type=ApiKeyScopeType.ASSISTANT,
        scope_id=scope_id or uuid4(),
        allowed_origins=["https://widget.example.test"],
        state=ApiKeyState.ACTIVE,
        resource_permissions=(
            ResourcePermissions(
                assistants=ResourcePermissionLevel.READ,
                conversations=ResourcePermissionLevel.READ,
                files=level,
            )
            if level is not None
            else None
        ),
        key_hash="test-only-hash",
        hash_version=ApiKeyHashVersion.HMAC_SHA256.value,
    )


def _file(
    user: UserInDB,
    name: str = "private-payroll.txt",
    text: str = "CONFIDENTIAL-PAYROLL-42",
) -> File:
    now = datetime.now(timezone.utc)
    return File(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        user_id=user.id,
        tenant_id=user.tenant_id,
        name=name,
        checksum="test-checksum",
        size=len(text),
        mimetype="text/plain",
        file_type=FileType.TEXT,
        text=text,
    )


def _metadata(file: File) -> FileMetadata:
    return FileMetadata(
        id=file.id,
        created_at=file.created_at,
        updated_at=file.updated_at,
        user_id=file.user_id,
        tenant_id=file.tenant_id,
        name=file.name,
        mimetype=file.mimetype,
        file_type=file.file_type,
    )


def _files(user: UserInDB, file: File) -> FileService:
    repo = AsyncMock()
    repo.session = Mock()
    repo.get_list_by_id_and_user.return_value = [_metadata(file)]
    service = FileService(
        user=user,
        repo=repo,
        protocol=Mock(),
        object_content=Mock(),
        audit_service=AsyncMock(),
    )
    service._content_loader.load = AsyncMock(return_value={file.id: file})
    return service


# --- Naming uploads in a request -----------------------------------------------


@pytest.mark.parametrize("key_type", [ApiKeyType.PK, ApiKeyType.SK])
async def test_files_none_rejects_known_owner_id_before_content_read(key_type):
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user, key_type=key_type)
    file = _file(user)
    service = _files(user, file)

    with pytest.raises(UnauthorizedException) as denied:
        await service.get_files_by_ids([file.id])

    assert denied.value.code == "insufficient_resource_permission"
    # What a route-level denial of the same code shows: never the held level.
    assert denied.value.context == {
        "resource_type": "files",
        "required_level": "read",
        "auth_layer": "api_key_resource",
        "action": "resource_permission_check",
    }
    service.repo.get_list_by_id_and_user.assert_not_awaited()
    service._content_loader.load.assert_not_awaited()
    service._audit_service.log_async.assert_awaited_once()
    logged = service._audit_service.log_async.await_args.kwargs
    assert logged["action"] is ActionType.API_KEY_AUTH_FAILED
    assert logged["outcome"] is Outcome.FAILURE
    assert logged["entity_id"] == user.active_api_key.id
    assert logged["metadata"]["extra"]["granted_level"] == "none"


@pytest.mark.parametrize(
    "level",
    [
        ResourcePermissionLevel.READ,
        ResourcePermissionLevel.WRITE,
        ResourcePermissionLevel.ADMIN,
        None,  # Simple keys retain the documented basic permission ceiling.
    ],
)
async def test_file_read_grants_preserve_owner_file_content(level):
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user, level, key_type=ApiKeyType.SK)
    file = _file(user)
    service = _files(user, file)

    assert await service.get_files_by_ids([file.id]) == [file]
    service.repo.get_list_by_id_and_user.assert_awaited_once_with(
        ids=[file.id], user_id=user.id
    )
    service._audit_service.log_async.assert_not_awaited()


@pytest.mark.parametrize("session_login", [False, True])
async def test_session_login_and_disabled_enforcement_preserve_file_access(
    session_login, resource_enforcement
):
    user = TEST_USER.model_copy()
    user.active_api_key = None if session_login else _key(user)
    resource_enforcement.api_key_enforce_resource_permissions = session_login
    file = _file(user)

    assert await _files(user, file).get_files_by_ids([file.id]) == [file]


async def test_empty_inputs_do_not_require_file_permission():
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user)
    service = _files(user, _file(user))
    service.repo.get_list_by_id_and_user.return_value = []

    assert await service.get_files_by_ids([]) == []


async def test_missing_or_foreign_file_keeps_existing_unavailable_error():
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user, ResourcePermissionLevel.READ)
    file = _file(user)
    service = _files(user, file)
    service.repo.get_list_by_id_and_user.return_value = []

    files = await service.get_files_by_ids([file.id])
    with pytest.raises(BadRequestException, match="Upload it again"):
        require_requested_files([file.id], files)


# --- Uploads earlier turns attached ---------------------------------------------


@pytest.mark.parametrize(
    ("login", "level", "enforced", "expected"),
    [
        ("session", None, True, True),
        ("key", ResourcePermissionLevel.NONE, True, False),
        ("key", ResourcePermissionLevel.READ, True, True),
        ("key", ResourcePermissionLevel.ADMIN, True, True),
        ("key", None, True, True),  # Simple key: the basic READ ceiling covers it.
        ("key", ResourcePermissionLevel.NONE, False, True),
    ],
)
def test_the_files_grant_decides_whether_uploads_are_readable(
    resource_enforcement, login, level, enforced, expected
):
    resource_enforcement.api_key_enforce_resource_permissions = enforced
    user = TEST_USER.model_copy()
    user.active_api_key = None if login == "session" else _key(user, level)

    assert may_read_user_uploads(user) is expected


@pytest.mark.parametrize("granted", [False, True])
def test_request_container_hydrates_conversations_by_the_principals_grant(granted):
    user = TEST_USER.model_copy()
    user.active_api_key = _key(
        user, ResourcePermissionLevel.READ if granted else ResourcePermissionLevel.NONE
    )
    container = _request_container(user, Mock())

    assert container.session_repo().include_user_uploads is granted
    assert container.question_repo().include_user_uploads is granted
    assert container.analysis_repo().include_user_uploads is granted
    assert container.app_run_repo().include_user_uploads is granted
    # The one derivation also reaches the repositories SessionService builds
    # for its own transactions.
    assert (
        container.session_service.kwargs["include_user_uploads"]
        is container.user_uploads_readable
    )


@pytest.mark.parametrize("granted", [False, True])
def test_session_service_write_repositories_follow_the_grant(granted):
    loader = Mock()
    service = SessionService(
        session_repo=AsyncMock(),
        question_repo=AsyncMock(),
        user=TEST_USER.model_copy(),
        file_content_loader_factory=lambda session: loader,
        include_user_uploads=granted,
    )

    for repo in (
        service._session_repository(Mock()),
        service._question_repository(Mock()),
    ):
        assert repo.include_user_uploads is granted
        assert repo.file_content_loader is loader


class _Loader:
    """Hydrates exactly the metadata it is asked for."""

    def __init__(self, files: Sequence[File]) -> None:
        self._files = {file.id: file for file in files}

    async def load_attachment_groups(
        self, groups: Sequence[FileAttachmentGroup], **_: object
    ) -> dict[tuple[str, UUID], list[File]]:
        return {
            group.key: [self._files[file.id] for file in group.files]
            for group in groups
        }


TOOL_READ = "TOOL-READ-PAYROLL-7"


def _request_container(user: UserInDB, loader: object) -> Container:
    container = request_container(
        session=providers.Object(AsyncMock()),
        user=providers.Object(user),
        tenant=providers.Object(user.tenant),
    )
    container.file_content_loader.override(providers.Object(loader))
    return container


@pytest.fixture
def hydrated(monkeypatch: pytest.MonkeyPatch):
    """Gives ``session`` an earlier turn, hydrated as a request by ``user``
    hydrates it: through the request container's own SessionRepository, with
    only the database lookups stubbed. The turn has one upload, one generated
    file, and a tool call that read the upload."""
    monkeypatch.setattr(
        "eneo.sessions.sessions_repo.InfoBlobRepository.hydrate_original_availability",
        AsyncMock(),
    )
    monkeypatch.setattr("eneo.sessions.sessions_repo.show_current_views", AsyncMock())

    async def hydrate(
        session: SessionInDB, user: UserInDB
    ) -> tuple[Question, File, File]:
        upload = _file(user)
        generated = _file(user, name="summary.txt", text="GENERATED-SUMMARY")
        question = Question(
            id=uuid4(),
            tenant_id=user.tenant_id,
            session_id=session.id,
            question="Read the attached document.",
            answer="Earlier answer.",
            num_tokens_question=5,
            num_tokens_answer=2,
            questions_files=[
                QuestionsFiles(type="user", file=_metadata(upload)),
                QuestionsFiles(type="assistant", file=_metadata(generated)),
            ],
            tool_calls=[
                ToolCallInfo(
                    server_name="files",
                    tool_name="read_file",
                    mcp_tool_name="files__read_file",
                    tool_call_id="read-upload",
                    arguments={
                        "url": f"https://eneo.test/api/v1/files/{upload.id}"
                        "/original/download?token=REDACTED"
                    },
                    result=f"File: {upload.name} (text/plain)\n\n{TOOL_READ}",
                )
            ],
        )
        session.questions = [question]
        repo = _request_container(user, _Loader([upload, generated])).session_repo()
        await repo._attach_turn_details([session])
        return question, upload, generated

    return hydrate


def _ownership(session: SessionInDB) -> SessionOwnership:
    return SessionOwnership(
        user_id=session.user_id,
        api_key_id=session.api_key_id,
        widget_id=session.widget_id,
        visitor_id=session.visitor_id,
        assistant_id=session.assistant.id if session.assistant else None,
        group_chat_id=session.group_chat_id,
    )


def _history(user: UserInDB, session: SessionInDB) -> SessionService:
    repo = AsyncMock()
    repo.get.return_value = session
    repo.get_ownership.return_value = _ownership(session)
    return SessionService(
        session_repo=repo,
        question_repo=AsyncMock(),
        user=user,
        include_user_uploads=may_read_user_uploads(user),
    )


async def test_history_without_the_grant_is_read_once_with_uploads_left_out(hydrated):
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user)
    session = SessionInDB(id=uuid4(), user_id=user.id, name="Private chat")
    _, upload, generated = await hydrated(session, user)
    history = _history(user, session)

    read = await history.get_session_by_uuid(session.id)

    assert read.questions[0].files == []
    assert read.questions[0].generated_files == [generated]
    assert upload.name not in read.model_dump_json()
    assert TOOL_READ not in read.model_dump_json()
    # The tool-result endpoint reads the same record.
    call = await history.get_tool_call_result(session=read, tool_call_id="read-upload")
    assert call is not None
    assert (call.arguments, call.result) == (None, None)
    history.session_repo.get.assert_awaited_once()
    history.session_repo.get_ownership.assert_not_awaited()


@pytest.mark.parametrize("operation", ["feedback", "rename"])
async def test_rename_and_feedback_stay_available_without_the_grant(
    hydrated, operation: str
):
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user)
    session = SessionInDB(id=uuid4(), user_id=user.id, name="Private chat")
    await hydrated(session, user)
    service = _history(user, session)
    service.session_repo.add_feedback.return_value = session
    service.session_repo.update.return_value = session

    if operation == "feedback":
        result = await service.leave_feedback(session.id, SessionFeedback(value=1))
        service.session_repo.add_feedback.assert_awaited_once()
    else:
        result = await service.update_session(
            SessionUpdate(id=session.id, name="New name")
        )
        service.session_repo.update.assert_awaited_once()

    assert result is session
    assert result.questions[0].files == []


async def test_files_none_can_delete_using_ownership_without_reading_history():
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user)
    session = SessionInDB(id=uuid4(), user_id=user.id, name="Private chat")
    service = _history(user, session)
    metadata = session.model_copy(update={"questions": []})
    service.session_repo.delete.return_value = metadata

    assert await service.delete(session.id) is metadata
    service.session_repo.delete.assert_awaited_once_with(session.id)
    service.session_repo.get.assert_not_awaited()


async def test_unreadable_copy_keeps_its_existing_missing_history_error():
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user)
    session = SessionInDB(id=uuid4(), user_id=user.id, name="Removed copy")
    service = _history(user, session)
    service.session_repo.get.return_value = None

    with pytest.raises(NotFoundException, match="Session not found"):
        await service.get_session_by_uuid(session.id)


@pytest.mark.parametrize("granted", [False, True])
async def test_history_reaches_the_model_only_with_the_files_grant(
    turn: TurnFixture, hydrated, granted: bool
):
    turn.user.active_api_key = _key(
        turn.user,
        ResourcePermissionLevel.READ if granted else ResourcePermissionLevel.NONE,
        scope_id=turn.assistant.id,
    )
    _, upload, _ = await hydrated(turn.session, turn.user)
    history = _history(turn.user, turn.session)
    turn.history.get_session_by_uuid.side_effect = history.get_session_by_uuid

    result = await turn.service.ask(
        question="Continue", assistant_id=turn.assistant.id, session_id=turn.session.id
    )

    assert result.answer == "Check the policy."
    assert len(turn.requests) == 1
    messages = str(turn.requests[0]["messages"])
    assert "Earlier answer." in messages
    assert (upload.text in messages) is granted
    # What an earlier turn's tool read out of the upload is replayed the same way.
    assert (TOOL_READ in messages) is granted


# --- Uploads named in the current request ----------------------------------------


@pytest.mark.parametrize("allowed", [False, True])
async def test_current_attachment_is_checked_before_inference_and_persistence(
    turn: TurnFixture, allowed: bool
):
    turn.user.active_api_key = _key(
        turn.user,
        ResourcePermissionLevel.READ if allowed else ResourcePermissionLevel.NONE,
        scope_id=turn.assistant.id,
    )
    file = _file(turn.user)
    turn.service.file_service = _files(turn.user, file)

    if allowed:
        await turn.service.ask(
            question="Read the upload",
            assistant_id=turn.assistant.id,
            file_ids=[file.id],
        )
        assert file.text in str(turn.requests[0]["messages"])
    else:
        with pytest.raises(UnauthorizedException) as denied:
            await turn.service.ask(
                question="Read the upload",
                assistant_id=turn.assistant.id,
                file_ids=[file.id],
            )
        assert denied.value.code == "insufficient_resource_permission"
        assert turn.requests == []
        assert turn.history.mock_calls == []


async def test_public_chat_keeps_configured_assistant_knowledge(turn: TurnFixture):
    turn.user.active_api_key = _key(turn.user, scope_id=turn.assistant.id)
    knowledge = _file(turn.user)
    turn.assistant.attachments = [knowledge]
    turn.service.file_service = _files(turn.user, knowledge)
    turn.service.file_service.repo.get_list_by_id_and_user.return_value = []

    result = await turn.service.ask(
        question="Use your knowledge", assistant_id=turn.assistant.id
    )

    assert result.answer == "Check the policy."
    assert knowledge.text in str(turn.requests[0]["messages"])


@pytest.mark.parametrize("editor_attachment", [False, True])
async def test_token_preflight_cannot_read_denied_files(
    turn: TurnFixture, editor_attachment: bool
):
    turn.user.active_api_key = _key(turn.user, scope_id=turn.assistant.id)
    file = _file(turn.user)
    files = _files(turn.user, file)
    service = ConversationService(
        assistant_service=turn.service,
        group_chat_service=Mock(),
        session_service=Mock(),
        completion_service=Mock(),
        space_service=Mock(),
        file_service=files,
    )
    service._resolve_preflight_model = AsyncMock(
        return_value=(turn.assistant.completion_model, 0, True)
    )

    with pytest.raises(UnauthorizedException) as denied:
        await service.preflight_tokens(
            question="Count this file",
            file_ids=[] if editor_attachment else [file.id],
            attachments=[(file.id, True)] if editor_attachment else None,
        )

    assert denied.value.code == "insufficient_resource_permission"
    files._content_loader.load.assert_not_awaited()


async def test_app_run_cannot_read_denied_input_before_execution():
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user)
    file = _file(user)
    app = Mock()
    app.run = AsyncMock()
    service = AppService.__new__(AppService)
    service.file_service = _files(user, file)
    service._get_runnable_app = AsyncMock(return_value=app)
    service._compose_app_prompt = AsyncMock()

    with pytest.raises(UnauthorizedException) as denied:
        await service.run_app(app_id=uuid4(), file_ids=[file.id], text="Read it")

    assert denied.value.code == "insufficient_resource_permission"
    app.run.assert_not_awaited()
    service.file_service._content_loader.load.assert_not_awaited()


async def test_queued_app_run_cannot_name_denied_files():
    """The worker later runs the app as the plain owner, so the key's grant
    has to be checked when the run is queued."""
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user)
    file = _file(user)
    files = _files(user, file)
    files.repo.get_by_ids.return_value = [_metadata(file)]
    jobs = AsyncMock()
    runs = AsyncMock()
    service = AppRunService(
        user=user,
        repo=runs,
        factory=Mock(),
        app_service=AsyncMock(),
        job_service=jobs,
        file_service=files,
    )

    with pytest.raises(UnauthorizedException) as denied:
        await service.queue_app_run(uuid4(), file_ids=[file.id], text="Read it")

    assert denied.value.code == "insufficient_resource_permission"
    files.repo.get_by_ids.assert_not_awaited()
    runs.add.assert_not_awaited()
    jobs.queue_job.assert_not_awaited()


async def test_service_run_cannot_read_denied_input_before_execution():
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user)
    file = _file(user)
    completion = AsyncMock()
    questions = AsyncMock()
    runner = ServiceRunner(
        user=user,
        service=Mock(groups=[]),
        completion_service=completion,
        file_service=_files(user, file),
        output_parser=Mock(),
        references_service=AsyncMock(),
        question_repo=questions,
        prompt="Use the provided input",
    )

    with pytest.raises(UnauthorizedException) as denied:
        await runner.run("Read it", file_ids=[ModelId(id=file.id)])

    assert denied.value.code == "insufficient_resource_permission"
    completion.get_response.assert_not_awaited()
    questions.add.assert_not_awaited()


async def test_denial_has_a_stable_403_api_response():
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user)
    file = _file(user)
    service = _files(user, file)
    app = FastAPI()
    add_exception_handlers(app)

    @app.post("/file-input")
    async def file_input():
        return await service.get_files_by_ids([file.id])

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/file-input")

    assert response.status_code == 403
    assert response.json()["code"] == "insufficient_resource_permission"
    assert response.json()["context"] == {
        "resource_type": "files",
        "required_level": "read",
        "auth_layer": "api_key_resource",
        "action": "resource_permission_check",
    }
    assert "CONFIDENTIAL-PAYROLL-42" not in response.text
