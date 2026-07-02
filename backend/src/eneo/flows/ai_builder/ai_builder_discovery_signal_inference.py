from __future__ import annotations

from collections.abc import Iterable

from eneo.flows.ai_builder.ai_builder_clause_segmenter import (
    build_role_scoped_text,
)
from eneo.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_phrase,
    contains_any_token_prefix,
    normalize_discovery_text,
)
from eneo.flows.ai_builder.ai_builder_input_architecture_policy import (
    InputIntentResolution,
    resolve_input_intent,
)
from eneo.flows.ai_builder.ai_builder_keywords import (
    DOCX_CONTEXT_MARKERS,
    PDF_OUTPUT_CONTEXT_MARKERS,
)
from eneo.flows.ai_builder.ai_builder_planner_pattern_signals import (
    detect_planner_pattern_signals,
)
from eneo.flows.ai_builder.ai_builder_runtime_input_fields import (
    infer_runtime_metadata_slot,
)


def normalize_signal_text(value: str) -> str:
    return normalize_discovery_text(value)


def infer_answer_signals_from_text(text: str) -> dict[str, set[str]]:
    normalized = normalize_signal_text(text)
    if not normalized:
        return {}

    signals: dict[str, set[str]] = {}
    input_intent = resolve_input_intent(normalized, {})
    input_material_mode = _infer_input_material_mode(normalized, input_intent)
    if _document_signals_apply(input_intent, input_material_mode):
        _add_signal(signals, "document_kind", _infer_document_kind(normalized))
        _add_signal(
            signals,
            "document_material_scope",
            _infer_document_material_scope(normalized),
        )
    _add_signal(signals, "input_material_mode", input_material_mode)
    _add_signal(
        signals,
        "flow_input_architecture",
        _infer_flow_input_architecture(normalized),
    )
    _add_signal(signals, "comparison_scope", _infer_comparison_scope(normalized))
    _add_signal(signals, "processing_scope", _infer_processing_scope(normalized))
    _add_signal(signals, "post_processing_goal", infer_post_processing_goal(normalized))
    _add_signal(
        signals,
        "structured_io_contract",
        infer_structured_io_contract(normalized),
    )
    _add_signal(
        signals,
        "structured_analysis_need",
        _infer_structured_analysis_need(normalized),
    )
    _add_signal(
        signals,
        "runtime_metadata_fields",
        _infer_runtime_metadata_fields(normalized),
    )
    _add_signal(
        signals,
        "pdf_generation_mode",
        _infer_pdf_generation_mode(normalized),
    )
    return signals


def _add_signal(
    signals: dict[str, set[str]],
    question_id: str,
    inferred_value: str | None,
) -> None:
    if inferred_value is None:
        return
    signals.setdefault(question_id, set()).add(inferred_value)


def _contains_any(text: str, phrases: Iterable[str]) -> bool:
    return contains_any_phrase(text, phrases)


def _contains_any_prefix(text: str, prefixes: Iterable[str]) -> bool:
    return contains_any_token_prefix(text, prefixes)


_MULTI_SOURCE_FILE_PHRASES: tuple[str, ...] = (
    "2-5 underlagsfiler",
    "flera underlagsfiler",
    "flera filer",
    "flera dokumentfiler",
    "flera källfiler",
    "several source files",
    "multiple source files",
    "several files",
    "multiple files",
    "uploaded reports",
)

_SOURCE_TO_SOURCE_COMPARISON_PHRASES: tuple[str, ...] = (
    "motsägelser mellan källorna",
    "motsägelser mellan källor",
    "motstridiga uppgifter mellan källorna",
    "jämför vad de olika filerna säger",
    "jämförelseanalysen",
    "inconsistencies between the uploaded reports",
    "inconsistencies between sources",
    "contradictions between sources",
    "compare what the different files say",
)


def is_high_confidence_source_to_source_comparison(text: str) -> bool:
    normalized = normalize_signal_text(text)
    if not normalized:
        return False
    return _infer_document_material_scope(
        normalized
    ) == "multiple_documents_case" and _has_source_to_source_comparison_evidence(
        normalized
    )


def _has_source_to_source_comparison_evidence(text: str) -> bool:
    return _contains_any(text, _SOURCE_TO_SOURCE_COMPARISON_PHRASES)


def _infer_document_kind(text: str) -> str | None:
    if _contains_any(
        text,
        (
            "blandat dokumentpaket",
            "mixed document package",
            "mixed documents",
            "olika dokumenttyper",
            "several different document types",
        ),
    ):
        return "mixed_documents"
    if _contains_any(
        text,
        (
            "leverantörsavtal",
            "ramavtal",
            "kommersiella villkor",
            "appendix",
            "bilagor",
            "avtal",
            "contract",
            "contracts",
            "agreement",
            "agreements",
        ),
    ):
        return "contracts_agreements"
    if _contains_any(
        text,
        (
            "news article",
            "news articles",
            "article like",
            "editorial",
            "artikelmaterial",
            "nyhetsartikel",
            "nyhetsartiklar",
            "artiklar",
        ),
    ):
        return "news_articles"
    if _contains_any(
        text,
        (
            "officiellt underlag",
            "official material",
            "official case files",
            "case material",
            "case files",
            "case package",
            "underlag",
            "kommunärende",
            "municipal case",
            "tjänsteskrivelse",
            "tjänsteskrivelser",
            "remiss",
            "remisser",
        ),
    ):
        return "case_documents"
    return None


def _infer_document_material_scope(text: str) -> str | None:
    if _contains_any(
        text,
        (
            "ibland ett ibland flera dokument",
            "either one or several documents",
            "både enskild fil och dokumentpaket",
            "both a single file and a case package",
            "både enskilt och flera samtidigt",
            "både ett och flera dokument",
            "både enskilt dokument och flera dokument",
            "båda lägen",
            "båda lägena",
            "both modes",
            "both single and multiple documents",
            "single and multiple documents",
            "flexibelt ett eller flera dokument",
            "flexible single or multiple documents",
        ),
    ):
        return "flexible_document_case"
    if _contains_any(
        text,
        (
            "flera pdf",
            "flera pdf er",
            "multiple pdf",
            *_MULTI_SOURCE_FILE_PHRASES,
            "document package",
            "dokumentpaket",
            "samlat underlag",
            "ladda upp flera dokument",
            "upload multiple documents",
            "upload several pdf",
            "upload multiple pdf",
        ),
    ):
        return "multiple_documents_case"
    if _contains_any(
        text,
        (
            "ett dokument",
            "en pdf",
            "one document",
            "one pdf",
            "single document",
            "single pdf",
            "ett huvuddokument",
            "ett avtal åt gången",
            "one contract at a time",
            "ett huvuddokument per ärende",
        ),
    ):
        return "single_document_case"
    return None


def _infer_input_material_mode(
    text: str,
    input_intent: InputIntentResolution,
) -> str | None:
    primary = input_intent.primary_runtime_input
    if primary != "unknown":
        return primary
    input_text = build_role_scoped_text(text).preferred_input_text()
    if _contains_any(
        input_text,
        (
            "pdf",
            "dokument",
            "document",
            "documents",
            "underlag",
            "fil",
            "file",
            "files",
        ),
    ):
        return "documents"
    return None


def _document_signals_apply(
    input_intent: InputIntentResolution,
    input_material_mode: str | None,
) -> bool:
    if input_material_mode == "json":
        return False
    if input_material_mode in {"documents", "text_and_documents"}:
        return True
    return (
        not input_intent.audio_requested
        or input_intent.document_runtime_input_requested
    )


def _infer_flow_input_architecture(text: str) -> str | None:
    if _contains_any(
        text,
        (
            "behåll dokument",
            "keep documents",
            "documents as primary",
            "dokument som primär",
            "documents as usual",
            "dokument som vanligt",
        ),
    ):
        return "document_primary_input"
    if _contains_any(
        text,
        (
            "byt till ljud",
            "switch to audio",
            "audio as primary",
            "ljud som primär",
            "transcribe first",
            "transkribera först",
        ),
    ):
        return "audio_primary_input"
    if _contains_any(
        text,
        (
            "blandade filer",
            "mixed files",
            "all file types",
            "alla typer",
            "generic file",
            "fil alla typer",
        ),
    ):
        return "generic_file_input"
    return None


def _infer_comparison_scope(text: str) -> str | None:
    if _contains_any(
        text,
        (
            "tidigare sparat material",
            "earlier saved material",
            "previous material",
            "tidigare körningar",
            "stored earlier material",
        ),
    ):
        return "compare_previous_material"
    if is_high_confidence_source_to_source_comparison(text):
        return "same_run_compare"
    if _contains_any(
        text,
        (
            "jämför dem direkt",
            "compare them directly",
            "flera dokument i samma körning",
            "compare documents in the same run",
            "same run",
            "samma körning",
        ),
    ):
        return "same_run_compare"
    return None


def _infer_processing_scope(text: str) -> str | None:
    if _contains_any(
        text,
        (
            "flera ärenden i samma körning",
            "multiple cases in one run",
            "several cases together",
        ),
    ):
        return "multiple_cases"
    if _contains_any(
        text,
        (
            "en körning åt gången",
            "ett paket åt gången",
            "one run at a time",
            "one package per run",
        ),
    ):
        return "single_case"
    return None


def infer_post_processing_goal(text: str) -> str | None:
    normalized = normalize_signal_text(text)
    if not normalized:
        return None
    # Richer workflow-shaping goals win before broad report/summary fallbacks.
    if _contains_any(
        normalized,
        (
            "bara transkrib",
            "only transcrib",
            "only transcript",
            "transcript only",
            "bara konvertera",
            "only convert",
            "ordagrant",
            "verbatim",
            "ingen sammanfattning",
            "no summary",
            "ingen analys",
            "no analysis",
        ),
    ):
        return "stop_after_primary_operation"
    if _contains_any(
        normalized,
        (
            "jämför",
            "jamfor",
            "jämföra",
            "jamfora",
            "jämförelse",
            "jamforelse",
            "compare",
            "comparison",
            "validera",
            "validate",
            "validation",
            "checklista",
            "checklist",
            "enligt schema",
            "against a schema",
            "mot schema",
        ),
    ):
        return "compare_or_validate"
    if _contains_any(
        normalized,
        (
            "risk",
            "risker",
            "risks",
            "avvikelse",
            "avvikelser",
            "deviation",
            "deviations",
            "issue",
            "issues",
            "problem",
            "problem",
            "red flag",
            "red flags",
        ),
    ):
        return "risk_or_issue_review"
    if _contains_any(
        normalized,
        (
            "beslut",
            "decisions",
            "decision",
            "nästa steg",
            "nasta steg",
            "next steps",
            "next step",
            "åtgärder",
            "atgarder",
            "actions",
            "ansvarig",
            "ansvariga",
            "owner",
            "owners",
            "deadline",
            "deadlines",
            "öppna frågor",
            "oppna fragor",
            "open questions",
            "follow-up",
            "follow up",
            "uppfölj",
            "uppfolj",
        ),
    ):
        return "action_followup"
    if _contains_any(
        normalized,
        (
            "extrahera",
            "extract",
            "extracts",
            "extracted",
            "extracting",
            "plocka ut",
            "hämta ut",
            "hamta ut",
            "nyckeluppgifter",
            "key information",
            "key details",
            "fält",
            "falt",
            "fields",
            "datum",
            "dates",
            "belopp",
            "amounts",
            "med data från",
            "med data fran",
            "with data from",
            "returnera fält",
            "return fields",
        ),
    ):
        return "extract_key_information"
    if _contains_any(
        normalized,
        (
            "beslutsunderlag",
            "decision support",
            "rekommendation",
            "rekommendationer",
            "recommendation",
            "recommendations",
            "vägval",
            "vagval",
            "next possible choices",
            "föreslå",
            "foresla",
            "suggest",
        ),
    ):
        return "decision_support"
    if _contains_any(
        normalized,
        (
            "sammanfatta",
            "sammanfattning",
            "summarize",
            "summary",
            "överblick",
            "overblick",
            "overview",
            "kortare version",
            "shorter version",
        ),
    ):
        return "summarize_or_overview"
    if _contains_any(
        normalized,
        (
            "strukturera",
            "structured notes",
            "tydliga anteckningar",
            "clear notes",
            "memo",
            "notat",
            "mötesrapport",
            "motesrapport",
        ),
    ):
        return "structure_key_information"
    if _looks_like_report_creation_goal(normalized):
        return "structure_key_information"
    if _looks_like_transcript_into_document_goal(normalized):
        return "stop_after_primary_operation"
    return None


def infer_structured_io_contract(text: str) -> str | None:
    # Heuristic backstop; classifier and structured answers remain the primary path.
    normalized = normalize_signal_text(text)
    if not normalized or "json" not in normalized:
        return None
    if _contains_any(
        normalized,
        (
            "validera",
            "validate",
            "validation",
            "schema",
            "schemat",
            "schemas",
            "regler",
            "rules",
            "krav",
            "requirements",
        ),
    ):
        return "validate_against_schema_or_rules"
    if _contains_any(
        normalized,
        (
            "mappa",
            "map",
            "mapping",
            "ny json struktur",
            "new json shape",
            "new schema",
            "nytt schema",
            "döp om",
            "dop om",
            "rename",
        ),
    ):
        return "map_to_new_schema"
    if _contains_any(
        normalized,
        (
            "extrahera",
            "extract",
            "beräkna",
            "berakna",
            "compute",
            "fält",
            "falt",
            "fields",
            "returnera fält",
            "return fields",
        ),
    ):
        return "extract_or_compute_fields"
    if _contains_any(
        normalized,
        (
            "normalisera",
            "normalize",
            "standardisera",
            "standardize",
            "berika",
            "enrich",
        ),
    ):
        return "normalize_or_enrich"
    if _contains_any(
        normalized,
        (
            "klassificera",
            "classify",
            "tagga",
            "tag",
            "kategori",
            "category",
            "etikett",
            "label",
        ),
    ):
        return "classify_or_tag"
    return None


def _looks_like_report_creation_goal(text: str) -> bool:
    return _contains_any_prefix(
        text,
        (
            "skapa",
            "skriv",
            "generer",
            "producer",
            "create",
            "write",
            "generate",
            "produce",
        ),
    ) and _contains_any(
        text,
        (
            "rapport",
            "slutrapport",
            "report",
            "final report",
            "memo",
            "notat",
            "anteckningar",
            "notes",
        ),
    )


def _looks_like_transcript_into_document_goal(text: str) -> bool:
    if not contains_any_token_prefix(text, ("transkrib", "transcrib")):
        return False
    if not _contains_any(text, (*DOCX_CONTEXT_MARKERS, *PDF_OUTPUT_CONTEXT_MARKERS)):
        return False
    return not _contains_any(
        text,
        (
            "analysera",
            "analyze",
            "analys",
            "analysis",
            "sammanfatta",
            "summarize",
            "rapport",
            "report",
            "memo",
            "extrahera",
            "extract",
            "beslut",
            "decision",
            "nästa steg",
            "next step",
            "risk",
            "jämför",
            "compare",
            "validera",
            "validate",
        ),
    )


def _infer_structured_analysis_need(text: str) -> str | None:
    pattern = detect_planner_pattern_signals(text)
    input_intent = resolve_input_intent(text, {})
    if (
        pattern.rich_document_workflow
        and pattern.prefers_structured_intermediate
        # Audio can mean transcript-only or transcript-plus-extraction; ask the
        # user instead of silently forcing a hidden JSON step.
        and not input_intent.audio_requested
    ):
        return "use_structured_analysis"
    if "strukturerad data" in text and "förbättrar kvaliteten" in text:
        return "use_structured_analysis"
    if "structured data" in text and "improves quality" in text:
        return "use_structured_analysis"
    if _contains_any(
        text,
        (
            "strukturerad data används där det förbättrar kvaliteten",
            "structured data where it improves quality",
            "use structured analysis",
            "structured analysis",
            "analysmodul",
            "analysis module",
            "output contract",
            "output_contract",
            "json innan slutrapporten",
            "json before writing the final report",
        ),
    ):
        return "use_structured_analysis"
    if _contains_any(
        text,
        (
            "håll analysen som vanlig text",
            "keep the analysis as plain text",
            "undvik extra struktur",
            "avoid extra structure",
        ),
    ):
        return "text_only_analysis"
    return None


def _infer_pdf_generation_mode(text: str) -> str | None:
    output_text = build_role_scoped_text(text).preferred_output_text()
    if "pdf" not in output_text:
        return None
    if not _contains_any(output_text, PDF_OUTPUT_CONTEXT_MARKERS):
        return None
    if _contains_any(
        output_text,
        (
            "generated pdf",
            "vanlig pdf",
            "normal pdf",
            "utan mall",
            "without template",
        ),
    ):
        return "generated_pdf"
    if _contains_any(
        output_text,
        (
            "pdf mall",
            "pdf mallar",
            "pdf template",
            "pdf-template",
            "pdf-mall",
            "fillable pdf",
            "fixed pdf layout",
            "fast pdf layout",
            "specific pdf layout",
            "specifik pdf layout",
        ),
    ):
        return "pdf_template_requested"
    if _contains_any(
        output_text,
        (
            "mall",
            "template",
            "fylla i",
            "fyll i",
            "fixed layout",
            "fast layout",
            "specific layout",
            "specifik layout",
        ),
    ):
        return "pdf_template_requested"
    return None


def _infer_runtime_metadata_fields(text: str) -> str | None:
    return infer_runtime_metadata_slot(text)
