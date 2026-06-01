from __future__ import annotations

from intric.flows.ai_builder.ai_builder_result_contract import (
    derive_result_contract,
    render_result_contract_prompt_block,
)
from intric.flows.ai_builder.planning_state import PlanningState, ResolvedSlot
from intric.flows.ai_builder.question_catalog import legal_slot_values

_GOAL_SIGNATURES = {
    "stop_after_primary_operation": "Stop after the primary operation",
    "summarize_or_overview": "Brief summary",
    "extract_key_information": "Extracted key information",
    "structure_key_information": "Structured source-grounded notes",
    "action_followup": "Mark missing owners, deadlines, and responsibilities",
    "decision_support": "Options or recommendations",
    "risk_or_issue_review": "Risks, issues, or deviations",
    "compare_or_validate": "Comparison or validation basis",
}


def _state_with_slots(**slots: str) -> PlanningState:
    return PlanningState.empty().model_copy(
        update={
            "resolved_slots": {
                name: ResolvedSlot(
                    name=name,
                    value=value,
                    source="structured_answer",
                    confidence="high",
                )
                for name, value in slots.items()
            }
        },
        deep=True,
    )


def test_result_contract_covers_every_post_processing_goal_value() -> None:
    assert set(_GOAL_SIGNATURES) == legal_slot_values("post_processing_goal")

    for value in legal_slot_values("post_processing_goal"):
        contract = derive_result_contract(
            _state_with_slots(post_processing_goal=value)
        )

        assert contract is not None
        assert contract.post_processing_goal == value
        assert contract.required_sections or contract.result_policies
        rendered = render_result_contract_prompt_block(contract)
        assert rendered is not None
        assert _GOAL_SIGNATURES[value] in rendered


def test_result_contract_action_followup_requires_missing_value_policy() -> None:
    contract = derive_result_contract(
        _state_with_slots(
            post_processing_goal="action_followup",
            terminal_output="docx_document",
        )
    )

    assert contract is not None
    assert "Decisions" in contract.required_sections
    assert "Deadlines" in contract.required_sections
    rendered = render_result_contract_prompt_block(contract)
    assert rendered is not None
    assert "Mark missing owners, deadlines, and responsibilities as unspecified" in rendered
    assert "final document step should render completed content" in rendered


def test_result_contract_returns_none_without_relevant_slots() -> None:
    assert derive_result_contract(PlanningState.empty()) is None
