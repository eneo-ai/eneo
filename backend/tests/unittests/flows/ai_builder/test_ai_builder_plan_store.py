from __future__ import annotations

from types import SimpleNamespace

from intric.flows.ai_builder.ai_builder_domain_models import LintSeverity, LintWarning
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    ConversationMessage,
    FlowDraftSpecCore,
    InputSource,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_plan_store import (
    append_plan_messages,
    build_lint_warnings,
)


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
