from __future__ import annotations

from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_canonicalization import canonical_question_id
from intric.flows.ai_builder.ai_builder_discovery_signal_inference import (
    is_high_confidence_source_to_source_comparison,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    build_framework_guardrails_block,
    extract_answer_signals,
    infer_question_answer_from_freeform,
    is_supported_structured_question_id,
    latest_pending_structured_question,
    mentions_runtime_metadata,
    needs_structured_extraction,
    normalize_question_answer,
    normalize_structured_question_payload,
    question_is_already_resolved,
    resolve_docx_output_mode,
    resolve_explicit_output_choice,
    resolve_output_intent,
    resolve_pdf_generation_mode,
)
from intric.flows.ai_builder.ai_builder_keywords import OUTPUT_CHANGE_KEYWORDS
from intric.flows.ai_builder.ai_builder_models import ConversationMessage, OutputType
from intric.flows.flow import Flow, FlowStep


def test_resolve_explicit_output_choice_detects_pdf_from_swedish_prompt() -> None:
    output = resolve_explicit_output_choice(
        "Jag vill ladda upp flera pdf-filer och få en ny pdf med detaljerna.",
        {},
    )

    assert output == "pdf_document"


def test_resolve_explicit_output_choice_prefers_word_target_in_substitution_phrase() -> (
    None
):
    output = resolve_explicit_output_choice(
        "Ändra så att jag får ut ett word dokument istället för en pdf.",
        {},
    )

    assert output == "docx_document"


def test_resolve_explicit_output_choice_detects_pdf_file_replacement_target() -> None:
    output = resolve_explicit_output_choice(
        "Ändra så att jag får ut en pdf fil istället för text.",
        {},
    )

    assert output == "pdf_document"


def test_resolve_explicit_output_choice_respects_existing_flow_default_when_output_not_reopened() -> (
    None
):
    output = resolve_explicit_output_choice(
        "Behåll samma flöde men lägg till makrotrender och geopolitiska signaler.",
        {},
        flow_defaults={"final_output_mode": {"structured_text"}},
    )

    assert output == "structured_text"


def test_resolve_explicit_output_choice_detects_swedish_text_summary_output() -> None:
    output = resolve_explicit_output_choice(
        "Slutresultatet ska vara en strukturerad textsammanfattning av materialet.",
        {},
    )

    assert output == "structured_text"


def test_resolve_explicit_output_choice_detects_generic_english_text_summary() -> None:
    output = resolve_explicit_output_choice(
        "I want a flow that summarizes uploaded news articles as a text summary.",
        {},
    )

    assert output == "structured_text"


def test_resolve_explicit_output_choice_ignores_json_payload_examples() -> None:
    output = resolve_explicit_output_choice(
        (
            "Output ska vara: 1. en översiktlig flödesdesign, "
            "2. exempel på payload eller JSON-struktur mellan noder, "
            "3. felhantering och kvalitetskontroller."
        ),
        {},
    )

    assert output is None


def test_resolve_explicit_output_choice_accepts_json_as_final_artifact() -> None:
    output = resolve_explicit_output_choice(
        "Slutresultatet ska vara JSON som kan läsas maskinellt.",
        {},
    )

    assert output == "structured_json"


def test_resolve_explicit_output_choice_does_not_detect_specialty_phrasings() -> None:
    """Lockdown for the framework_policy domain-vocabulary purge.

    Specialty Swedish phrasings (`beslutsunderlag som text`, bare
    `beslutsunderlag`) and the English `decision support as text`
    compound must not bias the planner toward `structured_text`. Generic
    markers (`text summary`, `textsammanfattning`, `sammanfattning som
    text`, `rapport`, `report`, `memo`, `sammanfattning`, `summary`) are
    pinned by sibling tests and cover the same detection surface for
    any non-specialty phrasing — a Swedish user who reaches for
    `textsammanfattning` or `rapport` still hits `structured_text`
    correctly."""
    specialty_inputs = (
        "Slutresultatet ska vara ett strukturerat beslutsunderlag som text.",
        "Bygg ett flöde som producerar ett beslutsunderlag.",
        "I want the flow to produce decision support text.",
        "Generate a decision-support brief.",
    )
    for prompt in specialty_inputs:
        assert resolve_explicit_output_choice(prompt, {}) is None, (
            f"Specialty phrasing leaked back into output-shape detection: {prompt!r}"
        )


def test_resolve_docx_output_mode_ignores_generic_template_wording_when_output_is_pdf() -> (
    None
):
    mode = resolve_docx_output_mode(
        "Jag vill fylla i en mall men slutresultatet ska vara en PDF.",
        {"final_output_mode": {"pdf_document"}},
        explicit_output="pdf_document",
    )

    assert mode is None


def test_resolve_docx_output_mode_detects_template_fill_for_docx_template_request() -> (
    None
):
    mode = resolve_docx_output_mode(
        "Skapa ett Word-dokument från en mall.",
        {"final_output_mode": {"docx_document"}},
        explicit_output="docx_document",
    )

    assert mode == "template_fill_docx"


def test_resolve_output_intent_defaults_generic_docx_prompt_to_generated_docx() -> None:
    prompt = "Bygg ett flöde som tar ett uppladdat PDF-dokument och genererar en DOCX-rapport."

    signals = extract_answer_signals([{"role": "user", "content": prompt}])
    intent = resolve_output_intent(prompt, signals)

    assert intent.terminal_output == "docx_document"
    assert intent.docx_output_mode == "generated_docx"
    assert intent.pdf_generation_mode is None


def test_resolve_output_intent_keeps_without_template_docx_prompt_on_docx_path() -> (
    None
):
    prompt = "Bygg ett flöde som genererar en DOCX-rapport utan mall från uppladdade PDF-dokument."

    signals = extract_answer_signals([{"role": "user", "content": prompt}])
    intent = resolve_output_intent(prompt, signals)

    assert intent.terminal_output == "docx_document"
    assert intent.docx_output_mode == "generated_docx"
    assert intent.pdf_generation_mode is None


def test_resolve_output_intent_keeps_docx_template_prompt_on_docx_path() -> None:
    prompt = (
        "Bygg ett flöde som fyller en DOCX-mall med data från uppladdade PDF-dokument."
    )

    signals = extract_answer_signals([{"role": "user", "content": prompt}])
    intent = resolve_output_intent(prompt, signals)

    assert intent.terminal_output == "docx_document"
    assert intent.docx_output_mode == "template_fill_docx"
    assert intent.pdf_generation_mode is None


def test_resolve_docx_output_mode_defaults_when_docx_is_selected_via_structured_answer() -> (
    None
):
    mode = resolve_docx_output_mode(
        "Behåll samma riktning.",
        {"final_output_mode": {"docx_document"}},
        explicit_output="docx_document",
    )

    assert mode == "generated_docx"


def test_resolve_output_intent_detects_pdf_template_expectation_without_docx_mode() -> (
    None
):
    intent = resolve_output_intent(
        "Jag vill fylla i en PDF-mall med transkriberingen.",
        {},
    )

    assert intent.terminal_output == "pdf_document"
    assert intent.pdf_generation_mode == "pdf_template_requested"
    assert intent.docx_output_mode is None


def test_resolve_output_intent_keeps_plain_pdf_when_pdf_generation_mode_is_answered() -> (
    None
):
    intent = resolve_output_intent(
        "Det ska vara en vanlig genererad PDF utan fast mall.",
        {
            "final_output_mode": {"pdf_document"},
            "pdf_generation_mode": {"generated_pdf"},
        },
    )

    assert intent.terminal_output == "pdf_document"
    assert intent.pdf_generation_mode == "generated_pdf"
    assert intent.docx_output_mode is None


def test_resolve_pdf_generation_mode_defaults_when_pdf_is_selected_via_structured_answer() -> (
    None
):
    mode = resolve_pdf_generation_mode(
        "Behåll samma riktning.",
        {"final_output_mode": {"pdf_document"}},
        explicit_output="pdf_document",
    )

    assert mode == "generated_pdf"


def test_resolve_output_intent_defaults_generic_pdf_prompt_to_generated_pdf() -> None:
    prompt = "Bygg ett flöde som tar ett uppladdat PDF-dokument och genererar en PDF-rapport."

    signals = extract_answer_signals([{"role": "user", "content": prompt}])
    intent = resolve_output_intent(prompt, signals)

    assert intent.terminal_output == "pdf_document"
    assert intent.pdf_generation_mode == "generated_pdf"


def test_resolve_output_intent_defaults_report_like_prompt_to_structured_text() -> None:
    intent = resolve_output_intent(
        (
            "Jag vill börja bygga ett flöde där jag kommer skicka in en ljudfil som du ska "
            "transkribera sen ska du sammanfatta det och ge mig en strukturerad rapport med "
            "dom viktigaste keywords och själva ämnet. Vilka namn som förekommer och om det "
            "förekommer ett datum och själva ämnet av samtalet också."
        ),
        {},
    )

    assert intent.terminal_output == "structured_text"
    assert intent.docx_output_mode is None
    assert intent.pdf_generation_mode is None


def test_resolve_output_intent_defaults_text_answer_flow_to_structured_text() -> None:
    intent = resolve_output_intent(
        (
            "Skapa ett enkelt textflöde som skriver ett kort svar på en "
            "inkommande fråga, låter ett separat kritiksteg kontrollera "
            "tydlighet och saklighet, och skriver en slutversion som använder "
            "kritiken."
        ),
        {},
    )

    assert intent.terminal_output == "structured_text"
    assert intent.docx_output_mode is None
    assert intent.pdf_generation_mode is None


def test_resolve_output_intent_defaults_english_short_answer_flow_to_structured_text() -> (
    None
):
    intent = resolve_output_intent(
        "Create a flow that generates a brief answer to an incoming question.",
        {},
    )

    assert intent.terminal_output == "structured_text"
    assert intent.docx_output_mode is None
    assert intent.pdf_generation_mode is None


def test_resolve_output_intent_does_not_treat_incidental_answer_phrase_as_text_output() -> (
    None
):
    intent = resolve_output_intent(
        "Skapa ett flöde som ger svar på leverantörens fråga.",
        {},
    )

    assert intent.terminal_output is None


def test_needs_structured_extraction_for_named_reusable_fields() -> None:
    assert needs_structured_extraction(
        (
            "Flödet ska extrahera viktiga fakta, risker, möjligheter och rekommendationer "
            "och använda strukturerad data där det förbättrar kvaliteten."
        ),
        {},
        step_count=2,
        terminal_output_type=OutputType.TEXT,
    )


def test_does_not_need_structured_extraction_for_single_step_plain_summary() -> None:
    assert not needs_structured_extraction(
        "Sammanfatta ett uppladdat dokument som vanlig text.",
        {},
        step_count=1,
        terminal_output_type=OutputType.TEXT,
    )


def test_framework_guardrails_block_forbids_custom_code_paths() -> None:
    guardrails = build_framework_guardrails_block()

    assert "Eneo Flow-ramverket" in guardrails
    assert "Python" in guardrails
    assert "egna integrationer" in guardrails


def test_normalizes_output_question_aliases_to_canonical_mode() -> None:
    payload = normalize_structured_question_payload(
        {
            "question_id": "final_output_format",
            "question": "Vilket slutresultat vill du att flödet ska producera?",
            "options": [
                {"id": "text_output", "label": "Text"},
                {"id": "docx_generated", "label": "DOCX"},
                {"id": "json_output", "label": "JSON"},
            ],
        }
    )

    assert payload["question_id"] == "final_output_mode"
    assert [option["id"] for option in payload["options"]] == [
        "structured_text",
        "docx_document",
        "structured_json",
    ]


def test_canonical_question_id_is_available_from_canonicalization_module() -> None:
    assert canonical_question_id("final_output_format") == "final_output_mode"


def test_output_change_keywords_live_in_keywords_module() -> None:
    assert "final pdf" in OUTPUT_CHANGE_KEYWORDS


def test_normalizes_output_answer_aliases_to_canonical_mode() -> None:
    answer = normalize_question_answer(
        {
            "question_id": "primary_output_format",
            "selected_option_ids": ["docx_generated"],
            "selected_values": ["docx_generated"],
            "answer": "docx_generated",
        }
    )

    assert answer["question_id"] == "final_output_mode"
    assert answer["selected_option_ids"] == ["docx_document"]
    assert answer["selected_values"] == ["docx_document"]
    assert answer["answer"] == "docx_document"


def test_normalizes_upload_and_output_type_aliases_to_framework_ids() -> None:
    upload_payload = normalize_structured_question_payload(
        {
            "question_id": "upload_mode",
            "question": "Hur ska filer laddas upp?",
            "options": [
                {"id": "multiple_same_run", "label": "Flera samtidigt"},
                {"id": "one_per_run", "label": "En åt gången"},
            ],
        }
    )
    output_answer = normalize_question_answer(
        {
            "question_id": "final_output_type",
            "selected_option_id": "comparison_matrix_json",
            "answer": "comparison_matrix_json",
        }
    )

    assert upload_payload["question_id"] == "document_material_scope"
    assert [option["id"] for option in upload_payload["options"]] == [
        "multiple_documents_case",
        "single_document_case",
    ]
    assert output_answer["question_id"] == "final_output_mode"
    assert output_answer["selected_option_id"] == "structured_json"
    assert output_answer["answer"] == "structured_json"


def test_extract_answer_signals_reads_singular_structured_answer_fields() -> None:
    signals = extract_answer_signals(
        [
            {
                "role": "user",
                "content": "Flera dokument i samma körning",
                "metadata": {
                    "question_answer": {
                        "question_id": "comparison_scope",
                        "selected_option_id": "same_run_multiple_documents",
                        "answer": "same_run_multiple_documents",
                    }
                },
            }
        ]
    )

    assert "comparison_scope" in signals
    assert "same_run_multiple_documents" in signals["comparison_scope"]


def test_extract_answer_signals_prefers_latest_structured_answer_for_same_question() -> (
    None
):
    signals = extract_answer_signals(
        [
            {
                "role": "user",
                "content": "DOCX document",
                "metadata": {
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_option_id": "docx_document",
                        "answer": "docx_document",
                    }
                },
            },
            {
                "role": "user",
                "content": "PDF-dokument",
                "metadata": {
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_option_id": "pdf_document",
                        "answer": "pdf_document",
                    }
                },
            },
        ]
    )

    assert signals["final_output_mode"] == {"pdf_document", "pdf-dokument"}


def test_extract_answer_signals_prefers_latest_input_material_answer() -> None:
    signals = extract_answer_signals(
        [
            {
                "role": "user",
                "content": "Dokument",
                "metadata": {
                    "question_answer": {
                        "question_id": "input_material_mode",
                        "selected_option_id": "documents",
                        "answer": "documents",
                    }
                },
            },
            {
                "role": "user",
                "content": "Ljud",
                "metadata": {
                    "question_answer": {
                        "question_id": "input_material_mode",
                        "selected_option_id": "audio",
                        "answer": "audio",
                    }
                },
            },
        ]
    )

    assert signals["input_material_mode"] == {"audio", "ljud"}


def test_extract_answer_signals_does_not_infer_cross_family_signals_from_structured_answer_labels() -> (
    None
):
    signals = extract_answer_signals(
        [
            {
                "role": "user",
                "content": "DOCX document",
                "metadata": {
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_option_id": "docx_document",
                        "answer": "docx_document",
                    }
                },
            }
        ]
    )

    assert "input_material_mode" not in signals
    assert signals["final_output_mode"] == {"docx_document", "docx document"}


def test_latest_pending_structured_question_reads_backend_question_payload() -> None:
    question = latest_pending_structured_question(
        [
            ConversationMessage(
                role="assistant",
                content="Question",
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "ask_structured_question",
                        "arguments": {
                            "question_id": "final_output_mode",
                            "question": "Vad ska flödet producera som slutresultat?",
                            "options": [
                                {
                                    "id": "structured_text",
                                    "label": "Strukturerat textresultat",
                                }
                            ],
                        },
                    }
                ],
            )
        ]
    )

    assert question is not None
    assert question["question_id"] == "final_output_mode"


def test_infer_question_answer_from_freeform_matches_exact_option_label() -> None:
    answer = infer_question_answer_from_freeform(
        [
            ConversationMessage(
                role="assistant",
                content="Question",
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "ask_structured_question",
                        "arguments": {
                            "question_id": "processing_scope",
                            "question": "Hur ska flödet hantera ärendematerial per körning?",
                            "options": [
                                {
                                    "id": "single_case",
                                    "label": "Ett ärende åt gången",
                                    "value": "single_case",
                                },
                                {
                                    "id": "multiple_cases",
                                    "label": "Flera ärenden i samma körning",
                                    "value": "multiple_cases",
                                },
                            ],
                        },
                    }
                ],
            )
        ],
        "Ett ärende åt gången.",
    )

    assert answer is not None
    assert answer["question_id"] == "processing_scope"
    assert answer["selected_option_id"] == "single_case"


def test_infer_question_answer_from_freeform_matches_option_description() -> None:
    answer = infer_question_answer_from_freeform(
        [
            ConversationMessage(
                role="assistant",
                content="Question",
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "ask_structured_question",
                        "arguments": {
                            "question_id": "comparison_scope",
                            "question": "När ska flödet jämföra dokument?",
                            "options": [
                                {
                                    "id": "same_run_compare",
                                    "label": "Jämför dokument i samma körning",
                                    "description": "Ladda upp flera dokument tillsammans och jämför dem direkt.",
                                    "value": "same_run_compare",
                                },
                                {
                                    "id": "compare_previous_material",
                                    "label": "Jämför mot tidigare sparat material",
                                    "description": "Ladda upp ett dokument och jämför det mot tidigare material.",
                                    "value": "compare_previous_material",
                                },
                            ],
                        },
                    }
                ],
            )
        ],
        "Låt användaren ladda upp flera PDF:er i samma körning.",
    )

    assert answer is not None
    assert answer["question_id"] == "comparison_scope"
    assert answer["selected_option_id"] == "same_run_compare"


def test_infer_question_answer_from_freeform_uses_question_family_specific_scope_signals() -> (
    None
):
    answer = infer_question_answer_from_freeform(
        [
            ConversationMessage(
                role="assistant",
                content="Question",
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "ask_structured_question",
                        "arguments": {
                            "question_id": "document_material_scope",
                            "question": "Hur brukar underlaget för ett ärende se ut?",
                            "options": [
                                {
                                    "id": "single_document_case",
                                    "label": "Ett huvuddokument per ärende",
                                    "value": "single_document_case",
                                },
                                {
                                    "id": "multiple_documents_case",
                                    "label": "Flera dokument för samma ärende",
                                    "value": "multiple_documents_case",
                                },
                            ],
                        },
                    }
                ],
            )
        ],
        "Ett avtal åt gången.",
    )

    assert answer is not None
    assert answer["question_id"] == "document_material_scope"
    assert answer["selected_option_id"] == "single_document_case"


def test_extract_answer_signals_infers_freeform_document_signals_without_metadata() -> (
    None
):
    signals = extract_answer_signals(
        [
            {
                "role": "user",
                "content": (
                    "Det handlar om leverantörsavtal och bilagor, och användaren ska kunna "
                    "ladda upp flera PDF:er i samma körning."
                ),
            }
        ]
    )

    assert "contracts_agreements" in signals["document_kind"]
    assert "multiple_documents_case" in signals["document_material_scope"]
    assert "documents" in signals["input_material_mode"]


def test_extract_answer_signals_infers_swedish_flexible_pdf_answers() -> None:
    signals = extract_answer_signals(
        [
            {
                "role": "user",
                "content": "båda lägen",
            },
            {
                "role": "user",
                "content": "pdf filer som inkommande underlag",
            },
        ]
    )

    assert "flexible_document_case" in signals["document_material_scope"]
    assert "documents" in signals["input_material_mode"]


def test_extract_answer_signals_infers_structured_analysis_and_metadata_needs() -> None:
    signals = extract_answer_signals(
        [
            {
                "role": "user",
                "content": (
                    "Användaren ska ange intern referens, prioritet och ansvarig avdelning, "
                    "och strukturerad data ska användas där det förbättrar kvaliteten."
                ),
            }
        ]
    )

    assert "use_structured_analysis" in signals["structured_analysis_need"]
    assert "detailed_case_metadata" in signals["runtime_metadata_fields"]


def test_extract_answer_signals_infers_structured_analysis_from_rich_docx_workflow() -> (
    None
):
    signals = extract_answer_signals(
        [
            {
                "role": "user",
                "content": (
                    "Bygg ett flöde där användaren laddar upp flera underlagsfiler "
                    "och en Word-mall. Flödet ska läsa underlaget, extrahera "
                    "huvudfakta, jämföra motstridiga uppgifter och fylla mallen."
                ),
            }
        ]
    )

    assert "documents" in signals["input_material_mode"]
    assert "use_structured_analysis" in signals["structured_analysis_need"]


@pytest.mark.parametrize(
    "text",
    [
        (
            "Användaren laddar upp 2-5 underlagsfiler och flödet ska "
            "identifiera motsägelser mellan källorna i ett separat analyssteg."
        ),
        (
            "Låt användaren ladda upp flera filer och jämför vad de olika "
            "filerna säger om samma fakta."
        ),
        (
            "Upload several source documents and find inconsistencies between "
            "the uploaded reports."
        ),
    ],
)
def test_high_confidence_source_comparison_requires_multiple_sources(
    text: str,
) -> None:
    assert is_high_confidence_source_to_source_comparison(text)


@pytest.mark.parametrize(
    "text",
    [
        "Bygg ett flöde som jämför flera dokument och genererar en DOCX-rapport.",
        "Bygg ett flöde som jämför ett avtal mot interna riktlinjer.",
        "Låt användaren ladda upp flera filer och sammanfatta dem kort.",
        (
            "Användaren laddar ibland upp ett, ibland flera dokument och vill "
            "identifiera motsägelser mellan källorna."
        ),
    ],
)
def test_high_confidence_source_comparison_rejects_ambiguous_or_one_sided_prompts(
    text: str,
) -> None:
    assert not is_high_confidence_source_to_source_comparison(text)


def test_extract_answer_signals_allows_high_confidence_comparison_freeform() -> None:
    signals = extract_answer_signals(
        [
            {
                "role": "user",
                "content": (
                    "Användaren laddar upp 2-5 underlagsfiler. Flödet ska "
                    "extrahera nyckelfakta som strukturerad JSON från varje fil "
                    "och identifiera motsägelser mellan källorna."
                ),
            }
        ]
    )

    assert signals["document_material_scope"] == {"multiple_documents_case"}
    assert signals["comparison_scope"] == {"same_run_compare"}


def test_requirements_summary_does_not_erase_high_confidence_comparison_signal() -> (
    None
):
    signals = extract_answer_signals(
        [
            {
                "role": "user",
                "content": (
                    "Användaren laddar upp flera underlagsfiler och flödet ska "
                    "identifiera motsägelser mellan källorna."
                ),
            },
            {
                "role": "tool",
                "content": "",
                "metadata": {
                    "requirements_summary": {
                        "input_description": "Primär indata vid körning: Dokument.",
                        "output_description": (
                            "Huvudsakligt slutresultat: Strukturerad JSON."
                        ),
                        "key_decisions": [
                            {
                                "topic": "Dokumentunderlag",
                                "decision": "Ibland ett, ibland flera dokument",
                            }
                        ],
                    }
                },
            },
        ]
    )

    assert signals["comparison_scope"] == {"same_run_compare"}


def test_extract_answer_signals_infers_common_runtime_metadata_field_names() -> None:
    signals = extract_answer_signals(
        [
            {
                "role": "user",
                "content": (
                    "Användaren ska fylla i diarienummer, avdelning och "
                    "handläggare innan rapporten skapas."
                ),
            }
        ]
    )

    assert "detailed_case_metadata" in signals["runtime_metadata_fields"]


def test_extract_answer_signals_does_not_infer_runtime_metadata_from_output_fields() -> (
    None
):
    signals = extract_answer_signals(
        [
            {
                "role": "user",
                "content": (
                    "Rapporten ska innehålla diarienummer, avdelning och "
                    "handläggare om det finns i dokumenten."
                ),
            }
        ]
    )

    assert "runtime_metadata_fields" not in signals


@pytest.mark.parametrize(
    "text",
    [
        "Extrahera metadata från dokumentet.",
        "Sammanfatta på svenskt språk.",
        "Ändra fokus till riskanalys.",
    ],
)
def test_mentions_runtime_metadata_ignores_content_and_analysis_terms(
    text: str,
) -> None:
    assert not mentions_runtime_metadata(text)


def test_extract_answer_signals_does_not_treat_input_pdfs_as_pdf_output_mode() -> None:
    prompt = (
        "Bygg ett flöde som tar emot ett dokumentpaket med flera PDF-filer i ett ärende. "
        "Steg 1 extraherar text ur alla dokument. Steg 2 identifierar nyckelpunkter som "
        "strukturerad JSON. Steg 3 skriver en strukturerad DOCX-rapport utan mall."
    )

    signals = extract_answer_signals(
        [
            {
                "role": "user",
                "content": prompt,
            }
        ]
    )
    intent = resolve_output_intent(prompt, signals)

    assert "pdf_generation_mode" not in signals
    assert intent.terminal_output == "docx_document"
    assert intent.docx_output_mode == "generated_docx"


def test_extract_answer_signals_reads_confirmed_requirements_summary_output_mode() -> (
    None
):
    signals = extract_answer_signals(
        [
            {
                "role": "tool",
                "content": "Requirements presented to user.",
                "metadata": {
                    "requirements_summary": {
                        "output_description": "En genererad DOCX-rapport baserad på PDF-underlaget."
                    }
                },
            }
        ]
    )

    assert signals["final_output_mode"] == {"docx_document"}


def test_extract_answer_signals_reads_confirmed_audio_requirements_summary() -> None:
    signals = extract_answer_signals(
        [
            {
                "role": "tool",
                "content": "Requirements presented to user.",
                "metadata": {
                    "requirements_summary": {
                        "input_description": "Användaren laddar upp en ljudfil vid körning.",
                        "output_description": "Ett genererat DOCX-dokument.",
                    }
                },
            }
        ]
    )

    assert signals["input_material_mode"] == {"audio"}
    assert signals["final_output_mode"] == {"docx_document"}


def test_resolve_output_intent_prefers_confirmed_docx_summary_over_pdf_input_reference() -> (
    None
):
    prompt = "Bygg ett flöde som tar ett uppladdat PDF-dokument och genererar en DOCX-rapport."
    signals = extract_answer_signals(
        [
            {"role": "user", "content": prompt},
            {
                "role": "tool",
                "content": "Requirements presented to user.",
                "metadata": {
                    "requirements_summary": {
                        "output_description": "En genererad DOCX-rapport baserad på PDF-underlaget."
                    }
                },
            },
        ]
    )

    intent = resolve_output_intent(prompt, signals)

    assert intent.terminal_output == "docx_document"


def test_resolve_output_intent_uses_role_scoped_pdf_input_vs_docx_output() -> None:
    prompt = "Bygg ett flöde som tar ett uppladdat PDF-dokument och genererar en DOCX-rapport."

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "docx_document"


def test_resolve_output_intent_prefers_text_summary_over_pdf_input_reference() -> None:
    prompt = "Bygg ett enkelt flöde som tar ett uppladdat PDF-dokument och returnerar en kort textsammanfattning på svenska."

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "structured_text"


def test_resolve_output_intent_keeps_pdf_when_summary_phrase_describes_pdf_content() -> (
    None
):
    prompt = "Bygg ett flöde som skapar en PDF-rapport som innehåller en kort textsammanfattning på svenska."

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "pdf_document"


def test_aggregate_freeform_user_text_ignores_structured_answer_messages() -> None:
    text = aggregate_freeform_user_text(
        [
            ConversationMessage(
                role="user",
                content="DOCX document",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_option_id": "docx_document",
                    }
                },
            ),
            ConversationMessage(
                role="user",
                content="Behåll samma flöde men lägg till makrotrender.",
            ),
        ]
    )

    assert "docx document" not in text
    assert "behåll samma flöde" in text


def test_aggregate_freeform_user_text_keeps_messages_when_question_answer_lacks_real_answer() -> (
    None
):
    text = aggregate_freeform_user_text(
        [
            ConversationMessage(
                role="user",
                content="ändra så att jag får ut en word dokument istället för en pdf",
                metadata={"question_answer": {"ui_language": "sv"}},
            ),
        ]
    )

    assert "word dokument" in text


def test_aggregate_freeform_user_text_keeps_long_freeform_message_even_with_structured_answer_metadata() -> (
    None
):
    text = aggregate_freeform_user_text(
        [
            ConversationMessage(
                role="user",
                content="ändra så att jag får ut en word dokument istället för en pdf",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_option_id": "docx_document",
                    }
                },
            ),
        ]
    )

    assert "word dokument istället för en pdf" in text


def test_aggregate_freeform_user_text_filters_structured_answer_echo_with_terminal_punctuation() -> (
    None
):
    text = aggregate_freeform_user_text(
        [
            ConversationMessage(
                role="user",
                content="pdf_document.",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_value": "pdf_document",
                    }
                },
            ),
        ]
    )

    assert text == ""


def test_aggregate_freeform_user_text_keeps_mixed_content_after_structured_answer_echo() -> (
    None
):
    text = aggregate_freeform_user_text(
        [
            ConversationMessage(
                role="user",
                content="pdf_document. men lägg till källor också",
                metadata={
                    "question_answer": {
                        "question_id": "final_output_mode",
                        "selected_value": "pdf_document",
                    }
                },
            ),
        ]
    )

    assert "lägg till källor också" in text


def test_question_resolution_ignores_prior_answer_labels_when_output_not_changed() -> (
    None
):
    flow = Flow(
        id=uuid4(),
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Bora",
        description=None,
        metadata_json={},
        steps=[
            FlowStep(
                id=uuid4(),
                flow_id=uuid4(),
                tenant_id=uuid4(),
                assistant_id=uuid4(),
                step_order=1,
                user_description="Summarize",
                input_source="flow_input",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
                mcp_policy="inherit",
            )
        ],
        published_version=None,
        draft_revision=0,
    )
    conversation = [
        ConversationMessage(
            role="user",
            content="DOCX document",
            metadata={
                "question_answer": {
                    "question_id": "final_output_mode",
                    "selected_option_id": "docx_document",
                }
            },
        ),
        ConversationMessage(
            role="user",
            content="Behåll samma flöde men lägg till makrotrender.",
        ),
    ]

    assert question_is_already_resolved(
        "final_output_mode",
        conversation,
        flow=flow,
    )


def test_rejects_unsupported_structured_question_ids() -> None:
    assert is_supported_structured_question_id("final_output_mode")
    assert is_supported_structured_question_id("upload_mode")
    assert is_supported_structured_question_id("final_output_type")
    assert is_supported_structured_question_id("structured_analysis_need")
    assert is_supported_structured_question_id("output_style")
    assert is_supported_structured_question_id("output_tone")
    assert is_supported_structured_question_id("detail_level")
    assert not is_supported_structured_question_id("multi_file_strategy")
