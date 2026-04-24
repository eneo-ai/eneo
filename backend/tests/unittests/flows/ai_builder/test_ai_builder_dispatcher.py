"""Unit tests for the planner action dispatcher.

After monotonicity guardrails accept a `PlannerOutput`, the dispatcher
routes the action to atomic persistence. Persisted branches produce a
`PlannerDispatchResult` envelope the caller emits as an SSE event;
`propose_plan` raises `NotImplementedError` (adapter not wired yet),
and an invalid `commit_architecture` shape raises `ValueError`.

Contracts exercised here:

- `commit_architecture` hands the delta's `ArchitectureCommit` to
  `AIBuilderRepository.commit_turn(architecture_commit=...)`, exercising
  the repo's atomic commit-stamp path end-to-end.
- `ask_question` and `confirm_requirements` commit the conversation +
  planner-owned state but pass ``architecture_commit=None`` so the
  repo's carry-forward helper preserves any prior commit.
- `propose_plan` intentionally raises `NotImplementedError` — its
  handoff to the legacy proposal processor requires a translating
  adapter that is not wired here; the dispatcher must not silently
  forward a `propose_plan` action through `commit_turn`.
- `PlannerDispatchResult` is a frozen dataclass — callers treat it as
  an immutable value, and mutation would silently corrupt downstream
  event emission.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, create_autospec
from uuid import UUID, uuid4

import pytest

from intric.flows.ai_builder.ai_builder_dispatcher import (
    PlannerDispatchResult,
    dispatch_planner_action,
)
from intric.flows.ai_builder.ai_builder_domain_models import ConversationMessage
from intric.flows.ai_builder.ai_builder_orchestrator import parse_planner_output
from intric.flows.ai_builder.ai_builder_repo import AIBuilderRepository
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
        "draft_plan": None,
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
    *, hash_hex: str = "a" * 64, chosen_patterns: list[str] | None = None
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
                "committed_at": datetime(2026, 4, 23, tzinfo=timezone.utc).isoformat(),
                "architecture_hash": hash_hex,
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


def _propose_plan_output_dict() -> dict:
    return {
        "planning_state_delta": {
            **_empty_delta_dict(),
            "draft_plan": {"steps": [{"id": "s0"}]},
        },
        "planner_action": {
            "kind": "propose_plan",
            "payload": {"plan_reference": "latest"},
        },
    }


_ALLOWED_COMMIT_TURN_KWARGS: frozenset[str] = frozenset(
    {
        "session_id",
        "tenant_id",
        "new_messages",
        "flow",
        "request_id",
        "lock_token",
        "architecture_commit",
        "base_version",
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
            session_id=session_id,
            tenant_id=tenant_id,
            output=output,
            new_messages=[_assistant_msg("committing")],
        )

        repo.commit_turn.assert_awaited_once()
        kwargs = repo.commit_turn.call_args.kwargs
        commit = kwargs["architecture_commit"]
        assert isinstance(commit, ArchitectureCommit)
        assert commit.architecture_hash == "a" * 64
        assert commit.chosen_patterns == ["summarize_text"]
        assert kwargs["session_id"] == session_id
        assert kwargs["tenant_id"] == tenant_id

    @pytest.mark.asyncio
    async def test_returns_result_with_new_version(self) -> None:
        repo = _mock_repo(next_version=9)
        output = parse_planner_output(_commit_architecture_output_dict())

        result = await dispatch_planner_action(
            repo=repo,
            session_id=uuid4(),
            tenant_id=uuid4(),
            output=output,
            new_messages=[_assistant_msg()],
        )

        assert result == PlannerDispatchResult(
            action_kind="commit_architecture",
            new_planning_state_version=9,
        )

    @pytest.mark.asyncio
    async def test_forwards_optional_params(self) -> None:
        """`flow`, `request_id`, and `lock_token` must flow through unchanged.

        Dropping any of these from the pass-through silently breaks
        optimistic concurrency and flow-scoped planning-state rebuilds.
        """
        repo = _mock_repo()
        output = parse_planner_output(_commit_architecture_output_dict())
        flow_stub = MagicMock(spec=Flow)
        request_id = uuid4()
        lock_token = uuid4()

        await dispatch_planner_action(
            repo=repo,
            session_id=uuid4(),
            tenant_id=uuid4(),
            output=output,
            new_messages=[_assistant_msg()],
            flow=flow_stub,
            request_id=request_id,
            lock_token=lock_token,
        )

        kwargs = repo.commit_turn.call_args.kwargs
        assert kwargs["flow"] is flow_stub
        assert kwargs["request_id"] == request_id
        assert kwargs["lock_token"] == lock_token

    @pytest.mark.asyncio
    async def test_forwards_base_version_to_commit_turn(self) -> None:
        """`base_version` must thread through to `commit_turn` so the repo
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
            session_id=uuid4(),
            tenant_id=uuid4(),
            output=output,
            new_messages=[_assistant_msg()],
            base_version=7,
        )

        kwargs = repo.commit_turn.call_args.kwargs
        assert kwargs["base_version"] == 7
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
                session_id=uuid4(),
                tenant_id=uuid4(),
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
            session_id=uuid4(),
            tenant_id=uuid4(),
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
            session_id=uuid4(),
            tenant_id=uuid4(),
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
            session_id=uuid4(),
            tenant_id=uuid4(),
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
            session_id=uuid4(),
            tenant_id=uuid4(),
            output=output,
            new_messages=[_assistant_msg()],
        )

        assert result.action_kind == "confirm_requirements"
        assert result.new_planning_state_version == 3


# ---------------------------------------------------------------------------
# propose_plan — deferred until a proposal processor adapter is wired
# ---------------------------------------------------------------------------


class TestProposePlanDispatch:
    @pytest.mark.asyncio
    async def test_raises_not_implemented_and_does_not_write(self) -> None:
        repo = _mock_repo()
        output = parse_planner_output(_propose_plan_output_dict())

        with pytest.raises(NotImplementedError, match="propose_plan"):
            await dispatch_planner_action(
                repo=repo,
                session_id=uuid4(),
                tenant_id=uuid4(),
                output=output,
                new_messages=[_assistant_msg()],
            )

        repo.commit_turn.assert_not_awaited()


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
            session_id=uuid4(),
            tenant_id=uuid4(),
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
            session_id=uuid4(),
            tenant_id=uuid4(),
            output=output,
            new_messages=[_assistant_msg()],
        )

        _assert_commit_turn_kwargs_bounded(repo.commit_turn)


# ---------------------------------------------------------------------------
# Type-sanity
# ---------------------------------------------------------------------------


class TestTypeContracts:
    def test_session_id_and_tenant_id_are_keyword_only(self) -> None:
        """`session_id` and `tenant_id` must be keyword-only so callers
        can never swap their positions at a call site."""
        repo = _mock_repo()
        output = parse_planner_output(_ask_question_output_dict())

        with pytest.raises(TypeError):
            dispatch_planner_action(  # type: ignore[call-arg]
                repo,
                UUID(int=0),
                UUID(int=1),
                output,
                [_assistant_msg()],
            )
