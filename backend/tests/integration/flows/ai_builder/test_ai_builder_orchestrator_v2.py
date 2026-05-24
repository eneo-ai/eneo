"""Integration tests for `run_planner_turn` against a real repo + mocked LLM.

`run_planner_turn` is already exhaustively unit-tested with
`AsyncMock(AIBuilderRepository)` — see
`tests/unittests/flows/ai_builder/test_ai_builder_planner_turn.py`. The
unit tests pin the contract of every outcome kind (`dispatched`,
`rejected`, `parse_failed`) but they never exercise the real persistence
layer.

This suite closes that gap. Each test drives a full turn end-to-end
against a live PostgreSQL container so the real `commit_turn`
savepoint, `load_planning_state` round-trip, and architecture-commit
atomic stamp all land exactly once. The LLM is the ONLY boundary
mocked — the `litellm_client.acompletion` coroutine returns a
hand-built JSON payload shaped like the orchestrator's structured
output contract.

Scope:
- `commit_architecture` happy path — the accepted delta's
  `ArchitectureCommit` is stamped onto `PlanningState` in the same
  savepoint as the conversation append, and `load_planning_state`
  returns the same semantic architecture with server-owned hash/time.
- `ask_question` happy path — conversation appended, no commit on the
  persisted state (carry-forward starts from empty).
- `rejected` outcome — the pipeline's terminal-rejection path does
  NOT write to the repo: conversation remains empty after the turn.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from intric.flows.ai_builder.ai_builder_architecture_commit import (
    architecture_commit_hash,
    canonical_architecture_commit_payload,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_orchestrator import OrchestrationContext
from intric.flows.ai_builder.ai_builder_planner_turn import run_planner_turn
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    PlanningState,
    ResolvedSlot,
    StepTriple,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _architecture_commit_fixture() -> ArchitectureCommit:
    """A minimal, deterministic commit the planner "produces" for happy-path tests."""
    return ArchitectureCommit(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=["summarize_text"],
        required_capabilities=["input_text", "output_mode_pass_through"],
        committed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )


def _resolved_core_slots() -> dict[str, ResolvedSlot]:
    return {
        "primary_runtime_input": ResolvedSlot(
            name="primary_runtime_input",
            value="text",
            source="structured_answer",
            confidence="high",
        ),
        "terminal_output": ResolvedSlot(
            name="terminal_output",
            value="text",
            source="structured_answer",
            confidence="high",
        ),
    }


def _planner_output_json(
    *,
    kind: str,
    architecture_commit: ArchitectureCommit | None = None,
    base_version: int = 0,
) -> str:
    """Build a structured-JSON planner-output string the pipeline will parse."""
    if kind == "ask_question":
        payload: dict[str, Any] = {
            "question_id": "primary_runtime_input",
            "slot_name": "primary_runtime_input",
            "prompt": "Vad ska flödet ta emot?",
        }
    elif kind == "commit_architecture":
        payload = {"note": ""}
    elif kind == "confirm_requirements":
        payload = {"summary": "Resolved"}
    else:
        raise AssertionError(f"unsupported planner action kind {kind}")

    return json.dumps(
        {
            "planning_state_delta": {
                "base_planning_state_version": base_version,
                "signals_added": [],
                "slots_resolved": [],
                "architecture_commit": (
                    canonical_architecture_commit_payload(architecture_commit)
                    if architecture_commit is not None
                    else None
                ),
            },
            "planner_action": {"kind": kind, "payload": payload},
        }
    )


@dataclass(frozen=True)
class _LLMMessageStub:
    """Strict stand-in for `litellm.ModelResponse`-nested message body.

    `SimpleNamespace` would also work, but a frozen dataclass pins the
    exact attribute set the orchestrator reads (`content`) — a future
    refactor that silently renames the field would fail here loudly
    instead of false-passing via magic attribute creation.
    """

    content: str


@dataclass(frozen=True)
class _LLMChoiceStub:
    message: _LLMMessageStub
    finish_reason: str


@dataclass(frozen=True)
class _LLMUsageStub:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class _LLMResponseStub:
    choices: list[_LLMChoiceStub]
    usage: _LLMUsageStub


def _mock_llm_client(
    content: str,
    *,
    finish_reason: str = "stop",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    total_tokens: int = 150,
) -> AsyncMock:
    """Build a litellm-shaped async mock whose response parses as a PlannerOutput.

    The response is a concrete dataclass (not `MagicMock`) so that a
    future read of a new / renamed attribute inside the orchestrator
    fails the test loudly instead of being auto-manufactured into a
    silent pass.
    """
    response = _LLMResponseStub(
        choices=[
            _LLMChoiceStub(
                message=_LLMMessageStub(content=content),
                finish_reason=finish_reason,
            )
        ],
        usage=_LLMUsageStub(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        ),
    )

    client = AsyncMock()
    client.acompletion.return_value = response
    return client


def _orchestration_context(
    *,
    current_version: int = 0,
    architecture_commit: ArchitectureCommit | None = None,
    required_slot_names: frozenset[str] = frozenset(),
    resolve_core_slots: bool = True,
) -> OrchestrationContext:
    state = PlanningState.empty()
    if architecture_commit is not None:
        state.architecture_commit = architecture_commit
    if resolve_core_slots:
        state.resolved_slots = _resolved_core_slots()
    return OrchestrationContext(
        current_version=current_version,
        session_state=state,
        required_slot_names=required_slot_names,
        unresolved_architectural_choices=frozenset(),
    )


async def _create_space(
    *,
    db_container: Any,
    space_name: str,
) -> UUID:
    """Create a user-scoped Space directly via the ORM.

    The test's job is to exercise the `run_planner_turn` persistence
    path — `AIBuilderRepository.create_session` only needs a valid
    `Space.id`, not a completion-model association (the LLM call is
    mocked at the `litellm_client.acompletion` boundary). Skipping the
    model/provider seeding removes coupling to a fixture outside this
    DB contract. `user_id=user.id` marks the Space user-scoped, which
    dodges the `idx_unique_org_space_per_tenant` constraint that
    fires for `user_id IS NULL`.
    """
    from intric.database.tables.spaces_table import Spaces

    async with db_container() as container:
        session = container.session()
        user = container.user()
        space = Spaces(name=space_name, tenant_id=user.tenant_id, user_id=user.id)
        session.add(space)
        await session.flush()
        return space.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_planner_turn_persists_commit_architecture_through_real_repo(
    db_container,
) -> None:
    """Happy path: `commit_architecture` accepted → ArchitectureCommit lands atomically.

    A single turn drives the real dispatcher through a real
    `commit_turn` savepoint. After the turn, `load_planning_state`
    must return the same semantic commit that the planner produced,
    plus server-owned hash/time — no field drift or partial writes.
    """
    commit = _architecture_commit_fixture()
    space_id = await _create_space(
        db_container=db_container,
        space_name="AI Builder Orchestrator V2 Commit",
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=space_id,
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )

        llm = _mock_llm_client(
            _planner_output_json(
                kind="commit_architecture",
                architecture_commit=commit,
            )
        )
        turn = SessionSendTurn(
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
            base_planning_state_version=0,
        )
        assert (
            await repo.claim_session_send(
                session_id=session.id,
                tenant_id=user.tenant_id,
                lease=turn.lease,
                # Keep the integration lease comfortably alive without
                # asserting production TTL policy.
                lock_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
            )
            is True
        )

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-4o-mini",
            litellm_kwargs={},
            turn=turn,
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_orchestration_context(),
            build_new_messages=lambda _a, _t: [
                ConversationMessage(role="user", content="Bind arkitekturen."),
                ConversationMessage(role="assistant", content="Arkitektur committad."),
            ],
        )

    assert result.kind == "dispatched"
    assert result.dispatch_result is not None
    assert result.dispatch_result.action_kind == "commit_architecture"
    assert result.dispatch_result.new_planning_state_version >= 1
    assert result.repair_attempts == 0
    assert llm.acompletion.await_count == 1
    assert result.turn_telemetry is not None
    assert result.turn_telemetry.request_id == str(turn.lease.request_id)
    assert result.turn_telemetry.architecture_commit_populated is True
    assert result.turn_telemetry.prompt_tokens == 100
    assert result.turn_telemetry.completion_tokens == 50

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        loaded = await repo.load_planning_state(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )
        fetched_session = await repo.get_session(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )

    assert loaded is not None
    assert loaded.architecture_commit is not None
    assert loaded.architecture_commit.architecture_hash == architecture_commit_hash(
        commit
    )
    assert loaded.architecture_commit.committed_at.tzinfo is not None
    assert canonical_architecture_commit_payload(loaded.architecture_commit) == (
        canonical_architecture_commit_payload(commit)
    )
    assert len(fetched_session.conversation) == 2
    assert fetched_session.conversation[0].role == "user"
    assert fetched_session.conversation[1].role == "assistant"


@pytest.mark.asyncio
async def test_run_planner_turn_persists_ask_question_without_commit(
    db_container,
) -> None:
    """`ask_question` accepted → conversation appended, no architecture commit.

    Proves the dispatcher's carry-forward logic starts from empty when
    the session has no prior commit and the accepted action doesn't
    introduce one. The persisted state's `architecture_commit` must
    stay None.
    """
    space_id = await _create_space(
        db_container=db_container,
        space_name="AI Builder Orchestrator V2 Ask",
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=space_id,
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )

        llm = _mock_llm_client(_planner_output_json(kind="ask_question"))
        turn = SessionSendTurn(
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
            base_planning_state_version=0,
        )
        assert (
            await repo.claim_session_send(
                session_id=session.id,
                tenant_id=user.tenant_id,
                lease=turn.lease,
                # Keep the integration lease comfortably alive without
                # asserting production TTL policy.
                lock_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
            )
            is True
        )

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-4o-mini",
            litellm_kwargs={},
            turn=turn,
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_orchestration_context(
                required_slot_names=frozenset({"primary_runtime_input"}),
                resolve_core_slots=False,
            ),
            build_new_messages=lambda _a, _t: [
                ConversationMessage(role="user", content="Vad behöver jag svara på?"),
                ConversationMessage(
                    role="assistant",
                    content="Vad ska flödet ta emot som input?",
                ),
            ],
        )

    assert result.kind == "dispatched"
    assert result.dispatch_result is not None
    assert result.dispatch_result.action_kind == "ask_question"
    assert result.repair_attempts == 0
    assert llm.acompletion.await_count == 1
    assert result.turn_telemetry is not None
    assert result.turn_telemetry.request_id == str(turn.lease.request_id)
    assert result.turn_telemetry.architecture_commit_populated is False

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        loaded = await repo.load_planning_state(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )
        fetched_session = await repo.get_session(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )

    assert loaded is not None
    assert loaded.architecture_commit is None
    assert len(fetched_session.conversation) == 2


@pytest.mark.asyncio
async def test_run_planner_turn_rejected_outcome_does_not_persist(
    db_container,
) -> None:
    """Terminal rejection → no DB writes.

    The planner asserts a `base_planning_state_version` that does not
    match the session's current version; the monotonicity guardrail
    rejects the turn. The repo must NOT see a conversation append or
    a planning-state save — proves the pipeline's rejection path is
    wired before the dispatcher in `run_planner_turn`.
    """
    space_id = await _create_space(
        db_container=db_container,
        space_name="AI Builder Orchestrator V2 Reject",
    )

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        session = await repo.create_session(
            tenant_id=user.tenant_id,
            space_id=space_id,
            actor_user_id=user.id,
            target_kind=TargetKind.CREATE,
            flow_id=None,
        )

        llm = _mock_llm_client(
            _planner_output_json(
                kind="confirm_requirements",
                # Context says current_version=7; planner asserts base_version=99 —
                # monotonicity rejection.
                base_version=99,
            )
        )
        turn = SessionSendTurn(
            session_id=session.id,
            tenant_id=user.tenant_id,
            lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
            base_planning_state_version=7,
        )

        def _fail_if_builder_invoked(_a: Any, _t: Any) -> list[ConversationMessage]:
            raise AssertionError(
                "rejected outcome must not call the post-accept builder; "
                "no conversation should be appended"
            )

        result = await run_planner_turn(
            repo=repo,
            litellm_client=llm,
            litellm_model="openai/gpt-4o-mini",
            litellm_kwargs={},
            turn=turn,
            flow=None,
            base_messages=[{"role": "system", "content": "system"}],
            orchestration_context=_orchestration_context(current_version=7),
            build_new_messages=_fail_if_builder_invoked,
        )

    assert result.kind == "rejected"
    assert result.rejection is not None
    assert result.rejection.code == "version_mismatch"
    assert result.rejection.current_version == 7
    assert result.repair_attempts == 0
    assert llm.acompletion.await_count == 1

    async with db_container() as container:
        repo = AIBuilderRepository(container.session())
        user = container.user()
        loaded = await repo.load_planning_state(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )
        fetched_session = await repo.get_session(
            session_id=session.id,
            tenant_id=user.tenant_id,
        )

    assert loaded is None
    assert fetched_session.conversation == []
