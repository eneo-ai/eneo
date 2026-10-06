from __future__ import annotations

import re
from typing import Final

from eneo.flows.ai_builder.ai_builder_discovery_families import (
    family_for_issue,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import DiscoveryProfile
from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_phrase,
    contains_any_token_prefix,
)
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    ResolvedSlotClassificationOutcome,
    SlotClassificationResult,
)

EXTERNAL_DELIVERY_UNSUPPORTED_ISSUE_ID: Final = "external_delivery_unsupported"


def question_category(question_id: str) -> str:
    return {
        "primary_runtime_input": "input",
        "mapped_file_limit": "input",
        "flow_input_architecture": "input",
        "document_material_scope": "input",
        "post_processing_goal": "outcome",
        "structured_io_contract": "outcome",
        "comparison_scope": "comparison",
        "terminal_output": "output",
        "docx_output_mode": "output",
        "pdf_generation_mode": "output",
        "report_disposition": "output",
        "runtime_metadata_fields": "input",
    }.get(question_id, "output")


_EXTERNAL_DELIVERY_ACTION_RE = re.compile(
    r"(?<![\w-])(?:"
    r"anropa|anropar|skicka|skickar|posta|postar|"
    r"send|sends|deliver|delivers|post|posts"
    r")(?![\w-])",
    re.IGNORECASE,
)
_EXTERNAL_DELIVERY_DESTINATION_RE = re.compile(
    r"(?<![\w-])(?:api|webhook)(?![\w-])|"
    r"\bexternal\s+(?:system|api|integration)\b|"
    r"\bexternt\s+(?:system|api)\b|"
    r"\bextern\s+integration\b",
    re.IGNORECASE,
)


def external_delivery_requested(profile: DiscoveryProfile) -> bool:
    return bool(
        _EXTERNAL_DELIVERY_ACTION_RE.search(profile.text)
        and _EXTERNAL_DELIVERY_DESTINATION_RE.search(profile.text)
    )


def _family_inactive(profile: DiscoveryProfile, question_id: str) -> bool:
    if not profile.edit_mode:
        return False
    family = family_for_issue(question_id)
    if family is None:
        return False
    return family not in profile.edit_scope.active_families


def post_processing_goal_is_vague(
    profile: DiscoveryProfile,
    *,
    slot_classification_result: SlotClassificationResult | None = None,
) -> bool:
    if _family_inactive(profile, "post_processing_goal"):
        return False
    # Ask on the same grade the answer is used on. A purpose resolved below
    # commit grade is a guess: architecture derivation and the result
    # contract already refuse to read it, so leaving the question unasked
    # spends the turn on a downstream slot like terminal_output while the
    # purpose the whole flow is shaped around stays unknown.
    committed_purpose = profile.planning_state.commit_grade_slot_value(
        "post_processing_goal"
    )
    if committed_purpose is not None:
        return False
    if needs_pdf_generation_mode_choice(profile):
        return False
    if _json_to_json_semantic_flow(profile):
        return False

    if slot_classification_result is not None:
        outcomes = slot_classification_result.slot_outcomes
        if isinstance(
            outcomes.get("post_processing_goal"), ResolvedSlotClassificationOutcome
        ):
            # The classifier did try to place the purpose and the commit-grade
            # gate above still found it unsettled, so what it placed is a
            # guess and the question is still owed.
            return True
        # Without a purpose classification, only a turn the classifier could
        # read at all is worth spending the purpose question on.
        return any(
            isinstance(outcome, ResolvedSlotClassificationOutcome)
            for outcome in outcomes.values()
        )

    return _post_processing_goal_classifier_outage_requires_question(profile)


def _post_processing_goal_classifier_outage_requires_question(
    profile: DiscoveryProfile,
) -> bool:
    return (
        profile.audio_like_input
        or profile.document_like_input
        or profile.final_output_text_or_docx
    )


def _json_to_json_semantic_flow(profile: DiscoveryProfile) -> bool:
    return (
        profile.input_intent.primary_runtime_input == "json"
        and profile.output_intent.terminal_output == "structured_json"
    )


def needs_pdf_generation_mode_choice(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "pdf_generation_mode"):
        return False
    intent = profile.output_intent
    return (
        intent.terminal_output == "pdf_document"
        and intent.pdf_generation_mode == "pdf_template_requested"
    )


def has_same_run_comparison_contradiction(
    text: str,
    answers: dict[str, set[str]],
) -> bool:
    if not contains_any_token_prefix(
        text, ("compare", "jämför", "jämföra", "jämförelse")
    ):
        return False

    says_single_file = contains_any_phrase(
        text,
        (
            "one file per run",
            "one pdf per run",
            "en fil per körning",
            "en pdf per körning",
            "1 pdf per run",
            "1 pdf laddas upp vid varje körning",
        ),
    )
    says_same_run_compare = contains_any_phrase(
        text,
        (
            "same run",
            "samma körning",
            "always compare multiple documents",
            "alltid jämföra flera dokument",
            "compare several documents together",
        ),
    )

    answer_texts = " ".join(value for values in answers.values() for value in values)
    if contains_any_phrase(
        answer_texts,
        (
            "same_run_compare",
            "multiple_documents_case",
            "flexible_document_case",
            "compare_previous_material",
            "no_direct_compare",
        ),
    ):
        return False

    if contains_any_phrase(
        text,
        (
            "ladda upp flera pdf",
            "ladda upp flera pdf:er",
            "ladda upp flera dokument",
            "upload multiple pdf",
            "upload several pdf",
            "upload multiple documents",
        ),
    ):
        return False

    return says_single_file and says_same_run_compare


def mixed_input_architecture_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "flow_input_architecture"):
        return False
    # The user's own choice already cleared the intent, so answer presence is
    # not a second thing to check — an answer the question never offered must
    # not silence it.
    return profile.input_intent.needs_architecture_clarification
