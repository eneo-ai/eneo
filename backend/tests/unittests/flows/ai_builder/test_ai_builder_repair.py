"""Contract tests for the single-pass planner repair helper.

The helper `repair_planner_turn` is a pure async function that takes a
rejected `PlannerOutput` + `RejectionReason` and asks the LLM to emit a
corrective JSON product. It does NOT hold the retry budget itself — the
outer `send_message` loop (shipping with the transport migration) owns
the multi-attempt bookkeeping. Per-call it returns exactly one
`RepairOutcome`:

- `not_repairable` when the rejection code is outside the
  `_REPAIR_ELIGIBLE_CODES` set (LLM not called).
- `repaired` when the LLM returned a `PlannerOutput` whose architecture
  commit, if any, still matches the session's prior commit hash.
- `commit_drift_blocked` when the LLM's repaired output either
  mutates the prior `architecture_hash` or drops the commit entirely
  after a prior commit existed. Budget is NOT decremented in this
  branch — drift is a hard failure, not a retry candidate.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from intric.flows.ai_builder.ai_builder_orchestrator import (
    PlannerOutput,
    RejectionReason,
)
from intric.flows.ai_builder.planning_state import ArchitectureCommit, StepTriple


def _make_commit(*, architecture_hash: str) -> ArchitectureCommit:
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
        architecture_hash=architecture_hash,
    )


def _make_planner_output_json(
    *,
    architecture_commit: ArchitectureCommit | None,
    kind: str = "propose_plan",
    base_version: int = 0,
) -> str:
    """Build a minimally-valid PlannerOutput JSON string.

    The helper's parse path accepts this string verbatim; if the
    schema drifts under us, parse will raise and the tests will fail
    loud rather than silently routing the wrong shape.
    """
    payload: dict[str, Any] = {
        "planning_state_delta": {
            "base_planning_state_version": base_version,
            "signals_added": [],
            "slots_resolved": [],
            "architecture_commit": (
                architecture_commit.model_dump(mode="json")
                if architecture_commit is not None
                else None
            ),
            "draft_plan": {
                "plan_id": "plan-42",
                "steps": [{"step_ix": 0}],
                "form_fields": [],
            },
        },
        "planner_action": {
            "kind": kind,
            "payload": (
                {"plan_reference": "latest"} if kind == "propose_plan" else {"note": ""}
            ),
        },
    }
    return json.dumps(payload)


def _llm_response(raw_json: str) -> MagicMock:
    """Shape a litellm-style chat.completions response."""
    message = MagicMock(content=raw_json, tool_calls=None)
    return MagicMock(choices=[MagicMock(message=message, finish_reason="stop")])


class TestNotRepairable:
    @pytest.mark.asyncio
    async def test_version_mismatch_short_circuits_without_llm_call(self) -> None:
        from intric.flows.ai_builder.ai_builder_repair import (
            RepairOutcome,
            repair_planner_turn,
        )

        llm = AsyncMock()
        rejection = RejectionReason(
            code="version_mismatch",
            detail="planner sent base_planning_state_version=3, session is at 5",
            current_version=5,
        )
        outcome = await repair_planner_turn(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system prompt"}],
            failed_output_json="{}",
            rejection=rejection,
            prior_architecture_commit=None,
        )
        assert isinstance(outcome, RepairOutcome)
        assert outcome.kind == "not_repairable"
        assert outcome.repaired_output is None
        assert outcome.drift_rejection is None
        llm.acompletion.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_duplicate_question_is_not_repair_eligible(self) -> None:
        from intric.flows.ai_builder.ai_builder_repair import (
            repair_planner_turn,
        )

        llm = AsyncMock()
        rejection = RejectionReason(
            code="duplicate_question",
            detail="planner re-asked input_material_mode without new evidence",
        )
        outcome = await repair_planner_turn(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system prompt"}],
            failed_output_json="{}",
            rejection=rejection,
            prior_architecture_commit=None,
        )
        assert outcome.kind == "not_repairable"
        llm.acompletion.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_architecture_commit_rejection_is_not_repair_eligible(self) -> None:
        """Per the intent doc, only propose_plan_* rejections are
        repair-eligible in this slice. Architecture commit rejections
        indicate the planner misunderstood the constraint surface, not
        that the plan shape drifted; they need a fresh turn, not a
        corrective loop."""
        from intric.flows.ai_builder.ai_builder_repair import (
            repair_planner_turn,
        )

        llm = AsyncMock()
        rejection = RejectionReason(
            code="architecture_commit_illegal_tuple",
            detail="tuple #0 (text → pdf, pass_through) not supported by FCM",
        )
        outcome = await repair_planner_turn(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system prompt"}],
            failed_output_json="{}",
            rejection=rejection,
            prior_architecture_commit=None,
        )
        assert outcome.kind == "not_repairable"
        llm.acompletion.assert_not_awaited()


class TestRepairEligibleCodes:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "code",
        [
            "propose_plan_without_architecture_commit",
            "propose_plan_missing_draft_plan",
            "propose_plan_draft_plan_structural_mismatch",
        ],
    )
    async def test_eligible_code_triggers_one_llm_call(self, code: str) -> None:
        from intric.flows.ai_builder.ai_builder_repair import (
            repair_planner_turn,
        )

        commit = _make_commit(architecture_hash="a" * 64)
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _make_planner_output_json(architecture_commit=commit)
        )
        rejection = RejectionReason(code=code, detail=f"detail for {code}")
        outcome = await repair_planner_turn(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system prompt"}],
            failed_output_json=_make_planner_output_json(architecture_commit=commit),
            rejection=rejection,
            prior_architecture_commit=commit,
        )
        assert outcome.kind == "repaired"
        assert outcome.repaired_output is not None
        assert isinstance(outcome.repaired_output, PlannerOutput)
        llm.acompletion.assert_awaited_once()


class TestRepairPromptShape:
    @pytest.mark.asyncio
    async def test_prompt_includes_rejection_detail_not_code(self) -> None:
        """The rejection `code` is internal vocabulary and must not
        reach the planner LLM; `detail` is the human-grade explanation
        and is what the LLM consumes."""
        from intric.flows.ai_builder.ai_builder_repair import (
            repair_planner_turn,
        )

        commit = _make_commit(architecture_hash="a" * 64)
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _make_planner_output_json(architecture_commit=commit)
        )
        unique_detail = "step count on draft_plan (2) differs from tuples_chain (3)"
        rejection = RejectionReason(
            code="propose_plan_draft_plan_structural_mismatch",
            detail=unique_detail,
        )
        await repair_planner_turn(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system prompt"}],
            failed_output_json=_make_planner_output_json(architecture_commit=commit),
            rejection=rejection,
            prior_architecture_commit=commit,
        )
        sent_messages = llm.acompletion.await_args.kwargs["messages"]
        last_message = sent_messages[-1]
        assert last_message["role"] == "user"
        assert unique_detail in last_message["content"]
        assert rejection.code not in last_message["content"], (
            "rejection code is internal vocabulary; the planner sees detail only"
        )

    @pytest.mark.asyncio
    async def test_prompt_instructs_preserve_committed_architecture(self) -> None:
        from intric.flows.ai_builder.ai_builder_repair import (
            repair_planner_turn,
        )

        commit = _make_commit(architecture_hash="a" * 64)
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _make_planner_output_json(architecture_commit=commit)
        )
        rejection = RejectionReason(
            code="propose_plan_missing_draft_plan",
            detail="propose_plan delta lacked draft_plan after commit",
        )
        await repair_planner_turn(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system prompt"}],
            failed_output_json=_make_planner_output_json(architecture_commit=commit),
            rejection=rejection,
            prior_architecture_commit=commit,
        )
        sent_messages = llm.acompletion.await_args.kwargs["messages"]
        last_message = sent_messages[-1]
        assert "committed architecture" in last_message["content"].lower(), (
            "repair prompt must remind the LLM the committed architecture "
            "is pinned and must not drift"
        )

    @pytest.mark.asyncio
    async def test_prompt_echoes_failed_output_for_the_planner_to_see(self) -> None:
        from intric.flows.ai_builder.ai_builder_repair import (
            repair_planner_turn,
        )

        commit = _make_commit(architecture_hash="a" * 64)
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _make_planner_output_json(architecture_commit=commit)
        )
        rejection = RejectionReason(
            code="propose_plan_missing_draft_plan",
            detail="propose_plan delta lacked draft_plan after commit",
        )
        failed_json = _make_planner_output_json(architecture_commit=commit)
        await repair_planner_turn(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system prompt"}],
            failed_output_json=failed_json,
            rejection=rejection,
            prior_architecture_commit=commit,
        )
        sent_messages = llm.acompletion.await_args.kwargs["messages"]
        assistant_echoes = [msg for msg in sent_messages if msg["role"] == "assistant"]
        assert assistant_echoes, (
            "repair loop must echo the failed output back as an assistant "
            "turn so the LLM sees what was rejected"
        )
        assert failed_json in assistant_echoes[-1]["content"]


class TestCommitDriftBlocked:
    @pytest.mark.asyncio
    async def test_drift_in_architecture_hash_blocks_repair(self) -> None:
        from intric.flows.ai_builder.ai_builder_repair import (
            repair_planner_turn,
        )

        prior = _make_commit(architecture_hash="a" * 64)
        drifted = _make_commit(architecture_hash="b" * 64)
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _make_planner_output_json(architecture_commit=drifted)
        )
        rejection = RejectionReason(
            code="propose_plan_missing_draft_plan",
            detail="propose_plan delta lacked draft_plan after commit",
        )
        outcome = await repair_planner_turn(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system prompt"}],
            failed_output_json=_make_planner_output_json(architecture_commit=prior),
            rejection=rejection,
            prior_architecture_commit=prior,
        )
        assert outcome.kind == "commit_drift_blocked"
        assert outcome.repaired_output is None
        assert outcome.drift_rejection is not None
        assert outcome.drift_rejection.code == "repair_attempted_commit_drift"
        assert "architecture_hash" in outcome.drift_rejection.detail

    @pytest.mark.asyncio
    async def test_dropping_commit_after_prior_commit_blocks_repair(self) -> None:
        """If the prior turn had a commit and the repaired output no
        longer carries one, the planner attempted to abandon the
        committed architecture — same drift class."""
        from intric.flows.ai_builder.ai_builder_repair import (
            repair_planner_turn,
        )

        prior = _make_commit(architecture_hash="a" * 64)
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _make_planner_output_json(architecture_commit=None)
        )
        rejection = RejectionReason(
            code="propose_plan_missing_draft_plan",
            detail="propose_plan delta lacked draft_plan after commit",
        )
        outcome = await repair_planner_turn(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system prompt"}],
            failed_output_json=_make_planner_output_json(architecture_commit=prior),
            rejection=rejection,
            prior_architecture_commit=prior,
        )
        assert outcome.kind == "commit_drift_blocked"
        assert outcome.drift_rejection is not None
        assert outcome.drift_rejection.code == "repair_attempted_commit_drift"

    @pytest.mark.asyncio
    async def test_matching_hash_with_mutated_body_is_blocked_as_drift(self) -> None:
        """The architecture_hash is planner-supplied and the server
        does NOT rebind it to the commit body at repair time. A
        matching hash whose `tuples_chain` / `chosen_patterns` /
        `required_capabilities` / `committed_at` differ from the prior
        is a forgery, not a preserved commit, and the helper must
        treat it as drift."""
        from intric.flows.ai_builder.ai_builder_repair import (
            repair_planner_turn,
        )

        shared_hash = "a" * 64
        prior = _make_commit(architecture_hash=shared_hash)
        # Same hash, but mutated tuples_chain (swapped output_type).
        mutated = ArchitectureCommit(
            tuples_chain=[
                StepTriple(
                    input_type="text",
                    output_type="json",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=prior.chosen_patterns,
            required_capabilities=prior.required_capabilities,
            committed_at=prior.committed_at,
            architecture_hash=shared_hash,
        )
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _make_planner_output_json(architecture_commit=mutated)
        )
        rejection = RejectionReason(
            code="propose_plan_missing_draft_plan",
            detail="propose_plan delta lacked draft_plan after commit",
        )
        outcome = await repair_planner_turn(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system prompt"}],
            failed_output_json=_make_planner_output_json(architecture_commit=prior),
            rejection=rejection,
            prior_architecture_commit=prior,
        )
        assert outcome.kind == "commit_drift_blocked"
        assert outcome.drift_rejection is not None
        assert outcome.drift_rejection.code == "repair_attempted_commit_drift"
        assert "mutated the commit body" in outcome.drift_rejection.detail

    @pytest.mark.asyncio
    async def test_adding_commit_when_prior_was_none_is_not_drift(self) -> None:
        """If the session had no prior commit, the repaired output may
        introduce one — that is the commit_architecture path, not
        drift. Drift is specifically about mutating or dropping an
        existing commit."""
        from intric.flows.ai_builder.ai_builder_repair import (
            repair_planner_turn,
        )

        new_commit = _make_commit(architecture_hash="c" * 64)
        llm = AsyncMock()
        llm.acompletion.return_value = _llm_response(
            _make_planner_output_json(architecture_commit=new_commit)
        )
        rejection = RejectionReason(
            code="propose_plan_without_architecture_commit",
            detail="propose_plan requires an architecture_commit on the delta",
        )
        outcome = await repair_planner_turn(
            litellm_client=llm,
            litellm_model="openai/gpt-5.4",
            litellm_kwargs={},
            base_messages=[{"role": "system", "content": "system prompt"}],
            failed_output_json=_make_planner_output_json(architecture_commit=None),
            rejection=rejection,
            prior_architecture_commit=None,
        )
        assert outcome.kind == "repaired"
        assert outcome.repaired_output is not None


class TestRepairBudgetConstant:
    def test_max_orchestrator_repair_retries_is_three(self) -> None:
        """The budget is a module-level Final the outer retry loop
        imports. Locked to 3 per the intent doc — deliberately
        distinct from the proposal processor's own retry budget so one
        loop's retries never eat the other's."""
        from intric.flows.ai_builder.ai_builder_repair import (
            MAX_ORCHESTRATOR_REPAIR_RETRIES,
        )

        assert MAX_ORCHESTRATOR_REPAIR_RETRIES == 3


class TestPublicSurface:
    def test_module_exports(self) -> None:
        from intric.flows.ai_builder import ai_builder_repair

        for symbol in (
            "MAX_ORCHESTRATOR_REPAIR_RETRIES",
            "RepairOutcome",
            "repair_planner_turn",
        ):
            assert hasattr(ai_builder_repair, symbol), (
                f"public surface must expose {symbol} — consumed by "
                "the outer send_message loop in the upcoming transport "
                "migration slice"
            )


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-x", "-v"])
