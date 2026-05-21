"""Unit tests for the planner action dispatcher.

After monotonicity guardrails accept a `PlannerOutput`, the dispatcher
routes the action to atomic persistence. Persisted branches produce a
`PlannerDispatchResult` envelope the caller emits as an SSE event; an
invalid `commit_architecture` shape raises `ValueError`.

Contracts exercised here:

- `commit_architecture` hands the delta's `ArchitectureCommit` to
  `AIBuilderRepository.commit_turn(architecture_commit=...)`, exercising
  the repo's atomic commit-stamp path end-to-end.
- `ask_question` and `confirm_requirements` commit the conversation +
  planner-owned state but pass ``architecture_commit=None`` so the
  repo's carry-forward helper preserves any prior commit.
- `PlannerDispatchResult` is a frozen dataclass — callers treat it as
  an immutable value, and mutation would silently corrupt downstream
  event emission.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, create_autospec
from uuid import UUID, uuid4

import pytest

from intric.flows.ai_builder.ai_builder_architecture_commit import (
    architecture_commit_hash,
)
from intric.flows.ai_builder.ai_builder_dispatcher import (
    PlannerDispatchResult,
    dispatch_planner_action,
)
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_orchestrator import parse_planner_output
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
from intric.flows.ai_builder.ai_builder_session_turn import (
    SessionSendLease,
    SessionSendTurn,
)
from intric.flows.ai_builder.planning_state import ArchitectureCommit
from intric.flows.flow import Flow

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _empty_delta_dict(base_version: int = 0) -> dict:
    return {
        "base_planning_state_version": base_version,
        "signals_added": [],
        "slots_resolved": [],
        "architecture_commit": None,
    }


def _ask_question_output_dict() -> dict:
    return {
        "planning_state_delta": _empty_delta_dict(),
        "planner_action": {
            "kind": "ask_question",
            "payload": {
                "question_id": "final_output_mode",
                "slot_name": "final_output_mode",
                "prompt": "Which output mode do you need?",
            },
        },
    }


def _commit_architecture_output_dict(
    *, chosen_patterns: list[str] | None = None
) -> dict:
    return {
        "planning_state_delta": {
            **_empty_delta_dict(),
            "architecture_commit": {
                "tuples_chain": [
                    {
                        "input_type": "text",
                        "output_type": "text",
                        "output_mode": "pass_through",
                    }
                ],
                "chosen_patterns": (
                    chosen_patterns
                    if chosen_patterns is not None
                    else ["summarize_text"]
                ),
                "required_capabilities": [],
            },
        },
        "planner_action": {
            "kind": "commit_architecture",
            "payload": {"note": ""},
        },
    }


def _confirm_requirements_output_dict() -> dict:
    return {
        "planning_state_delta": _empty_delta_dict(),
        "planner_action": {
            "kind": "confirm_requirements",
            "payload": {"summary": "Ready to propose draft plan."},
        },
    }


_ALLOWED_COMMIT_TURN_KWARGS: frozenset[str] = frozenset(
    {
        "new_messages",
        "flow",
        "architecture_commit",
        "turn",
    }
)


def _mock_repo(*, next_version: int = 4) -> MagicMock:
    """AIBuilderRepository autospec locking the full `commit_turn` kwarg set.

    `create_autospec(..., instance=True)` refuses attribute access that
    is not on the real class, so any drift in `commit_turn`'s signature
    — including a new argument the dispatcher starts forwarding — will
    surface as a test failure rather than a silent pass.
    """
    repo = create_autospec(AIBuilderRepository, instance=True)
    repo.commit_turn.return_value = next_version
    return repo


def _assert_commit_turn_kwargs_bounded(commit_turn_mock: Any) -> None:
    """No kwarg outside `_ALLOWED_COMMIT_TURN_KWARGS` may reach the repo.

    Protects against a future dispatcher edit that starts forwarding
    self-reported delta fields (`signals_added`, `slots_resolved`) or
    any invented parameter through to `commit_turn`.
    """
    unexpected = set(commit_turn_mock.call_args.kwargs) - _ALLOWED_COMMIT_TURN_KWARGS
    assert not unexpected, (
        f"dispatcher forwarded unexpected kwargs to commit_turn: {sorted(unexpected)}"
    )


def _assistant_msg(content: str = "dummy") -> ConversationMessage:
    return ConversationMessage(role="assistant", content=content)


def _make_turn(
    *,
    session_id: UUID | None = None,
    tenant_id: UUID | None = None,
    base_version: int = 0,
) -> SessionSendTurn:
    return SessionSendTurn(
        session_id=session_id or uuid4(),
        tenant_id=tenant_id or uuid4(),
        lease=SessionSendLease(request_id=uuid4(), lock_token=uuid4()),
        base_planning_state_version=base_version,
    )


# ---------------------------------------------------------------------------
# commit_architecture — the motivating path
# ---------------------------------------------------------------------------


class TestCommitArchitectureDispatch:
    @pytest.mark.asyncio
    async def test_passes_architecture_commit_through_to_commit_turn(self) -> None:
        repo = _mock_repo(next_version=5)
        session_id = uuid4()
        tenant_id = uuid4()
        output = parse_planner_output(_commit_architecture_output_dict())

        await dispatch_planner_action(
            repo=repo,
            turn=_make_turn(session_id=session_id, tenant_id=tenant_id),
            output=output,
            new_messages=[_assistant_msg("committing")],
        )

        repo.commit_turn.assert_awaited_once()
        kwargs = repo.commit_turn.call_args.kwargs
        commit = kwargs["architecture_commit"]
        assert isinstance(commit, ArchitectureCommit)
        assert commit.architecture_hash == architecture_commit_hash(commit)
        assert commit.committed_at.tzinfo is not None
        assert commit.chosen_patterns == ["summarize_text"]
        assert kwargs["turn"].session_id == session_id
        assert kwargs["turn"].tenant_id == tenant_id

    @pytest.mark.asyncio
    async def test_returns_result_with_new_version(self) -> None:
        repo = _mock_repo(next_version=9)
        output = parse_planner_output(_commit_architecture_output_dict())

        result = await dispatch_planner_action(
            repo=repo,
            turn=_make_turn(),
            output=output,
            new_messages=[_assistant_msg()],
        )

        assert result == PlannerDispatchResult(
            action_kind="commit_architecture",
            new_planning_state_version=9,
        )

    @pytest.mark.asyncio
    async def test_forwards_optional_params(self) -> None:
        """`flow` and active-turn authority must flow through unchanged.

        Dropping either from the pass-through silently breaks
        optimistic concurrency and flow-scoped planning-state rebuilds.
        """
        repo = _mock_repo()
        output = parse_planner_output(_commit_architecture_output_dict())
        flow_stub = MagicMock(spec=Flow)
        turn = _make_turn()

        await dispatch_planner_action(
            repo=repo,
            turn=turn,
            output=output,
            new_messages=[_assistant_msg()],
            flow=flow_stub,
        )

        kwargs = repo.commit_turn.call_args.kwargs
        assert kwargs["flow"] is flow_stub
        assert kwargs["turn"] == turn

    @pytest.mark.asyncio
    async def test_forwards_base_version_to_commit_turn(self) -> None:
        """`base_version` must thread through on `turn` so the repo
        enforces optimistic concurrency at the DB layer.

        The Python-side `_check_version` rejects a stale `PlannerOutput`
        whose `planning_state_delta.base_planning_state_version` does not
        match `OrchestrationContext.current_version`. That guard catches
        the LLM reading stale state. It does NOT catch another process
        (admin write, concurrent session) mutating `PlanningState`
        between the pipeline's read and the dispatcher's write. The
        `base_version` CAS on `save_planning_state` closes that window;
        dropping it on the dispatch path leaves the Python guard as the
        only defence against lost writes.
        """
        repo = _mock_repo()
        output = parse_planner_output(_commit_architecture_output_dict())

        await dispatch_planner_action(
            repo=repo,
            turn=_make_turn(base_version=7),
            output=output,
            new_messages=[_assistant_msg()],
        )

        kwargs = repo.commit_turn.call_args.kwargs
        assert kwargs["turn"].base_planning_state_version == 7
        _assert_commit_turn_kwargs_bounded(repo.commit_turn)

    @pytest.mark.asyncio
    async def test_raises_when_commit_architecture_action_has_no_commit(
        self,
    ) -> None:
        """`commit_architecture` without a delta commit is a precondition
        violation — the orchestrator guardrail rejects this shape, so a
        dispatcher reaching here means the caller skipped validation."""
        repo = _mock_repo()
        payload = _commit_architecture_output_dict()
        payload["planning_state_delta"]["architecture_commit"] = None
        # parse_planner_output would accept None here because the delta
        # field is Optional at the envelope level; only the guardrail
        # enforces the commit_architecture-specific shape. Simulate a
        # caller that bypassed the guardrail.
        output = parse_planner_output(payload)

        with pytest.raises(ValueError, match="architecture_commit=None"):
            await dispatch_planner_action(
                repo=repo,
                turn=_make_turn(),
                output=output,
                new_messages=[_assistant_msg()],
            )

        repo.commit_turn.assert_not_awaited()


# ---------------------------------------------------------------------------
# ask_question / confirm_requirements — non-commit paths
# ---------------------------------------------------------------------------


class TestAskQuestionDispatch:
    @pytest.mark.asyncio
    async def test_passes_none_architecture_commit(self) -> None:
        repo = _mock_repo()
        output = parse_planner_output(_ask_question_output_dict())

        await dispatch_planner_action(
            repo=repo,
            turn=_make_turn(),
            output=output,
            new_messages=[_assistant_msg("what?")],
        )

        repo.commit_turn.assert_awaited_once()
        assert repo.commit_turn.call_args.kwargs["architecture_commit"] is None

    @pytest.mark.asyncio
    async def test_result_carries_action_kind_and_version(self) -> None:
        repo = _mock_repo(next_version=2)
        output = parse_planner_output(_ask_question_output_dict())

        result = await dispatch_planner_action(
            repo=repo,
            turn=_make_turn(),
            output=output,
            new_messages=[_assistant_msg()],
        )

        assert result.action_kind == "ask_question"
        assert result.new_planning_state_version == 2


class TestConfirmRequirementsDispatch:
    @pytest.mark.asyncio
    async def test_passes_none_architecture_commit(self) -> None:
        repo = _mock_repo()
        output = parse_planner_output(_confirm_requirements_output_dict())

        await dispatch_planner_action(
            repo=repo,
            turn=_make_turn(),
            output=output,
            new_messages=[_assistant_msg("summary")],
        )

        repo.commit_turn.assert_awaited_once()
        assert repo.commit_turn.call_args.kwargs["architecture_commit"] is None

    @pytest.mark.asyncio
    async def test_result_has_confirm_requirements_kind(self) -> None:
        repo = _mock_repo(next_version=3)
        output = parse_planner_output(_confirm_requirements_output_dict())

        result = await dispatch_planner_action(
            repo=repo,
            turn=_make_turn(),
            output=output,
            new_messages=[_assistant_msg()],
        )

        assert result.action_kind == "confirm_requirements"
        assert result.new_planning_state_version == 3


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


class TestPlannerDispatchResultShape:
    def test_result_is_frozen(self) -> None:
        result = PlannerDispatchResult(
            action_kind="ask_question",
            new_planning_state_version=1,
        )
        with pytest.raises((AttributeError, TypeError)):
            result.new_planning_state_version = 2  # type: ignore[misc]

    def test_result_equality_is_structural(self) -> None:
        a = PlannerDispatchResult(
            action_kind="commit_architecture", new_planning_state_version=7
        )
        b = PlannerDispatchResult(
            action_kind="commit_architecture", new_planning_state_version=7
        )
        assert a == b


# ---------------------------------------------------------------------------
# Delta isolation — self-reported planner claims must not leak into the repo
# ---------------------------------------------------------------------------


class TestDeltaIsolation:
    """`commit_turn` rebuilds state from conversation; the planner's
    self-reported `signals_added` / `slots_resolved` in the delta are
    claims for guardrails, never inputs to the repo. Verify the
    dispatcher never forwards them as kwargs.
    """

    @pytest.mark.asyncio
    async def test_ask_question_does_not_forward_delta_signals(self) -> None:
        repo = _mock_repo()
        payload = _ask_question_output_dict()
        payload["planning_state_delta"]["signals_added"] = [
            {
                "question_id": "final_output_mode",
                "value": "docx",
                "confidence": "high",
                "source": "structured_answer",
                "provenance": [],
            }
        ]
        payload["planning_state_delta"]["slots_resolved"] = [
            {
                "name": "final_output_mode",
                "value": "docx",
                "source": "structured_answer",
                "evidence": [],
                "confidence": "high",
            }
        ]
        output = parse_planner_output(payload)

        await dispatch_planner_action(
            repo=repo,
            turn=_make_turn(),
            output=output,
            new_messages=[_assistant_msg()],
        )

        _assert_commit_turn_kwargs_bounded(repo.commit_turn)

    @pytest.mark.asyncio
    async def test_commit_architecture_does_not_forward_delta_signals(
        self,
    ) -> None:
        repo = _mock_repo()
        payload = _commit_architecture_output_dict()
        payload["planning_state_delta"]["signals_added"] = [
            {
                "question_id": "primary_runtime_input",
                "value": "pdf",
                "confidence": "high",
                "source": "structured_answer",
                "provenance": [],
            }
        ]
        output = parse_planner_output(payload)

        await dispatch_planner_action(
            repo=repo,
            turn=_make_turn(),
            output=output,
            new_messages=[_assistant_msg()],
        )

        _assert_commit_turn_kwargs_bounded(repo.commit_turn)


# ---------------------------------------------------------------------------
# Type-sanity
# ---------------------------------------------------------------------------


class TestTypeContracts:
    def test_turn_is_keyword_only(self) -> None:
        """`turn` must be keyword-only so callers cannot bypass names."""
        repo = _mock_repo()
        output = parse_planner_output(_ask_question_output_dict())

        with pytest.raises(TypeError):
            dispatch_planner_action(  # type: ignore[call-arg]
                repo,
                _make_turn(),
                output,
                [_assistant_msg()],
            )
