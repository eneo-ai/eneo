from __future__ import annotations

import asyncio
import json
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
from sqlalchemy import select

from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.completion_models.infrastructure.completion_service import (
    ResolvedCompletionModelRoute,
)
from eneo.database.tables.flow_tables import BuilderSessions
from eneo.database.tables.spaces_table import SpacesCompletionModels
from eneo.flows.ai_builder.ai_builder_api_models import (
    SendMessageRequest,
    SessionResponse,
)
from eneo.flows.ai_builder.ai_builder_conversation_compaction import (
    MAX_SESSION_MESSAGES,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderTurnState,
    PlanStatus,
)
from eneo.flows.ai_builder.ai_builder_plan_edit_context import AIBuilderPlanEditContext
from eneo.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from eneo.flows.ai_builder.ai_builder_tool_names import PROPOSE_FLOW_TOOL_NAME
from eneo.flows.ai_builder.planning_state import (
    PLANNING_STATE_PAYLOAD_CAP_BYTES,
    PlanningSignal,
    PlanningState,
)
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


def _route(
    *,
    model: str = "openai/gpt-4o-mini",
    kwargs: dict[str, object] | None = None,
) -> ResolvedCompletionModelRoute:
    return ResolvedCompletionModelRoute(
        litellm_model=model,
        provider_type="openai",
        litellm_kwargs=kwargs or {},
        supported_model_kwargs=SupportedModelKwargs(
            temperature=ModelKwargCapability(supported=True)
        ),
    )


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


def _make_llm_response(
    *,
    content: str | None = "Jag kan hjälpa dig bygga flödet.",
    tool_calls: list[MagicMock] | None = None,
) -> MagicMock:
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_tool_call(
    *,
    name: str,
    arguments: dict[str, object],
) -> MagicMock:
    tool_call = MagicMock()
    tool_call.id = f"call-{uuid4()}"
    tool_call.function.name = name
    tool_call.function.arguments = json.dumps(arguments)
    return tool_call


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
    *,
    marker_path: Path,
    marker: str,
    response: MagicMock | None = None,
    **_kwargs: object,
) -> MagicMock:
    _record_marker(marker_path, marker)
    return response or _make_llm_response()


@contextmanager
def _deterministic_provider(
    *,
    marker_path: Path,
    marker: str,
    response: MagicMock | None = None,
) -> Iterator[None]:
    async def completion(**kwargs: object) -> MagicMock:
        return await _deterministic_completion(
            marker_path=marker_path,
            marker=marker,
            response=response,
            **kwargs,
        )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_service.litellm.acompletion",
            new=AsyncMock(side_effect=completion),
        ),
        patch(
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "test-only"})),
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


def _parse_sse_payload(response: Response) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    current_event: str | None = None
    data_lines: list[str] = []
    for raw_line in response.text.splitlines():
        line = raw_line.rstrip("\r")
        if line.startswith("event:"):
            current_event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())
        elif line == "" and current_event is not None:
            raw_data = "\n".join(data_lines)
            events.append(
                {
                    "event": current_event,
                    "data": json.loads(raw_data) if raw_data else "",
                }
            )
            current_event = None
            data_lines = []
    return events


def _proposal_response(*, flow_name: str) -> MagicMock:
    proposal = _make_tool_call(
        name=PROPOSE_FLOW_TOOL_NAME,
        arguments={
            "flow_name": flow_name,
            "flow_description": "Sammanfattar dokument till en PDF-rapport.",
            "plan_rationale": "Extrahera en grundad sammanfattning till rapporten.",
            "steps": [
                {
                    "name": "Extrahera sammanfattning",
                    "instructions": (
                        "Sammanfatta dokumentunderlaget tydligt på svenska."
                    ),
                    "output_type": "json",
                    "output_fields": [
                        {
                            "name": "summary",
                            "field_type": "string",
                            "description": "En kort sammanfattning.",
                        }
                    ],
                }
            ],
        },
    )
    return _make_llm_response(content=None, tool_calls=[proposal])


async def _progress_session_to_plan(
    *,
    client: AsyncClient,
    bearer_token: str,
    session_id: str,
) -> Response:
    message = "Skapa ett flöde som sammanfattar dokument till en PDF-rapport."
    question_answer: dict[str, object] | None = None
    structured_answers = {
        "primary_runtime_input": "documents",
        "input_material_mode": "documents",
        "flow_input_architecture": "document_primary_input",
        "document_kind": "case_documents",
        "terminal_output": "pdf_document",
        "post_processing_goal": "summarize_or_overview",
        "runtime_metadata_fields": "no_extra_metadata",
    }
    for _ in range(7):
        response = await _send_message(
            client=client,
            bearer_token=bearer_token,
            session_id=session_id,
            request=SendMessageRequest(
                client_turn_id=uuid4(),
                message=message,
                question_answer=question_answer,
                ui_language="sv",
            ),
        )
        assert response.status_code == 200, response.text
        events = _parse_sse_payload(response)
        if any(event["event"] == "plan" for event in events):
            return response

        requirements = next(
            (event for event in events if event["event"] == "requirements_summary"),
            None,
        )
        if requirements is not None:
            requirements_data = requirements["data"]
            assert isinstance(requirements_data, dict)
            message = "Ja, det stämmer. Bygg planen."
            question_answer = {
                "kind": "requirements_confirmation",
                "requirements_confirmed": True,
                "requirements_version": requirements_data["requirements_version"],
                "ui_language": "sv",
            }
            continue

        question = next(
            (event for event in events if event["event"] == "question"),
            None,
        )
        assert question is not None, events
        question_data = question["data"]
        assert isinstance(question_data, dict)
        question_id = str(question_data["question_id"])
        selected_option_id = structured_answers.get(question_id)
        assert selected_option_id is not None, events
        options = question_data["options"]
        assert isinstance(options, list)
        selected_option = next(
            (
                option
                for option in options
                if isinstance(option, dict) and option.get("id") == selected_option_id
            ),
            None,
        )
        assert selected_option is not None, question_data
        message = str(selected_option["label"])
        question_answer = {
            "kind": "structured_question_answer",
            "question_id": question_id,
            "selected_option_ids": [selected_option_id],
            "selected_values": [selected_option_id],
            "ui_language": "sv",
        }

    raise AssertionError("AI Builder did not produce the setup plan.")


def _planning_state_at_byte_size(
    prior_state: PlanningState,
    *,
    byte_size: int,
) -> PlanningState:
    state = prior_state.model_copy(deep=True)
    filler = PlanningSignal(
        question_id="payload_cap",
        value="",
        confidence="high",
        source="model",
    )
    state.signals.append(filler)
    empty_size = len(
        json.dumps(
            state.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert empty_size < byte_size
    filler.value = "x" * (byte_size - empty_size)
    measured_size = len(
        json.dumps(
            state.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert measured_size == byte_size
    return state


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
    *,
    session: SessionResponse,
    expected_content: str,
    expected_message_id: UUID | None = None,
) -> UUID:
    latest_turn = _latest_turn(session)
    message_id = latest_turn.user_message_id
    if expected_message_id is not None:
        assert message_id == expected_message_id
    matching_messages = [
        message
        for message in session.conversation
        if message.role == "user" and message.content == expected_content
    ]
    assert len(matching_messages) == 1
    assert matching_messages[0].message_id == str(message_id)
    return message_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_oversized_planning_state_is_committed_once_and_replayed(
    client: AsyncClient,
    bearer_token: str,
    completion_model_factory,
    db_container,
    tmp_path: Path,
) -> None:
    marker_path = tmp_path / "oversized-state-provider-markers.txt"
    space_id = await _create_space_with_model(
        client=client,
        bearer_token=bearer_token,
        db_container=db_container,
        completion_model_factory=completion_model_factory,
    )
    session_id = await _create_session(
        client=client,
        bearer_token=bearer_token,
        space_id=space_id,
    )
    with _deterministic_provider(
        marker_path=marker_path,
        marker="setup_provider",
        response=_proposal_response(flow_name="Första planen"),
    ):
        setup_response = await _progress_session_to_plan(
            client=client,
            bearer_token=bearer_token,
            session_id=session_id,
        )
    assert "plan" in _event_names(setup_response)

    public_before = await _load_session(
        client=client,
        bearer_token=bearer_token,
        session_id=session_id,
    )
    async with db_container() as container:
        tenant_id = (
            await container.session().execute(
                select(BuilderSessions.tenant_id).where(
                    BuilderSessions.id == UUID(session_id)
                )
            )
        ).scalar_one()
        repo = AIBuilderRepository(container.session())
        session_before = await repo.get_session(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
        )
        planning_state_before = await repo.load_planning_state(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
        )
        plans_before = await repo.list_session_plans(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
        )

    assert planning_state_before is not None
    assert len(plans_before) == 1
    prior_plan = plans_before[0]
    assert prior_plan.status is PlanStatus.PROPOSED
    assert public_before.latest_plan_id == prior_plan.id
    oversized_state = _planning_state_at_byte_size(
        planning_state_before,
        byte_size=PLANNING_STATE_PAYLOAD_CAP_BYTES + 1,
    )
    revision_request = SendMessageRequest(
        client_turn_id=uuid4(),
        message="Byt namn på planen men behåll samma beteende.",
        edit_context=AIBuilderPlanEditContext(
            scope="whole_plan",
            plan_id=prior_plan.id,
        ),
        ui_language="sv",
    )

    with (
        patch(
            "eneo.flows.ai_builder.ai_builder_repo.build_planning_state_from_conversation",
            return_value=oversized_state,
        ),
        _deterministic_provider(
            marker_path=marker_path,
            marker="oversized_state_provider",
            response=_proposal_response(flow_name="Reviderad plan"),
        ),
    ):
        first_response = await _send_message(
            client=client,
            bearer_token=bearer_token,
            session_id=session_id,
            request=revision_request,
        )

    assert first_response.status_code == 200, first_response.text
    assert _event_names(first_response) == ("error", "done")
    first_events = _parse_sse_payload(first_response)
    error_data = first_events[0]["data"]
    assert isinstance(error_data, dict)
    assert error_data["code"] == "planning_state_payload_too_large"
    assert error_data["category"] == "bad_request"
    assert error_data["phase"] == "planner"
    assert error_data["details"] == {
        "payload_bytes": PLANNING_STATE_PAYLOAD_CAP_BYTES + 1,
        "payload_cap_bytes": PLANNING_STATE_PAYLOAD_CAP_BYTES,
    }
    provider_calls_before_replay = _marker_count(
        marker_path,
        "oversized_state_provider",
    )
    assert provider_calls_before_replay > 0

    public_after = await _load_session(
        client=client,
        bearer_token=bearer_token,
        session_id=session_id,
    )
    latest_turn = _latest_turn(public_after)
    assert latest_turn.state is BuilderTurnState.COMMITTED
    assert latest_turn.error is not None
    assert latest_turn.error.code == "planning_state_payload_too_large"
    assert public_after.latest_plan_id == prior_plan.id
    assert public_after.conversation[: len(public_before.conversation)] == (
        public_before.conversation
    )
    appended_messages = public_after.conversation[len(public_before.conversation) :]
    assert len(appended_messages) == 1
    assert appended_messages[0].role == "user"
    _assert_one_accepted_user_message(
        session=public_after,
        expected_content=revision_request.message,
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        session_after = await repo.get_session(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
        )
        planning_state_after = await repo.load_planning_state(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
        )
        plans_after = await repo.list_session_plans(
            session_id=UUID(session_id),
            tenant_id=tenant_id,
        )

    assert session_after.planning_state_version == session_before.planning_state_version
    assert planning_state_after == planning_state_before
    assert [(plan.id, plan.status) for plan in plans_after] == [
        (prior_plan.id, PlanStatus.PROPOSED)
    ]

    with _provider_must_not_run():
        replay = await _send_message(
            client=client,
            bearer_token=bearer_token,
            session_id=session_id,
            request=revision_request,
        )
    assert replay.status_code == 200, replay.text
    assert replay.text == first_response.text
    assert _event_names(replay) == ("error", "done")
    assert (
        _marker_count(marker_path, "oversized_state_provider")
        == provider_calls_before_replay
    )
    replayed_session = await _load_session(
        client=client,
        bearer_token=bearer_token,
        session_id=session_id,
    )
    assert replayed_session.conversation == public_after.conversation
    assert replayed_session.latest_turn == public_after.latest_turn
    assert replayed_session.latest_plan_id == prior_plan.id


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
    committed_message_id = _assert_one_accepted_user_message(
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
    before_provider_message_id = _assert_one_accepted_user_message(
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
    unknown_message_id = _assert_one_accepted_user_message(
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
        expected_message_id=unknown_message_id,
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
        expected_message_id=before_provider_message_id,
    )
    assert len(before_provider_committed.conversation) <= MAX_SESSION_MESSAGES
    assert _latest_turn(before_provider_committed).retry_request == (
        before_provider_request
    )
    assert [attachment.id for attachment in before_provider_committed.attachments] == [
        UUID(file_id)
    ]

    committed_provider_calls = _marker_count(marker_path, "provider_call:after_commit")
    with _provider_must_not_run():
        replay = await _send_message(
            client=client,
            bearer_token=bearer_token,
            session_id=committed_session,
            request=committed_request,
        )
    assert replay.status_code == 200, replay.text
    assert _event_names(replay) == ("done",)
    replayed_reload = await _load_session(
        client=client,
        bearer_token=bearer_token,
        session_id=committed_session,
    )
    _assert_one_accepted_user_message(
        session=replayed_reload,
        expected_content=committed_request.message,
        expected_message_id=committed_message_id,
    )
    assert replayed_reload.conversation == committed_reload.conversation
    assert replayed_reload.latest_turn == committed_reload.latest_turn
    assert replayed_reload.attachments == committed_reload.attachments

    conflicting_request = committed_request.model_copy(
        update={"message": "A changed request must conflict."}
    )
    with _provider_must_not_run():
        conflict = await _send_message(
            client=client,
            bearer_token=bearer_token,
            session_id=committed_session,
            request=conflicting_request,
        )
    assert conflict.status_code == 409, conflict.text
    assert (
        _PublicError.model_validate_json(conflict.content).code
        == "session_turn_idempotency_conflict"
    )
    conflict_reload = await _load_session(
        client=client,
        bearer_token=bearer_token,
        session_id=committed_session,
    )
    _assert_one_accepted_user_message(
        session=conflict_reload,
        expected_content=committed_request.message,
        expected_message_id=committed_message_id,
    )
    assert conflict_reload.conversation == committed_reload.conversation
    assert conflict_reload.latest_turn == committed_reload.latest_turn
    assert conflict_reload.attachments == committed_reload.attachments
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
            "eneo.completion_models.infrastructure.completion_service.CompletionService.resolve_model_route",
            new=AsyncMock(return_value=_route(kwargs={"api_key": "test-only"})),
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
