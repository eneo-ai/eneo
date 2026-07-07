from __future__ import annotations

import pytest

from eneo.flows.ai_builder.ai_builder_create_feedback import (
    CREATE_CRITIC_REMEDIATION,
    CREATE_CRITIC_REMEDIATION_PASSTHROUGH_IDS,
    format_create_critic_feedback,
    format_create_intent_quality_feedback,
)
from eneo.flows.ai_builder.ai_builder_critic_invariants import (
    CRITIC_INVARIANTS,
    CriticIssue,
)

_CREATE_FEEDBACK_MECHANICS_TOKENS = (
    "input_source",
    "uses_previous_fields",
    "input_bindings",
    "{{ step_",
    "output_mode",
    "transcribe_only",
    "template_fill",
    "output_contract",
)


def test_format_create_intent_quality_feedback_translates_contract_terms_only() -> None:
    feedback = format_create_intent_quality_feedback(
        "Quality issues:\n"
        "1. Step has output_type 'json' but no output_contract. Adding one enables structured variable access for downstream steps."
    )

    assert feedback is not None
    assert "output_fields" in feedback
    assert "output_contract" not in feedback
    assert "Create-intent schema repair rules" not in feedback
    assert "For every JSON semantic step" not in feedback


@pytest.mark.parametrize(
    "issue_id",
    [
        "final_text_step_must_reference_relevant_structured_outputs",
    ],
)
def test_format_create_critic_feedback_translates_underlag_to_semantics(
    issue_id: str,
) -> None:
    feedback = format_create_critic_feedback(
        (
            CriticIssue(
                id=issue_id,
                kind="semantic",
                remediation="Raw remediation with input_source and uses_previous_fields.",
            ),
        )
    )

    assert feedback is not None
    assert "Quality issues" in feedback
    assert "semant" in feedback.casefold()
    assert "strukturerade" in feedback.casefold()
    for token in _CREATE_FEEDBACK_MECHANICS_TOKENS:
        assert token not in feedback


@pytest.mark.parametrize(
    "issue_id",
    [
        "rich_workflow_requires_json_contract_step",
        "structured_extraction_requires_json_contract_step",
    ],
)
def test_format_create_critic_feedback_names_outline_structured_fields(
    issue_id: str,
) -> None:
    feedback = format_create_critic_feedback(
        (
            CriticIssue(
                id=issue_id,
                kind="semantic",
                remediation="Raw remediation with output_contract.",
            ),
        )
    )

    assert feedback is not None
    assert 'output_type="json"' in feedback
    assert "output_fields" in feedback
    assert "output_contract" not in feedback


def test_format_create_critic_feedback_translates_simple_text_transform_restraint() -> (
    None
):
    feedback = format_create_critic_feedback(
        (
            CriticIssue(
                id="simple_text_transform_must_remain_single_step",
                kind="semantic",
                remediation="Raw remediation.",
            ),
        )
    )

    assert feedback is not None
    assert "direkt textomvandling" in feedback.casefold()
    assert "ett enda textsteg" in feedback.casefold()
    for token in _CREATE_FEEDBACK_MECHANICS_TOKENS:
        assert token not in feedback


def test_format_create_critic_feedback_translates_section_underlag_issue() -> None:
    feedback = format_create_critic_feedback(
        (
            CriticIssue(
                id="section_text_steps_must_reference_source_json_fields",
                kind="semantic",
                remediation="Raw remediation.",
            ),
        )
    )

    assert feedback is not None
    assert "varje avsnittssteg" in feedback.casefold()
    assert "namngivna fält" in feedback.casefold()
    assert "relevant underlag" in feedback.casefold()
    for token in _CREATE_FEEDBACK_MECHANICS_TOKENS:
        assert token not in feedback


def test_create_critic_feedback_covers_every_semantic_invariant() -> None:
    semantic_ids = {
        invariant.id for invariant in CRITIC_INVARIANTS if invariant.kind == "semantic"
    }
    covered_ids = set(CREATE_CRITIC_REMEDIATION) | set(
        CREATE_CRITIC_REMEDIATION_PASSTHROUGH_IDS
    )

    assert semantic_ids == covered_ids
    assert not (
        set(CREATE_CRITIC_REMEDIATION) & set(CREATE_CRITIC_REMEDIATION_PASSTHROUGH_IDS)
    )


def test_create_critic_feedback_remediations_do_not_leak_backend_mechanics() -> None:
    for remediation in CREATE_CRITIC_REMEDIATION.values():
        for token in _CREATE_FEEDBACK_MECHANICS_TOKENS:
            assert token not in remediation


@pytest.mark.parametrize(
    "issue_id",
    [
        "rich_workflow_requires_json_contract_step",
        "structured_extraction_requires_json_contract_step",
    ],
)
def test_semantic_critic_keeps_compiled_contract_remediation_for_edit_mode(
    issue_id: str,
) -> None:
    invariant = next(
        invariant for invariant in CRITIC_INVARIANTS if invariant.id == issue_id
    )

    assert "output_contract" in invariant.remediation
    assert "output_fields" not in invariant.remediation


def test_format_create_critic_feedback_passes_through_explicit_allowlist() -> None:
    remediation = "Välj bara MCP-verktyg när användarens namngivna MCP matchar."

    feedback = format_create_critic_feedback(
        (
            CriticIssue(
                id="mcp_selection_requires_semantic_support",
                kind="semantic",
                remediation=remediation,
            ),
        )
    )

    assert feedback is not None
    assert remediation in feedback


def test_format_create_critic_feedback_rejects_unregistered_semantic_issue() -> None:
    with pytest.raises(ValueError, match="No create-mode critic remediation"):
        format_create_critic_feedback(
            (
                CriticIssue(
                    id="not_registered",
                    kind="semantic",
                    remediation="Fix it.",
                ),
            )
        )


def test_format_create_critic_feedback_rejects_architecture_issue() -> None:
    with pytest.raises(ValueError, match="requires semantic issues"):
        format_create_critic_feedback(
            (
                CriticIssue(
                    id="json_input_rejects_all_previous_steps_source",
                    kind="architecture",
                    remediation="Fix mechanics.",
                ),
            )
        )
