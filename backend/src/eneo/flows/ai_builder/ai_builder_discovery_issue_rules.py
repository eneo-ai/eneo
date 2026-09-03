from __future__ import annotations

import re
from typing import Final

from eneo.flows.ai_builder.ai_builder_discovery_families import (
    family_for_issue,
)
from eneo.flows.ai_builder.ai_builder_discovery_models import DiscoveryProfile
from eneo.flows.ai_builder.ai_builder_discovery_profile_builder import (
    expresses_task_intent,
)
from eneo.flows.ai_builder.ai_builder_discovery_signal_inference import (
    infer_structured_io_contract,
)
from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_phrase,
    contains_any_token_prefix,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_framework_policy import (
    canonical_question_id,
    latest_pending_structured_question,
    mentions_output_change,
    mentions_runtime_metadata,
)
from eneo.flows.ai_builder.ai_builder_slot_classification_contract import (
    UNKNOWN_SLOT_VALUE,
    SlotClassificationResult,
)

EXTERNAL_DELIVERY_UNSUPPORTED_ISSUE_ID: Final = "external_delivery_unsupported"


def implies_single_primary_document(text: str) -> bool:
    if contains_any_phrase(
        text,
        (
            "flera dokument",
            "multiple documents",
            "several documents",
            "document package",
            "dokumentpaket",
        ),
    ):
        return False
    return contains_any_phrase(
        text,
        (
            "underlag som pdf",
            "ett huvuddokument",
            "ett dokument",
            "en pdf",
            "one document",
            "one pdf",
            "uploaded pdf",
        ),
    )


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


def latest_pending_question_id(
    conversation: list[ConversationMessage],
) -> str | None:
    payload = latest_pending_structured_question(conversation)
    if not isinstance(payload, dict):
        return None
    question_id = payload.get("question_id")
    return canonical_question_id(question_id) if isinstance(question_id, str) else None


def _family_inactive(profile: DiscoveryProfile, question_id: str) -> bool:
    if not profile.edit_mode:
        return False
    family = family_for_issue(question_id)
    if family is None:
        return False
    return family not in profile.edit_scope.active_families


def primary_runtime_input_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "primary_runtime_input"):
        return False
    if "primary_runtime_input" in profile.answers:
        return False
    if profile.input_intent.needs_architecture_clarification:
        return False
    return profile.input_intent.primary_runtime_input == "unknown"


def terminal_output_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "terminal_output"):
        return False
    text = profile.text
    if profile.output_intent.terminal_output is not None:
        return False
    if external_delivery_requested(profile):
        return False
    if mentions_output_change(text):
        return False
    if profile.flow_defaults.get("terminal_output"):
        return False
    if (
        profile.document_like_input
        or profile.audio_like_input
        or profile.final_output_text_or_docx
    ):
        return True
    if "terminal_output" not in profile.answers and expresses_task_intent(text):
        return True
    return contains_any_phrase(
        text,
        (
            "report",
            "reports",
            "rapport",
            "rapporten",
            "rapporter",
            "rapporterna",
            "summary",
            "summaries",
            "sammanfattning",
            "sammanfattningen",
            "sammanfattningar",
            "output",
            "outputs",
            "resultat",
            "resultatet",
            "resultaten",
            "slutresultat",
            "slutresultatet",
            "slutresultaten",
            "generate",
            "generates",
            "generated",
            "generating",
            "generera",
            "genererar",
            "genererade",
        ),
    )


def ultra_vague_terminal_output_choice_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "terminal_output"):
        return False
    if profile.output_intent.terminal_output is not None:
        return False
    if "terminal_output" in profile.answers:
        return False
    if profile.flow_defaults.get("terminal_output"):
        return False
    if profile.comparison_requested:
        return False
    if len(profile.text.split()) > 7:
        return False
    if contains_any_phrase(
        profile.text,
        (
            "pdf",
            "docx",
            "word",
            "json",
            "rapport",
            "report",
            "text summary",
            "textsammanfattning",
            "sammanfattning som text",
        ),
    ):
        return False
    if not contains_any_token_prefix(
        profile.text,
        (
            "sammanfatt",
            "summarize",
            "analysera",
            "analyze",
            "extrahera",
            "extract",
            "process",
            "bearbeta",
        ),
    ):
        return False
    return profile.document_like_input or profile.audio_like_input


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
        classified_slots = slot_classification_result.slots
        if any(slot.slot_name == "post_processing_goal" for slot in classified_slots):
            # The classifier did try to place the purpose and the commit-grade
            # gate above still found it unsettled, so what it placed is a
            # guess and the question is still owed.
            return True
        # Without a purpose classification, only a turn the classifier could
        # read at all is worth spending the purpose question on.
        return any(slot.value != UNKNOWN_SLOT_VALUE for slot in classified_slots)

    return _post_processing_goal_classifier_outage_requires_question(profile)


def _post_processing_goal_classifier_outage_requires_question(
    profile: DiscoveryProfile,
) -> bool:
    return (
        profile.audio_like_input
        or profile.document_like_input
        or profile.final_output_text_or_docx
    )


def structured_io_contract_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "structured_io_contract"):
        return False
    if not _json_to_json_semantic_flow(profile):
        return False
    if profile.resolved_slot("structured_io_contract") is not None:
        return False
    if "structured_io_contract" in profile.answers:
        return False
    return infer_structured_io_contract(profile.text) is None


def _json_to_json_semantic_flow(profile: DiscoveryProfile) -> bool:
    return (
        profile.input_intent.primary_runtime_input == "json"
        and profile.output_intent.terminal_output == "structured_json"
    )


def needs_docx_mode_choice(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "docx_output_mode"):
        return False
    intent = profile.output_intent
    if intent.terminal_output != "docx_document":
        return False
    if profile.planning_state.has_template_file_role():
        docx_mode_slot = profile.resolved_slot("docx_output_mode")
        return docx_mode_slot is None or docx_mode_slot.source == "policy_default"
    if intent.docx_output_mode is not None:
        return False
    return contains_any_phrase(
        profile.text,
        (
            "docx",
            "word",
            "word document",
            "word-dokument",
            "mall",
            "template",
        ),
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


def document_cardinality_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "document_material_scope"):
        return False
    if profile.resolved_slot("document_material_scope") is not None:
        return False
    answers = profile.answers
    text = profile.text
    if not profile.document_like_input or profile.audio_like_input:
        return False
    if "document_material_scope" in answers:
        return False
    if "document_material_scope" in profile.flow_defaults:
        return False
    if "primary_runtime_input" in answers and "text" in " ".join(
        answers["primary_runtime_input"]
    ):
        return False
    if "comparison_scope" in answers:
        return False
    if contains_any_phrase(
        text,
        (
            "one document",
            "single document",
            "one pdf",
            "ett dokument",
            "en pdf",
            "multiple documents",
            "several documents",
            "flera dokument",
            "document package",
            "dokumentpaket",
        ),
    ):
        return False
    if implies_single_primary_document(text):
        return False
    return profile.comparison_requested


def mixed_input_architecture_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "flow_input_architecture"):
        return False
    # The user's own choice already cleared the intent, so answer presence is
    # not a second thing to check — an answer the question never offered must
    # not silence it.
    return profile.input_intent.needs_architecture_clarification


def runtime_metadata_is_vague(profile: DiscoveryProfile) -> bool:
    if _family_inactive(profile, "runtime_metadata_fields"):
        return False
    if profile.resolved_slot("runtime_metadata_fields") is not None:
        return False
    answers = profile.answers
    text = profile.text
    if "runtime_metadata_fields" in answers:
        return False
    if (
        "runtime_metadata_fields" in profile.flow_defaults
        and not mentions_runtime_metadata(text)
    ):
        return False
    if mentions_runtime_metadata(text):
        return False
    if not _runtime_metadata_prerequisites_resolved(profile):
        return False
    return True


def _runtime_metadata_prerequisites_resolved(profile: DiscoveryProfile) -> bool:
    if primary_runtime_input_is_vague(profile):
        return False
    if profile.input_intent.needs_architecture_clarification:
        return False
    if (
        profile.document_like_input
        and profile.resolved_slot("document_material_scope") is None
        and "document_material_scope" not in profile.answers
        and "document_material_scope" not in profile.flow_defaults
    ):
        return False
    if document_cardinality_is_vague(profile):
        return False
    if terminal_output_is_vague(profile):
        return False
    if ultra_vague_terminal_output_choice_is_vague(profile):
        return False
    if needs_docx_mode_choice(profile):
        return False
    if needs_pdf_generation_mode_choice(profile):
        return False
    return True
