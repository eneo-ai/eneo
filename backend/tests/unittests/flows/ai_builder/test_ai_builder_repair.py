from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from intric.flows.ai_builder.ai_builder_architecture_commit import (
    canonical_architecture_commit_payload,
)
from intric.flows.ai_builder.ai_builder_orchestrator import (
    PlannerOutput,
    RejectionReason,
)
from intric.flows.ai_builder.ai_builder_repair import (
    MAX_ORCHESTRATOR_REPAIR_RETRIES,
    MAX_PARSE_REPAIR_RETRIES,
    RepairOutcome,
    build_parse_repair_user_message,
    repair_planner_turn,
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


def _planner_output_json(
    *,
    kind: str = "confirm_requirements",
    architecture_commit: ArchitectureCommit | None = None,
) -> str:
    payload: dict[str, Any] = {
        "planning_state_delta": {
            "base_planning_state_version": 0,
            "signals_added": [],
            "slots_resolved": [],
            "architecture_commit": (
                canonical_architecture_commit_payload(architecture_commit)
                if architecture_commit is not None
                else None
            ),
        },
        "planner_action": {
            "kind": kind,
            "payload": _payload_for(kind),
        },
    }
    return json.dumps(payload)


def _payload_for(kind: str) -> dict[str, Any]:
    if kind == "ask_question":
        return {
            "question_id": "primary_runtime_input",
            "slot_name": "primary_runtime_input",
            "prompt": "What should the flow receive?",
        }
    if kind == "commit_architecture":
        return {"note": ""}
    if kind == "confirm_requirements":
        return {
            "summary": "Resolved requirements.",
            "key_decisions": [],
            "input_description": "",
            "output_description": "",
            "assumptions": [],
            "manual_setup_notes": [],
        }
    raise AssertionError(f"unsupported kind {kind}")


def _llm_response(raw_json: str) -> MagicMock:
    message = MagicMock(content=raw_json, tool_calls=None)
    return MagicMock(choices=[MagicMock(message=message, finish_reason="stop")])


def test_parse_repair_has_separate_single_retry_budget() -> None:
    assert MAX_PARSE_REPAIR_RETRIES == 1


def test_parse_repair_prompt_pins_raw_json_contract() -> None:
    content = build_parse_repair_user_message(
        parse_error_message="missing planner_action"
    )

    assert "single raw JSON object" in content
    assert "Do NOT wrap" in content
    assert "Do NOT add prose" in content
    assert "`architecture_commit: null`" in content
    assert "the server derives the architecture" in content


@pytest.mark.asyncio
async def test_version_mismatch_short_circuits_without_llm_call() -> None:
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
    llm.acompletion.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    [
        "architecture_commit_premature_unresolved_choices",
        "architecture_commit_missing_delta",
        "off_topic_question",
        "duplicate_question",
    ],
)
async def test_eligible_code_triggers_one_llm_call(code: str) -> None:
    llm = AsyncMock()
    llm.acompletion.return_value = _llm_response(_planner_output_json())

    outcome = await repair_planner_turn(
        litellm_client=llm,
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        base_messages=[{"role": "system", "content": "system prompt"}],
        failed_output_json=_planner_output_json(kind="ask_question"),
        rejection=RejectionReason(code=code, detail=f"detail for {code}"),
        prior_architecture_commit=None,
    )

    assert outcome.kind == "repaired"
    assert isinstance(outcome.repaired_output, PlannerOutput)
    llm.acompletion.assert_awaited_once()


@pytest.mark.asyncio
async def test_prompt_includes_rejection_detail_not_code() -> None:
    llm = AsyncMock()
    llm.acompletion.return_value = _llm_response(_planner_output_json())
    unique_detail = "question_id='x' already asked this session"
    rejection = RejectionReason(code="duplicate_question", detail=unique_detail)

    await repair_planner_turn(
        litellm_client=llm,
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        base_messages=[{"role": "system", "content": "system prompt"}],
        failed_output_json=_planner_output_json(kind="ask_question"),
        rejection=rejection,
        prior_architecture_commit=None,
    )

    content = llm.acompletion.await_args.kwargs["messages"][-1]["content"]
    assert unique_detail in content
    assert rejection.code not in content


@pytest.mark.asyncio
async def test_duplicate_question_prompt_forbids_repeating_question() -> None:
    llm = AsyncMock()
    llm.acompletion.return_value = _llm_response(
        _planner_output_json(kind="commit_architecture")
    )
    rejection = RejectionReason(
        code="duplicate_question",
        detail=(
            "question_id='runtime_metadata_fields' already asked this session "
            "and no new evidence arrived since"
        ),
    )

    await repair_planner_turn(
        litellm_client=llm,
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        base_messages=[{"role": "system", "content": "system prompt"}],
        failed_output_json=_planner_output_json(kind="ask_question"),
        rejection=rejection,
        prior_architecture_commit=None,
    )

    content = llm.acompletion.await_args.kwargs["messages"][-1]["content"]
    assert "Do NOT repeat the same `ask_question`" in content
    assert "latest user message" in content
    assert "different unresolved slot" in content


@pytest.mark.asyncio
async def test_missing_commit_delta_prompt_keeps_commit_server_derived() -> None:
    llm = AsyncMock()
    llm.acompletion.return_value = _llm_response(
        _planner_output_json(kind="commit_architecture")
    )
    rejection = RejectionReason(
        code="architecture_commit_missing_delta",
        detail="commit_architecture action requires a populated architecture_commit delta",
    )

    await repair_planner_turn(
        litellm_client=llm,
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        base_messages=[{"role": "system", "content": "system prompt"}],
        failed_output_json=_planner_output_json(kind="commit_architecture"),
        rejection=rejection,
        prior_architecture_commit=None,
    )

    content = llm.acompletion.await_args.kwargs["messages"][-1]["content"]
    assert "planning_state_delta.architecture_commit" in content
    assert "server derives" in content
    assert "Flow Capability Manifest" in content
    assert "architecture_hash" in content
    assert "committed_at" in content


@pytest.mark.asyncio
async def test_drift_in_architecture_body_blocks_repair() -> None:
    prior = _make_commit(architecture_hash="a" * 64)
    drifted = ArchitectureCommit(
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
        architecture_hash=prior.architecture_hash,
    )
    llm = AsyncMock()
    llm.acompletion.return_value = _llm_response(
        _planner_output_json(kind="commit_architecture", architecture_commit=drifted)
    )

    outcome = await repair_planner_turn(
        litellm_client=llm,
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        base_messages=[{"role": "system", "content": "system prompt"}],
        failed_output_json=_planner_output_json(kind="ask_question"),
        rejection=RejectionReason(
            code="duplicate_question",
            detail="question_id='x' already asked",
        ),
        prior_architecture_commit=prior,
    )

    assert outcome.kind == "commit_drift_blocked"
    assert outcome.drift_rejection is not None
    assert outcome.drift_rejection.code == "repair_attempted_commit_drift"


@pytest.mark.asyncio
async def test_omitted_commit_after_prior_commit_is_preservation_by_absence() -> None:
    prior = _make_commit(architecture_hash="a" * 64)
    llm = AsyncMock()
    llm.acompletion.return_value = _llm_response(_planner_output_json())

    outcome = await repair_planner_turn(
        litellm_client=llm,
        litellm_model="openai/gpt-5.4",
        litellm_kwargs={},
        base_messages=[{"role": "system", "content": "system prompt"}],
        failed_output_json=_planner_output_json(kind="ask_question"),
        rejection=RejectionReason(
            code="duplicate_question",
            detail="question_id='x' already asked",
        ),
        prior_architecture_commit=prior,
    )

    assert outcome.kind == "repaired"
    assert outcome.repaired_output is not None
    assert outcome.repaired_output.planning_state_delta.architecture_commit is None


def test_max_orchestrator_repair_retries_is_three() -> None:
    assert MAX_ORCHESTRATOR_REPAIR_RETRIES == 3


def test_module_exports() -> None:
    from intric.flows.ai_builder import ai_builder_repair

    for symbol in (
        "MAX_ORCHESTRATOR_REPAIR_RETRIES",
        "RepairOutcome",
        "repair_planner_turn",
    ):
        assert hasattr(ai_builder_repair, symbol)
