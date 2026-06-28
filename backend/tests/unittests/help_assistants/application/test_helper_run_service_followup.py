"""Unit tests for ``HelperRunService.continue_turn`` and ``set_status``.

Step 019 pins:

* ``continue_turn`` reuses the run's ``session_id``, persists a Question
  row via the same ``_persist_answer`` path as ``run()``, and hands back
  the resulting answer.
* ``continue_turn`` rejects a different user trying to drive a run that
  isn't theirs.
* ``continue_turn`` rejects when the admin disabled the role between
  turns — re-checks both ``is_enabled`` and ``is_visible_to_users``.
* ``set_status`` only allows transitions from ``IN_PROGRESS``.
* ``set_status(COMPLETED)`` fills ``completed_at``.

All collaborators are mocked: the goal is to exercise the service's
authorization, sequencing, and state-machine logic, not the I/O of
``CompletionService`` / ``ReferencesService`` (those are exercised by
the step-018 integration test).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
)
from eneo.help_assistants.application.helper_run_service import HelperRunService
from eneo.help_assistants.domain.factory import HelperAssistantsFactory
from eneo.help_assistants.domain.helper_kind import HelperKind
from eneo.help_assistants.domain.helper_run import HelperRun
from eneo.help_assistants.domain.helper_run_status import HelperRunStatus
from eneo.help_assistants.domain.role_assignment import RoleAssignment
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleInDB
from eneo.services.service import DatastoreResult
from eneo.sessions.session import SessionInDB
from eneo.tenants.tenant import TenantInDB
from eneo.users.user import UserInDB

_TENANT = TenantInDB(id=uuid4(), name="acme", quota_limit=1024**3)


def _make_user(*, user_id: UUID | None = None) -> UserInDB:
    role = RoleInDB(
        id=uuid4(),
        name="test_role",
        permissions=[Permission.ASSISTANTS],
        tenant_id=_TENANT.id,
    )
    return UserInDB(
        id=user_id or uuid4(),
        username="tester",
        email="tester@example.com",
        salt=None,
        password=None,
        used_tokens=0,
        tenant_id=_TENANT.id,
        tenant=_TENANT,
        roles=[role],
        state="active",
    )


def _make_run(
    *,
    actor_user_id: UUID,
    session_id: UUID | None = None,
    assistant_id: UUID | None = None,
    status: HelperRunStatus = HelperRunStatus.IN_PROGRESS,
) -> HelperRun:
    return HelperRun(
        id=uuid4(),
        tenant_id=_TENANT.id,
        org_space_id=uuid4(),
        kind=HelperKind.PROMPT_GUIDE,
        assistant_id=assistant_id or uuid4(),
        target_type="assistant",
        target_id=uuid4(),
        session_id=session_id or uuid4(),
        actor_user_id=actor_user_id,
        status=status,
    )


def _make_role(
    *,
    assistant_id: UUID,
    is_enabled: bool = True,
    is_visible_to_users: bool = True,
) -> RoleAssignment:
    return RoleAssignment(
        id=uuid4(),
        org_space_id=uuid4(),
        kind=HelperKind.PROMPT_GUIDE,
        assistant_id=assistant_id,
        is_enabled=is_enabled,
        is_visible_to_users=is_visible_to_users,
    )


def _mock_helper_assistant(*, assistant_id: UUID) -> MagicMock:
    """Build a MagicMock that walks like ``Assistant`` for the run path.

    The fields touched are exactly the ones HelperRunService reads when
    building the completion call. Everything that contributes to context
    is empty so the test stays focused on orchestration.
    """
    completion_model = MagicMock()
    completion_model.id = uuid4()
    completion_model.can_access = True

    assistant = MagicMock()
    assistant.id = assistant_id
    assistant.completion_model = completion_model
    assistant.completion_model_kwargs = MagicMock()
    assistant.attachments = []
    assistant.collections = []
    assistant.websites = []
    assistant.integration_knowledge_list = []
    assistant.mcp_servers = []
    assistant.has_knowledge = MagicMock(return_value=False)
    assistant.get_prompt_text = MagicMock(return_value="HELPER_PROMPT")
    return assistant


def _build_session(*, session_id: UUID, name: str = "Helper session") -> SessionInDB:
    """Construct a real ``SessionInDB`` so Pydantic accepts the response.

    ``HelperRunResponse.session`` is strictly typed; a MagicMock wouldn't
    survive Pydantic validation. Defaults keep the empty-questions case
    (first follow-up against a fresh helper run).
    """
    return SessionInDB(id=session_id, name=name)


def _make_completion_response(
    *, text: str = "Helper says hi.", model_id: UUID | None = None
) -> CompletionModelResponse:
    """Build a CompletionModelResponse without revalidating the model field.

    The ``model: CompletionModel`` field is a strict-typed Pydantic v2
    submodel — passing a MagicMock through normal validation explodes on
    ~14 missing fields. ``model_construct`` skips validators, which is
    fine here because the service only reads ``.completion``, ``.usage``,
    and ``.total_token_count`` off the response.
    """
    completion_model = MagicMock()
    completion_model.id = model_id or uuid4()
    return CompletionModelResponse.model_construct(
        completion=Completion(text=text),
        model=completion_model,
        extended_logging=None,
        total_token_count=10,
        usage=None,
    )


def _build_service(
    *,
    user: UserInDB,
    helper_run_repo: AsyncMock | None = None,
    role_service: AsyncMock | None = None,
    assistant_service: AsyncMock | None = None,
    session_repo: AsyncMock | None = None,
    question_repo: AsyncMock | None = None,
    completion_service: AsyncMock | None = None,
    references_service: AsyncMock | None = None,
    audit_service: AsyncMock | None = None,
) -> tuple[HelperRunService, dict[str, AsyncMock]]:
    helper_run_repo = helper_run_repo or AsyncMock()
    role_service = role_service or AsyncMock()
    assistant_service = assistant_service or AsyncMock()
    session_repo = session_repo or AsyncMock()
    question_repo = question_repo or AsyncMock()
    completion_service = completion_service or AsyncMock()
    references_service = references_service or AsyncMock()
    audit_service = audit_service or AsyncMock()

    service = HelperRunService(
        user=user,
        helper_run_repo=helper_run_repo,
        role_service=role_service,
        assistant_service=assistant_service,
        session_repo=session_repo,
        question_repo=question_repo,
        completion_service=completion_service,
        references_service=references_service,
        factory=HelperAssistantsFactory(),
        audit_service=audit_service,
    )
    return service, {
        "helper_run_repo": helper_run_repo,
        "role_service": role_service,
        "assistant_service": assistant_service,
        "session_repo": session_repo,
        "question_repo": question_repo,
        "completion_service": completion_service,
        "references_service": references_service,
        "audit_service": audit_service,
    }


@pytest.mark.asyncio
async def test_continue_turn_reuses_session_and_persists_question():
    user = _make_user()
    assistant_id = uuid4()
    session_id = uuid4()
    run = _make_run(
        actor_user_id=user.id,
        session_id=session_id,
        assistant_id=assistant_id,
    )
    role = _make_role(assistant_id=assistant_id)
    helper_assistant = _mock_helper_assistant(assistant_id=assistant_id)
    session = _build_session(session_id=session_id)

    helper_run_repo = AsyncMock()
    helper_run_repo.get_by_id.return_value = run

    role_service = AsyncMock()
    role_service.get_active.return_value = role

    assistant_service = AsyncMock()
    # continue_turn loads the helper via the privileged get_help_assistant
    # (step 099): the helper lives in the org-space, so a non-admin actor
    # would 403 through the permission-enforcing get_assistant. It returns the
    # assistant directly, not the (assistant, permissions) tuple.
    assistant_service.get_help_assistant.return_value = helper_assistant

    session_repo = AsyncMock()
    session_repo.get_for_helper_run.return_value = session

    references_service = AsyncMock()
    references_service.get_references.return_value = DatastoreResult(
        chunks=[], no_duplicate_chunks=[], info_blobs=[]
    )

    completion_service = AsyncMock()
    completion_service.get_response.return_value = _make_completion_response(
        text="Follow-up answer.",
        model_id=helper_assistant.completion_model.id,
    )

    question_repo = AsyncMock()

    service, mocks = _build_service(
        user=user,
        helper_run_repo=helper_run_repo,
        role_service=role_service,
        assistant_service=assistant_service,
        session_repo=session_repo,
        question_repo=question_repo,
        completion_service=completion_service,
        references_service=references_service,
    )

    result = await service.continue_turn(
        run_id=run.id, question="What about edge cases?"
    )

    # Session was reused, not created anew.
    session_repo.get_for_helper_run.assert_awaited_once_with(session_id, user.tenant_id)
    session_repo.add.assert_not_awaited()
    assert result.session is session
    assert result.run is run

    # A new Question row was persisted under the existing session_id.
    question_repo.add.assert_awaited_once()
    persisted_question = question_repo.add.await_args.args[0]
    assert persisted_question.session_id == session_id
    assert persisted_question.tenant_id == user.tenant_id
    assert persisted_question.question == "What about edge cases?"
    assert persisted_question.answer == "Follow-up answer."
    # extended_logging never produced a LoggingDetails block.
    assert persisted_question.logging_details is None
    assert persisted_question.assistant_id == helper_assistant.id

    # Completion call carried extended_logging=False regardless of the
    # helper assistant's stored ``logging_enabled`` (mocked).
    completion_call = mocks["completion_service"].get_response.await_args.kwargs
    assert completion_call["extended_logging"] is False
    assert completion_call["session"] is session

    # Status was NOT mutated — continue_turn keeps the run IN_PROGRESS.
    mocks["helper_run_repo"].update_status.assert_not_awaited()
    assert result.answer == "Follow-up answer."


@pytest.mark.asyncio
async def test_continue_turn_rejects_different_user():
    actor = _make_user()
    other_user = _make_user()
    run = _make_run(actor_user_id=actor.id)

    helper_run_repo = AsyncMock()
    helper_run_repo.get_by_id.return_value = run

    service, mocks = _build_service(user=other_user, helper_run_repo=helper_run_repo)

    with pytest.raises(UnauthorizedException):
        await service.continue_turn(run_id=run.id, question="hi")

    # No downstream calls happened — the guard short-circuited before
    # the role / model / session lookups.
    mocks["role_service"].get_active.assert_not_awaited()
    mocks["session_repo"].get_for_helper_run.assert_not_awaited()
    mocks["completion_service"].get_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_continue_turn_rejects_missing_run():
    user = _make_user()
    helper_run_repo = AsyncMock()
    helper_run_repo.get_by_id.return_value = None

    service, mocks = _build_service(user=user, helper_run_repo=helper_run_repo)

    with pytest.raises(NotFoundException):
        await service.continue_turn(run_id=uuid4(), question="hi")

    mocks["role_service"].get_active.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role_state",
    [
        "disabled",
        "invisible",
        "unassigned",
    ],
)
async def test_continue_turn_rejects_when_role_changed_mid_conversation(
    role_state: str,
):
    user = _make_user()
    assistant_id = uuid4()
    run = _make_run(actor_user_id=user.id, assistant_id=assistant_id)

    helper_run_repo = AsyncMock()
    helper_run_repo.get_by_id.return_value = run

    role_service = AsyncMock()
    if role_state == "unassigned":
        role_service.get_active.return_value = None
    elif role_state == "disabled":
        role_service.get_active.return_value = _make_role(
            assistant_id=assistant_id, is_enabled=False
        )
    else:
        role_service.get_active.return_value = _make_role(
            assistant_id=assistant_id, is_visible_to_users=False
        )

    service, mocks = _build_service(
        user=user,
        helper_run_repo=helper_run_repo,
        role_service=role_service,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.continue_turn(run_id=run.id, question="hi")

    assert exc_info.value.code == "helper_not_available"
    mocks["assistant_service"].get_assistant.assert_not_awaited()
    mocks["session_repo"].get_for_helper_run.assert_not_awaited()
    mocks["completion_service"].get_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_status_only_allows_transitions_from_in_progress():
    user = _make_user()
    run = _make_run(actor_user_id=user.id, status=HelperRunStatus.COMPLETED)

    helper_run_repo = AsyncMock()
    helper_run_repo.get_by_id.return_value = run

    service, _ = _build_service(user=user, helper_run_repo=helper_run_repo)

    with pytest.raises(BadRequestException, match="IN_PROGRESS"):
        await service.set_status(run_id=run.id, status=HelperRunStatus.ABANDONED)

    helper_run_repo.update_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_status_rejects_in_progress_target():
    user = _make_user()
    run = _make_run(actor_user_id=user.id)

    helper_run_repo = AsyncMock()
    helper_run_repo.get_by_id.return_value = run

    service, _ = _build_service(user=user, helper_run_repo=helper_run_repo)

    with pytest.raises(BadRequestException, match="terminal"):
        await service.set_status(run_id=run.id, status=HelperRunStatus.IN_PROGRESS)

    helper_run_repo.update_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_status_rejects_different_user():
    actor = _make_user()
    other_user = _make_user()
    run = _make_run(actor_user_id=actor.id)

    helper_run_repo = AsyncMock()
    helper_run_repo.get_by_id.return_value = run

    service, _ = _build_service(user=other_user, helper_run_repo=helper_run_repo)

    with pytest.raises(UnauthorizedException):
        await service.set_status(run_id=run.id, status=HelperRunStatus.COMPLETED)

    helper_run_repo.update_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_status_completed_fills_completed_at():
    user = _make_user()
    run = _make_run(actor_user_id=user.id)

    helper_run_repo = AsyncMock()
    helper_run_repo.get_by_id.return_value = run

    # update_status returns the post-update entity. We don't care what
    # ``completed_at`` ends up on the returned object — we assert the repo
    # call shape, which is what HelperRunService actually drives.
    helper_run_repo.update_status.return_value = run

    service, _ = _build_service(user=user, helper_run_repo=helper_run_repo)

    await service.set_status(run_id=run.id, status=HelperRunStatus.COMPLETED)

    helper_run_repo.update_status.assert_awaited_once()
    call_kwargs = helper_run_repo.update_status.await_args.kwargs
    assert call_kwargs["id"] == run.id
    assert call_kwargs["tenant_id"] == user.tenant_id
    assert call_kwargs["status"] == HelperRunStatus.COMPLETED
    # The repo's ``update_status`` signature takes the timestamp as a
    # positional concept but the service passes it as ``completed_at`` —
    # what matters here is that it is non-None (the service computed it
    # rather than letting NULL slip through).
    assert call_kwargs["completed_at"] is not None


@pytest.mark.parametrize(
    "terminal_status",
    [
        HelperRunStatus.COMPLETED,
        HelperRunStatus.ABANDONED,
        HelperRunStatus.FAILED,
    ],
)
@pytest.mark.asyncio
async def test_set_status_accepts_all_terminal_statuses(
    terminal_status: HelperRunStatus,
):
    user = _make_user()
    run = _make_run(actor_user_id=user.id)

    helper_run_repo = AsyncMock()
    helper_run_repo.get_by_id.return_value = run
    helper_run_repo.update_status.return_value = run

    service, _ = _build_service(user=user, helper_run_repo=helper_run_repo)

    await service.set_status(run_id=run.id, status=terminal_status)

    helper_run_repo.update_status.assert_awaited_once()
    assert helper_run_repo.update_status.await_args.kwargs["status"] == terminal_status
