from __future__ import annotations

import pytest

from intric.flows.ai_builder.ai_builder_create_feedback import (
    CREATE_CRITIC_REMEDIATION,
    CREATE_CRITIC_REMEDIATION_PASSTHROUGH_IDS,
    format_create_critic_feedback,
    format_create_quality_feedback,
    format_create_validation_feedback,
)
from intric.flows.ai_builder.ai_builder_critic_invariants import (
    CRITIC_INVARIANTS,
    CriticIssue,
)
from intric.flows.ai_builder.ai_builder_validation_common import SpecValidationResult

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


def test_format_create_validation_feedback_adds_first_step_source_rule() -> None:
    validation = SpecValidationResult()
    validation.add_error(
        step_ref="step_a",
        code="first_step_invalid_source",
        message="Step 1 must use flow_input.",
    )

    feedback = format_create_validation_feedback(validation)

    assert "Create draft validation failed" in feedback
    assert "runtime entry step" in feedback
    assert "committed architecture" in feedback


def test_format_create_validation_feedback_adds_json_all_previous_steps_rule() -> None:
    validation = SpecValidationResult()
    validation.add_error(
        step_ref="step_b",
        code="json_incompatible_with_all_previous_steps",
        message=(
            "input_type 'json' is incompatible with input_source 'all_previous_steps'."
        ),
    )

    feedback = format_create_validation_feedback(validation)

    assert "Create draft validation failed" in feedback
    assert "Outline-flow repair rules" in feedback
    assert "semantic extraction and synthesis steps" in feedback
    assert "server-owned fan-in" in feedback


def test_format_create_quality_feedback_adds_terminal_artifact_rule() -> None:
    feedback = format_create_quality_feedback(
        "Du har valt DOCX som slutartefakt men sista steget producerar inte DOCX."
    )

    assert feedback is not None
    assert "Outline-flow quality repair rules" in feedback
    assert "final step output_type to 'docx'" in feedback


def test_format_create_quality_feedback_does_not_redirect_input_source_authoring() -> (
    None
):
    feedback = format_create_quality_feedback(
        "Det sista steget har "
        '`input_source="all_previous_steps"` trots att tidigare steg producerar JSON.'
    )

    assert feedback is not None
    assert "Outline-flow quality repair rules" not in feedback
    assert "let the backend compile the dataflow" not in feedback
    assert "do not author input_source" not in feedback.casefold()


@pytest.mark.parametrize(
    "issue_id",
    [
        "prefer_targeted_underlag_over_all_previous_steps",
        "final_text_step_must_reference_relevant_structured_outputs",
    ],
)
def test_format_create_critic_feedback_translates_mechanics_to_semantics(
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
