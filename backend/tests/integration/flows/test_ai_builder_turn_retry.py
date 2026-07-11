from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from time import monotonic
from typing import IO, NoReturn
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from pydantic import BaseModel, ConfigDict, Field

from eneo.database.tables.spaces_table import SpacesCompletionModels
from eneo.flows.ai_builder.ai_builder_api_models import (
    SendMessageRequest,
    SessionResponse,
)
from eneo.flows.ai_builder.ai_builder_conversation_compaction import (
    MAX_SESSION_MESSAGES,
)
from eneo.flows.ai_builder.ai_builder_domain_models import BuilderTurnState
from eneo.main.config import Settings
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserUpdate
from tests.integration.flows.conftest import _flow_worker_environment

_CHILD_ARGUMENT = "--ai-builder-turn-retry-child"
_HARD_EXIT_CODE = 86
_LEASE_SECONDS = 30
_PROCESS_DEADLINE_SECONDS = 20.0
_RECOVERY_DEADLINE_SECONDS = 45.0
_POLL_INTERVAL_SECONDS = 0.1
_COMPACTION_SETUP_TURNS = (MAX_SESSION_MESSAGES // 2) + 1


class _CrashMode(StrEnum):
    BEFORE_PROVIDER = "before_provider"
    AFTER_PROVIDER_RETURN = "after_provider_return"
    AFTER_COMMIT = "after_commit"


class _ChildCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: _CrashMode
    token: str = Field(repr=False)
    session_id: UUID
    request: SendMessageRequest
    marker_path: Path


class _PublicError(BaseModel):
    code: str


@dataclass(slots=True, repr=False)
class _BuilderTurnChild:
    process: subprocess.Popen[str]
    log_file: IO[str]
    log_path: Path

    async def require_hard_exit(self) -> None:
        try:
            return_code = await asyncio.to_thread(
                self.process.wait,
                timeout=_PROCESS_DEADLINE_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise AssertionError(
                "AI Builder process-test child did not reach its hard-exit checkpoint. "
                f"Log tail:\n{self.log_tail()}"
            ) from error
        if return_code != _HARD_EXIT_CODE:
            raise AssertionError(
                "AI Builder process-test child exited at the wrong boundary "
                f"(exit code {return_code}). Log tail:\n{self.log_tail()}"
            )

    async def close(self) -> None:
        try:
            if self.process.poll() is None:
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    await asyncio.to_thread(self.process.wait, timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    await asyncio.to_thread(self.process.wait, timeout=3)
        except ProcessLookupError:
            await asyncio.to_thread(self.process.wait, timeout=3)
        finally:
            self.log_file.close()

    def log_tail(self) -> str:
        if not self.log_path.exists():
            return "<no child log>"
        lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-30:])


@pytest.fixture
async def bearer_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"ai-builder-turn-retry-{uuid4().hex[:8]}",
                permissions=[
                    Permission.ASSISTANTS,
                    Permission.SHARED_SPACES,
                    Permission.FLOWS_MANAGE,
                    Permission.FLOWS_AI_BUILDER,
                ],
                tenant_id=admin_user.tenant_id,
            )
        )
        user = await container.user_repo().update(
            UserUpdate(id=admin_user.id, roles=[ModelId(id=role.id)])
        )
        assert user is not None
        return container.auth_service().create_access_token_for_user(user)


def _make_llm_response() -> MagicMock:
    message = MagicMock()
    message.content = "Jag kan hjälpa dig bygga flödet."
    message.tool_calls = None
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _record_marker(marker_path: Path, marker: str) -> None:
    with marker_path.open("a", encoding="utf-8") as marker_file:
        marker_file.write(f"{marker}\n")
        marker_file.flush()
        os.fsync(marker_file.fileno())


def _markers(marker_path: Path) -> tuple[str, ...]:
    if not marker_path.exists():
        return ()
    return tuple(marker_path.read_text(encoding="utf-8").splitlines())


def _marker_count(marker_path: Path, marker: str) -> int:
    return sum(value == marker for value in _markers(marker_path))


def _hard_exit(marker_path: Path, marker: str) -> NoReturn:
    _record_marker(marker_path, marker)
    os._exit(_HARD_EXIT_CODE)


async def _deterministic_completion(
    *, marker_path: Path, marker: str, **_kwargs: object
) -> MagicMock:
    _record_marker(marker_path, marker)
    return _make_llm_response()


@contextmanager
def _deterministic_provider(*, marker_path: Path, marker: str) -> Iterator[None]:
    async def completion(**kwargs: object) -> MagicMock:
        return await _deterministic_completion(
            marker_path=marker_path,
            marker=marker,
            **kwargs,
        )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
            new=AsyncMock(side_effect=completion),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_router._resolve_litellm_params",
            new=AsyncMock(
                return_value=("openai/gpt-4o-mini", {"api_key": "test-only"})
            ),
        ),
    ):
        yield


@contextmanager
def _provider_must_not_run() -> Iterator[None]:
    async def fail_provider(**_kwargs: object) -> NoReturn:
        raise AssertionError("A committed/conflicting turn reached the provider.")

    with patch(
        "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
        new=AsyncMock(side_effect=fail_provider),
    ):
        yield


async def _create_space_with_model(
    *,
    client: AsyncClient,
    bearer_token: str,
    db_container,
    completion_model_factory,
) -> str:
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"AI Builder process retry {uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 201, response.text
    space_id = response.json()["id"]
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session,
            "gpt-4o-mini",
            litellm_model_name="openai/gpt-4o-mini",
        )
        session.add(
            SpacesCompletionModels(
                space_id=UUID(space_id),
                completion_model_id=model.id,
            )
        )
        await session.flush()
    return space_id


async def _create_session(
    *, client: AsyncClient, bearer_token: str, space_id: str
) -> str:
    response = await client.post(
        "/api/v1/flows/ai-builder/sessions",
        json={"target_kind": "create", "space_id": space_id},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["session_id"]


async def _upload_reference_file(*, client: AsyncClient, bearer_token: str) -> str:
    response = await client.post(
        "/api/v1/files/",
        files={
            "upload_file": (
                "process-retry-reference.txt",
                b"durable reference material",
                "text/plain",
            )
        },
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


async def _send_message(
    *,
    client: AsyncClient,
    bearer_token: str,
    session_id: str,
    request: SendMessageRequest,
) -> Response:
    return await client.post(
        f"/api/v1/flows/ai-builder/sessions/{session_id}/messages",
        json=request.model_dump(mode="json"),
        headers={
            "Authorization": f"Bearer {bearer_token}",
            "accept": "text/event-stream",
        },
    )


async def _load_session(
    *, client: AsyncClient, bearer_token: str, session_id: str
) -> SessionResponse:
    response = await client.get(
        f"/api/v1/flows/ai-builder/sessions/{session_id}",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 200, response.text
    return SessionResponse.model_validate_json(response.content)


def _latest_turn(session: SessionResponse):
    latest_turn = session.latest_turn
    assert latest_turn is not None
    return latest_turn


def _event_names(response: Response) -> tuple[str, ...]:
    return tuple(
        line[6:].strip()
        for line in response.text.splitlines()
        if line.startswith("event:")
    )


async def _wait_for_turn_state(
    *,
    client: AsyncClient,
    bearer_token: str,
    session_id: str,
    expected_state: BuilderTurnState,
) -> SessionResponse:
    deadline = monotonic() + _RECOVERY_DEADLINE_SECONDS
    last_state: object = None
    while monotonic() < deadline:
        session = await _load_session(
            client=client,
            bearer_token=bearer_token,
            session_id=session_id,
        )
        last_state = _latest_turn(session).state
        if last_state == expected_state:
            return session
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    raise AssertionError(
        f"Session {session_id} did not reach {expected_state!r}; "
        f"last public state was {last_state!r}."
    )


def _child_environment(*, test_settings: Settings) -> dict[str, str]:
    environment = _flow_worker_environment(
        settings=test_settings,
        queue_name=test_settings.flow_celery_queue,
    )
    environment["TESTING"] = "true" if test_settings.testing else "false"
    environment["AI_BUILDER_SEND_LOCK_LEASE_SECONDS"] = str(_LEASE_SECONDS)
    return environment


def _start_child(
    *,
    command: _ChildCommand,
    test_settings: Settings,
    log_path: Path,
) -> _BuilderTurnChild:
    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.integration.flows.test_ai_builder_turn_retry",
            _CHILD_ARGUMENT,
        ],
        cwd=Path(__file__).resolve().parents[3],
        env=_child_environment(test_settings=test_settings),
        stdin=subprocess.PIPE,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    if process.stdin is None:
        process.terminate()
        log_file.close()
        raise AssertionError("AI Builder process-test child did not open stdin.")
    process.stdin.write(command.model_dump_json())
    process.stdin.close()
    return _BuilderTurnChild(process=process, log_file=log_file, log_path=log_path)


@asynccontextmanager
async def _child_process(
    *,
    command: _ChildCommand,
    test_settings: Settings,
    log_path: Path,
) -> AsyncIterator[_BuilderTurnChild]:
    child = _start_child(
        command=command,
        test_settings=test_settings,
        log_path=log_path,
    )
    try:
        yield child
    finally:
        await child.close()


async def _prefill_conversation_through_public_api(
    *,
    client: AsyncClient,
    bearer_token: str,
    session_id: str,
    marker_path: Path,
) -> None:
    with _deterministic_provider(marker_path=marker_path, marker="setup_provider"):
        for index in range(_COMPACTION_SETUP_TURNS):
            response = await _send_message(
                client=client,
                bearer_token=bearer_token,
                session_id=session_id,
                request=SendMessageRequest(
                    client_turn_id=uuid4(),
                    message=f"Compaction setup turn {index}.",
                    ui_language="en",
                ),
            )
            assert response.status_code == 200, response.text
            assert "done" in _event_names(response)


def _assert_one_accepted_user_message(
    *, session: SessionResponse, expected_content: str
) -> None:
    latest_turn = _latest_turn(session)
    message_id = str(latest_turn.user_message_id)
    matching_messages = [
        message for message in session.conversation if message.message_id == message_id
    ]
    assert len(matching_messages) == 1
    assert matching_messages[0].role == "user"
    assert matching_messages[0].content == expected_content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ai_builder_turn_retry_survives_hard_process_failures(
    client: AsyncClient,
    bearer_token: str,
    completion_model_factory,
    db_container,
    test_settings: Settings,
    tmp_path: Path,
) -> None:
    marker_path = tmp_path / "provider-markers.txt"
    space_id = await _create_space_with_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
    )
    before_provider_session = await _create_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
    )
    unknown_session = await _create_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
    )
    committed_session = await _create_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
    )
    await _prefill_conversation_through_public_api(
        client=client,
        bearer_token=bearer_token,
        session_id=before_provider_session,
        marker_path=marker_path,
    )
    file_id = await _upload_reference_file(
        client=client,
        bearer_token=bearer_token,
    )

    before_provider_request = SendMessageRequest(
        client_turn_id=uuid4(),
        message="Use the attached durable reference after recovery.",
        file_ids=[UUID(file_id)],
        ui_language="en",
    )
    unknown_request = SendMessageRequest(
        client_turn_id=uuid4(),
        message="Build a deterministic flow after explicit recovery.",
        ui_language="en",
    )
    committed_request = SendMessageRequest(
        client_turn_id=uuid4(),
        message="Commit this turn before the response is delivered.",
        ui_language="en",
    )

    commands = (
        (
            _ChildCommand(
                mode=_CrashMode.BEFORE_PROVIDER,
                token=bearer_token,
                session_id=UUID(before_provider_session),
                request=before_provider_request,
                marker_path=marker_path,
            ),
            tmp_path / "before-provider-child.log",
        ),
        (
            _ChildCommand(
                mode=_CrashMode.AFTER_PROVIDER_RETURN,
                token=bearer_token,
                session_id=UUID(unknown_session),
                request=unknown_request,
                marker_path=marker_path,
            ),
            tmp_path / "unknown-outcome-child.log",
        ),
        (
            _ChildCommand(
                mode=_CrashMode.AFTER_COMMIT,
                token=bearer_token,
                session_id=UUID(committed_session),
                request=committed_request,
                marker_path=marker_path,
            ),
            tmp_path / "committed-response-loss-child.log",
        ),
    )

    async with (
        _child_process(
            command=commands[0][0],
            test_settings=test_settings,
            log_path=commands[0][1],
        ) as before_provider_child,
        _child_process(
            command=commands[1][0],
            test_settings=test_settings,
            log_path=commands[1][1],
        ) as unknown_child,
        _child_process(
            command=commands[2][0],
            test_settings=test_settings,
            log_path=commands[2][1],
        ) as committed_child,
    ):
        await asyncio.gather(
            before_provider_child.require_hard_exit(),
            unknown_child.require_hard_exit(),
            committed_child.require_hard_exit(),
        )

    assert "before_provider_exit" in _markers(marker_path)
    assert _marker_count(marker_path, "provider_call:before_provider") == 0
    assert _marker_count(marker_path, "provider_call:after_provider_return") >= 1
    assert "provider_returned:after_provider_return" in _markers(marker_path)
    assert _marker_count(marker_path, "provider_call:after_commit") >= 1
    assert "response_lost_after_commit" in _markers(marker_path)

    committed_reload = await _wait_for_turn_state(
        client=client,
        bearer_token=bearer_token,
        session_id=committed_session,
        expected_state=BuilderTurnState.COMMITTED,
    )
    _assert_one_accepted_user_message(
        session=committed_reload,
        expected_content=committed_request.message,
    )
    before_provider_reload, unknown_reload = await asyncio.gather(
        _wait_for_turn_state(
            client=client,
            bearer_token=bearer_token,
            session_id=before_provider_session,
            expected_state=BuilderTurnState.FAILED_BEFORE_PROVIDER,
        ),
        _wait_for_turn_state(
            client=client,
            bearer_token=bearer_token,
            session_id=unknown_session,
            expected_state=BuilderTurnState.PROVIDER_OUTCOME_UNKNOWN,
        ),
    )

    before_latest = _latest_turn(before_provider_reload)
    assert before_latest.requires_duplicate_provider_spend_acknowledgement is False
    assert before_latest.retry_request == before_provider_request
    _assert_one_accepted_user_message(
        session=before_provider_reload,
        expected_content=before_provider_request.message,
    )
    assert len(before_provider_reload.conversation) <= MAX_SESSION_MESSAGES
    assert [attachment.id for attachment in before_provider_reload.attachments] == [
        UUID(file_id)
    ]

    unknown_latest = _latest_turn(unknown_reload)
    assert unknown_latest.requires_duplicate_provider_spend_acknowledgement is True
    assert unknown_latest.retry_request == unknown_request
    _assert_one_accepted_user_message(
        session=unknown_reload,
        expected_content=unknown_request.message,
    )

    unknown_calls_before_blocked_retry = _marker_count(
        marker_path, "provider_call:after_provider_return"
    )
    with _provider_must_not_run():
        blocked_unknown = await _send_message(
            client=client,
            bearer_token=bearer_token,
            session_id=unknown_session,
            request=unknown_request,
        )
    assert blocked_unknown.status_code == 409, blocked_unknown.text
    assert (
        _PublicError.model_validate_json(blocked_unknown.content).code
        == "session_turn_provider_outcome_unknown"
    )
    assert (
        _marker_count(marker_path, "provider_call:after_provider_return")
        == unknown_calls_before_blocked_retry
    )

    acknowledged_request = unknown_request.model_copy(
        update={"acknowledge_duplicate_provider_spend": True}
    )
    with _deterministic_provider(
        marker_path=marker_path,
        marker="provider_call:unknown_retry",
    ):
        acknowledged_retry = await _send_message(
            client=client,
            bearer_token=bearer_token,
            session_id=unknown_session,
            request=acknowledged_request,
        )
    assert acknowledged_retry.status_code == 200, acknowledged_retry.text
    assert "done" in _event_names(acknowledged_retry)
    assert _marker_count(marker_path, "provider_call:unknown_retry") >= 1
    unknown_committed = await _wait_for_turn_state(
        client=client,
        bearer_token=bearer_token,
        session_id=unknown_session,
        expected_state=BuilderTurnState.COMMITTED,
    )
    _assert_one_accepted_user_message(
        session=unknown_committed,
        expected_content=unknown_request.message,
    )

    with _deterministic_provider(
        marker_path=marker_path,
        marker="provider_call:before_provider_retry",
    ):
        before_provider_retry = await _send_message(
            client=client,
            bearer_token=bearer_token,
            session_id=before_provider_session,
            request=before_provider_request,
        )
    assert before_provider_retry.status_code == 200, before_provider_retry.text
    assert "done" in _event_names(before_provider_retry)
    assert _marker_count(marker_path, "provider_call:before_provider_retry") >= 1
    before_provider_committed = await _wait_for_turn_state(
        client=client,
        bearer_token=bearer_token,
        session_id=before_provider_session,
        expected_state=BuilderTurnState.COMMITTED,
    )
    _assert_one_accepted_user_message(
        session=before_provider_committed,
        expected_content=before_provider_request.message,
    )
    assert len(before_provider_committed.conversation) <= MAX_SESSION_MESSAGES
    assert _latest_turn(before_provider_committed).retry_request == (
        before_provider_request
    )

    committed_provider_calls = _marker_count(marker_path, "provider_call:after_commit")
    with _provider_must_not_run():
        replay = await _send_message(
            client=client,
            bearer_token=bearer_token,
            session_id=committed_session,
            request=committed_request,
        )
        conflicting_request = committed_request.model_copy(
            update={"message": "A changed request must conflict."}
        )
        conflict = await _send_message(
            client=client,
            bearer_token=bearer_token,
            session_id=committed_session,
            request=conflicting_request,
        )
    assert replay.status_code == 200, replay.text
    assert _event_names(replay) == ("done",)
    assert conflict.status_code == 409, conflict.text
    assert (
        _PublicError.model_validate_json(conflict.content).code
        == "session_turn_idempotency_conflict"
    )
    assert (
        _marker_count(marker_path, "provider_call:after_commit")
        == committed_provider_calls
    )


async def _run_child(command: _ChildCommand) -> NoReturn:
    from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
    from eneo.server.dependencies.lifespan import startup
    from eneo.server.main import get_application

    async def fake_completion(**_kwargs: object) -> MagicMock:
        _record_marker(command.marker_path, f"provider_call:{command.mode.value}")
        return _make_llm_response()

    async def exit_before_provider(
        _repo: AIBuilderRepository, **_kwargs: object
    ) -> NoReturn:
        _hard_exit(command.marker_path, "before_provider_exit")

    def exit_after_provider_return(*_args: object, **_kwargs: object) -> NoReturn:
        _hard_exit(command.marker_path, "provider_returned:after_provider_return")

    application = get_application()
    await startup()
    if command.mode is _CrashMode.BEFORE_PROVIDER:
        failure_patch = patch.object(
            AIBuilderRepository,
            "mark_session_turn_processing",
            new=exit_before_provider,
        )
    elif command.mode is _CrashMode.AFTER_PROVIDER_RETURN:
        failure_patch = patch(
            "eneo.flows.ai_builder.ai_builder_slot_classifier.parse_slot_classification_response",
            new=exit_after_provider_return,
        )
    else:
        from eneo.flows.ai_builder import ai_builder_router

        original_encode = ai_builder_router.encode_ai_builder_stream_event

        def exit_after_commit(event):
            if event.event == "done":
                _hard_exit(command.marker_path, "response_lost_after_commit")
            return original_encode(event)

        failure_patch = patch.object(
            ai_builder_router,
            "encode_ai_builder_stream_event",
            new=exit_after_commit,
        )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
            new=AsyncMock(side_effect=fake_completion),
        ),
        patch(
            "eneo.flows.ai_builder.ai_builder_router._resolve_litellm_params",
            new=AsyncMock(
                return_value=("openai/gpt-4o-mini", {"api_key": "test-only"})
            ),
        ),
        failure_patch,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test.local",
        ) as client:
            await client.post(
                f"/api/v1/flows/ai-builder/sessions/{command.session_id}/messages",
                json=command.request.model_dump(mode="json"),
                headers={
                    "Authorization": f"Bearer {command.token}",
                    "accept": "text/event-stream",
                },
            )
    raise AssertionError("AI Builder child request completed without a hard exit.")


if __name__ == "__main__" and sys.argv[1:] == [_CHILD_ARGUMENT]:
    child_command = _ChildCommand.model_validate_json(sys.stdin.read())
    asyncio.run(_run_child(child_command))
