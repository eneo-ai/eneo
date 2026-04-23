from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_create_tool_schema import CREATE_FLOW_TOOL_NAME
from intric.flows.ai_builder.ai_builder_domain_models import LintSeverity, LintWarning
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    ConversationMessage,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    MCPPolicy,
    OutputMode,
    OutputType,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_plan_store import (
    append_plan_messages,
    build_lint_warnings,
    store_plan_and_update_conversation,
)
from intric.flows.ai_builder.planning_state import PlanningState


def test_build_lint_warnings_hides_internal_info_level_quality_lints() -> None:
    validation = SimpleNamespace(
        warnings=[
            LintWarning(
                step_ref="step_d",
                code="json_output_text_interpolation",
                message=(
                    "Underlag interpolates output.text from a JSON-producing step. "
                    "Prefer output.structured.<field> when only specific fields are needed."
                ),
                severity=LintSeverity.INFO,
            ),
            LintWarning(
                step_ref="step_e",
                code="all_previous_overuse",
                message="Too many steps use all_previous_steps.",
                severity=LintSeverity.WARNING,
            ),
        ]
    )

    visible_warnings = build_lint_warnings(validation)

    assert visible_warnings == [
        LintWarning(
            step_ref="step_e",
            code="all_previous_overuse",
            message="Too many steps use all_previous_steps.",
            severity=LintSeverity.WARNING,
        )
    ]


def test_append_plan_messages_uses_active_submission_tool_name() -> None:
    conversation: list[ConversationMessage] = []
    spec = FlowDraftSpecCore(
        flow_name="Kommunärende",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Extrahera",
                assistant_spec=AssistantSpec(instructions="Extrahera."),
                input_source=InputSource.FLOW_INPUT,
            )
        ],
    )

    append_plan_messages(
        conversation=conversation,
        assistant_content="Här är planen.",
        tool_call_id="call_create",
        tool_name="create_flow",
        arguments={"plan_rationale": "Struktur först."},
        spec=spec,
        assumptions=["Antagande"],
    )

    assert conversation[0].tool_calls is not None
    assert conversation[0].tool_calls[0]["name"] == "create_flow"


@asynccontextmanager
async def _noop_savepoint() -> AsyncIterator[None]:
    yield


def _make_repo_mock() -> AsyncMock:
    repo = AsyncMock()
    repo.savepoint = _noop_savepoint
    repo.append_session_messages = AsyncMock(return_value=[])
    repo.create_plan = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    return repo


def _make_turn_spec() -> FlowDraftSpecCore:
    return FlowDraftSpecCore(
        flow_name="Unit plan",
        flow_description="Unit plan description",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                existing_step_ref=None,
                name="Step A",
                assistant_spec=AssistantSpec(instructions="Do work."),
                mcp_policy=MCPPolicy.INHERIT,
                input_source=InputSource.FLOW_INPUT,
                input_type=InputType.TEXT,
                output_mode=OutputMode.PASS_THROUGH,
                output_type=OutputType.TEXT,
            )
        ],
    )


@pytest.mark.asyncio
async def test_store_plan_and_update_conversation_saves_planning_state_inside_savepoint() -> (
    None
):
    repo = _make_repo_mock()
    spec = _make_turn_spec()

    await store_plan_and_update_conversation(
        repo=repo,
        tenant_id=uuid4(),
        session_id=uuid4(),
        conversation=[],
        new_messages_start=0,
        assistant_content="plan ready",
        tool_call_id="call-unit-1",
        tool_name=CREATE_FLOW_TOOL_NAME,
        arguments={},
        spec=spec,
        assumptions=[],
        plan_rationale=None,
        reasoning=None,
        validation=MagicMock(warnings=[]),
    )

    repo.save_planning_state.assert_awaited_once()
    assert repo.save_planning_state.await_args is not None
    saved_state = repo.save_planning_state.await_args.kwargs["state"]
    assert isinstance(saved_state, PlanningState)
    assert saved_state.draft_plan_id == repo.create_plan.return_value.id
    assert saved_state.phase == "plan_proposed"
