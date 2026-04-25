from __future__ import annotations

from collections.abc import Iterable

from intric.flows.ai_builder.ai_builder_clause_segmenter import (
    build_role_scoped_text,
)
from intric.flows.ai_builder.ai_builder_discovery_text_matcher import (
    contains_any_phrase,
    normalize_discovery_text,
)
from intric.flows.ai_builder.ai_builder_input_architecture_policy import (
    resolve_input_intent,
)
from intric.flows.ai_builder.ai_builder_keywords import (
    PDF_OUTPUT_CONTEXT_MARKERS,
)
from intric.flows.ai_builder.ai_builder_runtime_input_fields import (
    infer_runtime_metadata_slot,
)


def normalize_signal_text(value: str) -> str:
    return normalize_discovery_text(value)


def infer_answer_signals_from_text(text: str) -> dict[str, set[str]]:
    normalized = normalize_signal_text(text)
    if not normalized:
        return {}

    signals: dict[str, set[str]] = {}
    _add_signal(signals, "document_kind", _infer_document_kind(normalized))
    _add_signal(
        signals,
        "document_material_scope",
        _infer_document_material_scope(normalized),
    )
    _add_signal(signals, "input_material_mode", _infer_input_material_mode(normalized))
    _add_signal(
        signals,
        "flow_input_architecture",
        _infer_flow_input_architecture(normalized),
    )
    _add_signal(signals, "comparison_scope", _infer_comparison_scope(normalized))
    _add_signal(signals, "processing_scope", _infer_processing_scope(normalized))
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


def _infer_input_material_mode(text: str) -> str | None:
    primary = resolve_input_intent(text, {}).primary_runtime_input
    return None if primary == "unknown" else primary


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


def _infer_structured_analysis_need(text: str) -> str | None:
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
    runtime_field_intent = infer_runtime_metadata_slot(text)
    if runtime_field_intent is not None:
        return runtime_field_intent

    field_marker_groups = (
        (
            "case number",
            "case id",
            "reference number",
            "referensnummer",
            "intern referens",
            "internal reference",
            "ärendenummer",
            "diarienummer",
            "diarie nummer",
        ),
        (
            "department",
            "avdelning",
            "ansvarig avdelning",
            "responsible department",
            "committee",
            "nämnd",
        ),
        (
            "case officer",
            "handläggare",
            "owner",
            "ansvarig",
            "role",
            "roll",
        ),
        ("priority", "prioritet"),
        ("language", "språk"),
        ("focus", "fokus"),
        ("date", "datum"),
        ("case type", "ärendetyp", "typ av ärende"),
    )
    if sum(1 for markers in field_marker_groups if _contains_any(text, markers)) >= 2:
        return "detailed_case_metadata"
    if _contains_any(
        text,
        (
            "metadata",
            "formulärfält",
            "form fields",
            "basic metadata",
            "grundläggande metadata",
        ),
    ):
        return "basic_case_metadata"
    return None
