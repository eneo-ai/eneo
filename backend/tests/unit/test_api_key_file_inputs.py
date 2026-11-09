"""A chat capability must not turn the key owner's files into public inputs."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from eneo.analysis.analysis_service import AnalysisService
from eneo.apps.apps.app_service import AppService
from eneo.assistants.api.assistant_models import AssistantSparse
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
from eneo.files.file_models import File, FileMetadata, FileType
from eneo.files.file_service import FileService, require_requested_files
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.main.models import ModelId
from eneo.questions.question import Question
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


def _file(user: UserInDB) -> File:
    now = datetime.now(timezone.utc)
    return File(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        user_id=user.id,
        tenant_id=user.tenant_id,
        name="private-payroll.txt",
        checksum="test-checksum",
        size=22,
        mimetype="text/plain",
        file_type=FileType.TEXT,
        text="CONFIDENTIAL-PAYROLL-42",
    )


def _files(user: UserInDB, file: File) -> FileService:
    metadata = FileMetadata(
        id=file.id,
        created_at=file.created_at,
        updated_at=file.updated_at,
        user_id=user.id,
        tenant_id=user.tenant_id,
        name=file.name,
        mimetype=file.mimetype,
        file_type=file.file_type,
    )
    repo = AsyncMock()
    repo.session = Mock()
    repo.get_list_by_id_and_user.return_value = [metadata]
    service = FileService(user=user, repo=repo, protocol=Mock(), object_content=Mock())
    service._content_loader.load = AsyncMock(return_value={file.id: file})
    return service


@pytest.mark.parametrize("key_type", [ApiKeyType.PK, ApiKeyType.SK])
async def test_files_none_rejects_known_owner_id_before_content_read(key_type):
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user, key_type=key_type)
    file = _file(user)
    service = _files(user, file)

    with pytest.raises(UnauthorizedException) as denied:
        await service.get_files_by_ids([file.id])

    assert denied.value.code == "insufficient_resource_permission"
    assert denied.value.context["resource_type"] == "files"
    service.repo.get_list_by_id_and_user.assert_not_awaited()
    service._content_loader.load.assert_not_awaited()


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


def _history(user: UserInDB, session: SessionInDB) -> SessionService:
    repo = AsyncMock()
    repo.get.return_value = session
    repo.get_ownership.return_value = _ownership(session)
    repo.has_user_uploads.return_value = any(
        question.files for question in session.questions
    )
    return SessionService(session_repo=repo, question_repo=AsyncMock(), user=user)


def _ownership(session: SessionInDB) -> SessionOwnership:
    return SessionOwnership(
        user_id=session.user_id,
        api_key_id=session.api_key_id,
        widget_id=session.widget_id,
        visitor_id=session.visitor_id,
        assistant_id=session.assistant.id if session.assistant else None,
        group_chat_id=session.group_chat_id,
    )


def _previous_question(
    session: SessionInDB, user: UserInDB, *, generated: bool = False
) -> Question:
    file = _file(user)
    return Question(
        id=uuid4(),
        tenant_id=user.tenant_id,
        session_id=session.id,
        question="Read the attached document.",
        answer="Earlier answer.",
        num_tokens_question=5,
        num_tokens_answer=2,
        files=[] if generated else [file],
        generated_files=[file] if generated else [],
    )


async def test_history_read_requires_files_permission_for_previous_uploads():
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user)
    session = SessionInDB(id=uuid4(), user_id=user.id, name="Private chat")
    session.questions = [_previous_question(session, user)]

    history = _history(user, session)
    with pytest.raises(UnauthorizedException) as denied:
        await history.get_session_by_uuid(session.id)

    assert denied.value.code == "insufficient_resource_permission"
    history.session_repo.get.assert_not_awaited()


@pytest.mark.parametrize("operation", ["feedback", "rename"])
@pytest.mark.parametrize("allowed", [False, True])
async def test_history_returning_mutations_authorize_files_before_writing(
    operation: str, allowed: bool
):
    user = TEST_USER.model_copy()
    user.active_api_key = _key(
        user,
        ResourcePermissionLevel.READ if allowed else ResourcePermissionLevel.NONE,
    )
    session = SessionInDB(id=uuid4(), user_id=user.id, name="Private chat")
    session.questions = [_previous_question(session, user)]
    service = _history(user, session)
    service.session_repo.add_feedback.return_value = session
    service.session_repo.update.return_value = session

    async def mutate():
        if operation == "feedback":
            return await service.leave_feedback(session.id, SessionFeedback(value=1))
        return await service.update_session(
            SessionUpdate(id=session.id, name="New name")
        )

    if allowed:
        assert await mutate() is session
        if operation == "feedback":
            service.session_repo.add_feedback.assert_awaited_once()
        else:
            service.session_repo.update.assert_awaited_once()
    else:
        with pytest.raises(UnauthorizedException) as denied:
            await mutate()
        assert denied.value.code == "insufficient_resource_permission"
        service.session_repo.add_feedback.assert_not_awaited()
        service.session_repo.update.assert_not_awaited()


async def test_files_none_can_delete_using_ownership_without_reading_history():
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user)
    session = SessionInDB(id=uuid4(), user_id=user.id, name="Private chat")
    session.questions = [_previous_question(session, user)]
    service = _history(user, session)
    metadata = session.model_copy(update={"questions": []})
    service.session_repo.delete.return_value = metadata

    assert await service.delete(session.id) is metadata
    service.session_repo.delete.assert_awaited_once_with(session.id)
    service.session_repo.get.assert_not_awaited()
    service.session_repo.has_user_uploads.assert_not_awaited()


async def test_history_rechecks_uploads_linked_after_the_metadata_probe():
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user)
    session = SessionInDB(id=uuid4(), user_id=user.id, name="Private chat")
    session.questions = [_previous_question(session, user)]
    service = _history(user, session)
    service.session_repo.has_user_uploads.return_value = False

    with pytest.raises(UnauthorizedException) as denied:
        await service.get_session_by_uuid(session.id)

    assert denied.value.code == "insufficient_resource_permission"
    service.session_repo.get.assert_awaited_once()


async def test_unreadable_copy_keeps_its_existing_missing_history_error():
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user)
    session = SessionInDB(id=uuid4(), user_id=user.id, name="Removed copy")
    service = _history(user, session)
    service.session_repo.get.return_value = None

    with pytest.raises(NotFoundException, match="Session not found"):
        await service.get_session_by_uuid(session.id)


@pytest.mark.parametrize(
    "level", [ResourcePermissionLevel.NONE, ResourcePermissionLevel.READ]
)
@pytest.mark.parametrize("view", ["session", "first_questions", "all_questions"])
async def test_insight_history_requires_file_grant_without_changing_insight_ownership(
    view: str, level: ResourcePermissionLevel
):
    user = TEST_USER.model_copy()
    user.active_api_key = _key(user, level, key_type=ApiKeyType.SK)
    user.active_api_key.scope_type = ApiKeyScopeType.TENANT
    user.active_api_key.scope_id = None
    owner = user.model_copy(update={"id": uuid4(), "active_api_key": None})
    assistant = AssistantSparse(
        id=uuid4(), user_id=owner.id, name="Insights", type="assistant"
    )
    session = SessionInDB(
        id=uuid4(), user_id=owner.id, assistant=assistant, name="Another user's chat"
    )
    question = _previous_question(session, owner)
    # The public history projection includes transcription, unlike file text.
    question.files[0].transcription = "CONFIDENTIAL-AUDIO-42"
    session.questions = [question]
    repo = AsyncMock()
    repo.get_assistant_sessions_since.return_value = [session]
    sessions = AsyncMock()
    sessions.get.return_value = session
    sessions.get_ownership.return_value = _ownership(session)
    assistants = AsyncMock()
    assistants.get_assistant.return_value = (SimpleNamespace(space_id=uuid4()), [])
    service = AnalysisService(
        user=user,
        repo=repo,
        assistant_service=assistants,
        question_repo=AsyncMock(),
        session_repo=sessions,
        space_service=Mock(),
        session_service=_history(user, session),
        group_chat_service=Mock(),
        completion_service=Mock(),
    )
    service._check_insight_access = AsyncMock()
    service._check_assistant_question_access = AsyncMock()

    async def read():
        if view == "session":
            return await service.get_insight_session(session.id)
        return await service.get_questions_since(
            assistant.id,
            from_date=datetime.now(timezone.utc),
            to_date=datetime.now(timezone.utc),
            include_followups=view == "all_questions",
        )

    if level == ResourcePermissionLevel.NONE:
        with pytest.raises(UnauthorizedException) as denied:
            await read()
        assert denied.value.code == "insufficient_resource_permission"
    else:
        result = await read()
        assert result == (session if view == "session" else [question])
        assert question.files[0].transcription == "CONFIDENTIAL-AUDIO-42"


@pytest.mark.parametrize("session_login", [False, True])
async def test_permitted_history_still_reaches_the_model(
    turn: TurnFixture, session_login: bool
):
    turn.user.active_api_key = (
        None
        if session_login
        else _key(turn.user, ResourcePermissionLevel.READ, scope_id=turn.assistant.id)
    )
    turn.session.questions = [_previous_question(turn.session, turn.user)]
    history = _history(turn.user, turn.session)
    turn.history.get_session_by_uuid.side_effect = history.get_session_by_uuid

    await turn.service.ask(
        question="Continue", assistant_id=turn.assistant.id, session_id=turn.session.id
    )

    assert "CONFIDENTIAL-PAYROLL-42" in str(turn.requests[0]["messages"])


@pytest.mark.parametrize("generated", [False, True])
async def test_followup_cannot_replay_uploads_but_preserves_generated_outputs(
    turn: TurnFixture, generated: bool
):
    turn.user.active_api_key = _key(turn.user, scope_id=turn.assistant.id)
    turn.session.questions = [
        _previous_question(turn.session, turn.user, generated=generated)
    ]
    history = _history(turn.user, turn.session)
    # Keep the real session policy; only its repository and persistence are
    # replaced, just as in the ordinary completion fixture.
    turn.history.get_session_by_uuid.side_effect = history.get_session_by_uuid
    turn.service.file_service = _files(turn.user, _file(turn.user))
    turn.service.file_service.repo.get_list_by_id_and_user.return_value = []

    if generated:
        result = await turn.service.ask(
            question="Continue",
            assistant_id=turn.assistant.id,
            session_id=turn.session.id,
        )
        assert result.answer == "Check the policy."
        assert len(turn.requests) == 1
    else:
        with pytest.raises(UnauthorizedException) as denied:
            await turn.service.ask(
                question="Summarize the earlier upload",
                assistant_id=turn.assistant.id,
                session_id=turn.session.id,
            )
        assert denied.value.code == "insufficient_resource_permission"
        assert turn.requests == []
        turn.history.create_question_placeholder.assert_not_awaited()
        turn.history.complete_question_with_answer.assert_not_awaited()


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
    assert response.json()["context"]["auth_layer"] == "api_key_resource"
    assert "CONFIDENTIAL-PAYROLL-42" not in response.text
