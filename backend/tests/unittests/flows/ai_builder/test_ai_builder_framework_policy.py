from __future__ import annotations

from uuid import uuid4

import pytest

from intric.flows.ai_builder.ai_builder_canonicalization import canonical_question_id
from intric.flows.ai_builder.ai_builder_discovery_signal_inference import (
    infer_post_processing_goal,
    is_high_confidence_source_to_source_comparison,
)
from intric.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from intric.flows.ai_builder.ai_builder_framework_policy import (
    aggregate_freeform_user_text,
    extract_answer_signals,
    infer_question_answer_from_freeform,
    is_supported_structured_question_id,
    latest_pending_structured_question,
    mentions_runtime_metadata,
    needs_structured_extraction,
    normalize_question_answer,
    normalize_requirements_summary_for_flow,
    normalize_structured_question_payload,
    question_is_already_resolved,
    resolve_docx_output_mode,
    resolve_explicit_output_choice,
    resolve_output_intent,
    resolve_pdf_generation_mode,
    slot_names_blocked_by_explicit_uncertainty,
    supported_structured_question_ids,
    terminal_output_uncertainty_is_unresolved,
)
from intric.flows.ai_builder.ai_builder_input_architecture_policy import (
    resolve_input_intent,
)
from intric.flows.ai_builder.ai_builder_keywords import OUTPUT_CHANGE_KEYWORDS
from intric.flows.ai_builder.planning_state_builder import (
    build_planning_state_from_conversation,
)
from intric.flows.ai_builder.question_catalog import (
    slot_resolving_legacy_question_ids,
)
from intric.flows.domain.flow import Flow, FlowStep
from intric.flows.flow_authoring_spec import (
    OutputType,
)

_AUDIO_TO_WORD_REPORT_PROMPT = (
    "Skapa ett flöde i Eneo Flödesbyggaren. "
    "Flödet ska ta emot en ljudfil eller ljudinspelning från ett möte, "
    "transkribera ljudet till svensk text och skapa ett välstrukturerat "
    "slutdokument som Word-fil (.docx). "
    "Indata är en ljudfil eller ljudinspelning. "
    "Första steget i flödet ska alltid vara transkribering av ljudet till svensk text. "
    "Ta emot ljudfilen och skapa en så korrekt svensk transkribering som möjligt. "
    "Alla efterföljande steg ska arbeta mot transkriberingen som källa. "
    "Varje analyssteg ska föra vidare tidigare ackumulerat underlag. "
    "Slutrapporten ska inte följa en stel mall, utan struktureras utifrån "
    "innehållet i mötet. "
    "Flödet ska ge en färdig Word-fil (.docx) med rapporten."
)


def _make_flow_step(
    *,
    step_order: int,
    user_description: str,
    input_source: str,
    input_type: str,
    output_mode: str,
    output_type: str,
) -> FlowStep:
    return FlowStep(
        id=uuid4(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=user_description,
        input_source=input_source,
        input_type=input_type,
        output_mode=output_mode,
        output_type=output_type,
        mcp_policy="inherit",
    )


def _make_audio_docx_flow() -> Flow:
    return Flow(
        id=uuid4(),
        name="Transkribering till rapport",
        description="Transkriberar ljud och skapar DOCX.",
        tenant_id=uuid4(),
        user_id=uuid4(),
        space_id=uuid4(),
        steps=[
            _make_flow_step(
                step_order=1,
                user_description="Transkribera ljud",
                input_source="flow_input",
                input_type="audio",
                output_mode="transcribe_only",
                output_type="text",
            ),
            _make_flow_step(
                step_order=2,
                user_description="Skapa DOCX",
                input_source="previous_step",
                input_type="text",
                output_mode="pass_through",
                output_type="docx",
            ),
        ],
        metadata_json=None,
        published=True,
        published_version=1,
        draft_revision=3,
    )


def test_resolve_explicit_output_choice_detects_pdf_from_swedish_prompt() -> None:
    output = resolve_explicit_output_choice(
        "Jag vill ladda upp flera pdf-filer och få en ny pdf med detaljerna.",
        {},
    )

    assert output == "pdf_document"


def test_resolve_output_intent_keeps_pdf_files_as_input_when_output_is_absent() -> None:
    output = resolve_output_intent("flera pdf filer ska vara input", {})

    assert output.terminal_output is None


def test_resolve_output_intent_keeps_explicitly_uncertain_output_unresolved() -> None:
    prompt = (
        "Jag har en svensk ljudinspelning från ett möte och vill göra ett flöde "
        "av den. Flödet ska ta ljudfilen, förstå vad som sades och skapa något "
        "användbart som jag kan dela vidare efteråt. Jag vet inte exakt vilket "
        "format slutresultatet ska vara ännu, men det ska kännas professionellt "
        "och lätt att läsa."
    )
    conversation = [ConversationMessage(role="user", content=prompt)]

    output = resolve_output_intent(
        prompt,
        extract_answer_signals(conversation),
        conversation=conversation,
    )

    assert output.terminal_output is None
    assert terminal_output_uncertainty_is_unresolved(
        prompt,
        extract_answer_signals(conversation),
        conversation=conversation,
    )
    assert slot_names_blocked_by_explicit_uncertainty(conversation) == frozenset(
        {"terminal_output"}
    )


def test_resolve_output_intent_allows_later_freeform_output_clarification() -> None:
    conversation = [
        ConversationMessage(
            role="user",
            content=(
                "Jag har en svensk ljudinspelning. Jag vet inte exakt vilket "
                "format slutresultatet ska vara ännu."
            ),
        ),
        ConversationMessage(
            role="user",
            content="Slutresultatet ska vara ett DOCX-dokument.",
        ),
    ]
    text = aggregate_freeform_user_text(conversation)

    output = resolve_output_intent(
        text,
        extract_answer_signals(conversation),
        conversation=conversation,
    )

    assert output.terminal_output == "docx_document"
    assert output.docx_output_mode == "generated_docx"
    assert not terminal_output_uncertainty_is_unresolved(
        text,
        extract_answer_signals(conversation),
        conversation=conversation,
    )
    assert slot_names_blocked_by_explicit_uncertainty(conversation) == frozenset()


def test_resolve_output_intent_does_not_treat_topic_uncertainty_as_output_uncertainty() -> (
    None
):
    prompt = (
        "Jag vet inte vad mötet handlar om. Slutresultatet ska vara ett DOCX-dokument."
    )
    conversation = [ConversationMessage(role="user", content=prompt)]

    output = resolve_output_intent(
        prompt,
        extract_answer_signals(conversation),
        conversation=conversation,
    )

    assert output.terminal_output == "docx_document"
    assert not terminal_output_uncertainty_is_unresolved(
        prompt,
        extract_answer_signals(conversation),
        conversation=conversation,
    )


def test_resolve_output_intent_does_not_treat_non_output_uncertainty_clause_as_output_uncertainty() -> (
    None
):
    prompt = "Jag är osäker på texten, men slutresultatet ska vara ett DOCX-dokument."
    conversation = [ConversationMessage(role="user", content=prompt)]

    output = resolve_output_intent(
        prompt,
        extract_answer_signals(conversation),
        conversation=conversation,
    )

    assert output.terminal_output == "docx_document"
    assert not terminal_output_uncertainty_is_unresolved(
        prompt,
        extract_answer_signals(conversation),
        conversation=conversation,
    )


def test_resolve_output_intent_asks_when_same_turn_lists_tentative_formats() -> None:
    prompt = "Jag är osäker på om slutresultatet ska vara PDF eller DOCX."
    conversation = [ConversationMessage(role="user", content=prompt)]

    output = resolve_output_intent(
        prompt,
        extract_answer_signals(conversation),
        conversation=conversation,
    )

    assert output.terminal_output is None
    assert slot_names_blocked_by_explicit_uncertainty(conversation) == frozenset(
        {"terminal_output"}
    )


@pytest.mark.parametrize(
    "prompt",
    [
        "Skapa ett flöde som ska få ett worddokument uppladdat som input.",
        "Skapa ett flöde som ska få ett Word-dokument uppladdat som input.",
        "Skapa ett flöde som ska få ett word dokument uppladdat som input.",
        "Skapa ett flöde som ska få en wordfil uppladdad som input.",
        "Skapa ett flöde som ska få ett pdfdokument uppladdat som input.",
        "Skapa ett flöde som ska få en pdffil uppladdad som input.",
    ],
)
def test_resolve_output_intent_keeps_swedish_artifact_uploads_as_input_only(
    prompt: str,
) -> None:
    output = resolve_output_intent(prompt, {})

    assert output.terminal_output is None
    assert output.docx_output_mode is None
    assert output.pdf_generation_mode is None


@pytest.mark.parametrize(
    ("prompt", "terminal_output", "docx_mode", "pdf_mode"),
    [
        (
            "Användaren laddar upp ett underlag. I slutändan skapas ett worddokument som output.",
            "docx_document",
            "generated_docx",
            None,
        ),
        (
            "Användaren laddar upp ett underlag. I slutändan skapas en wordfil som output.",
            "docx_document",
            "generated_docx",
            None,
        ),
        (
            "Användaren laddar upp ett underlag. I slutändan skapas ett docxdokument som output.",
            "docx_document",
            "generated_docx",
            None,
        ),
        (
            "Användaren laddar upp ett underlag. Slutresultatet ska vara ett pdfdokument.",
            "pdf_document",
            None,
            "generated_pdf",
        ),
        (
            "Användaren laddar upp ett underlag. Slutresultatet ska vara en pdffil.",
            "pdf_document",
            None,
            "generated_pdf",
        ),
        (
            "Användaren laddar upp ett underlag. I slutändan skapas en pdfrapport som output.",
            "pdf_document",
            None,
            "generated_pdf",
        ),
    ],
)
def test_resolve_output_intent_detects_swedish_artifact_output_compounds(
    prompt: str,
    terminal_output: str,
    docx_mode: str | None,
    pdf_mode: str | None,
) -> None:
    output = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert output.terminal_output == terminal_output
    assert output.docx_output_mode == docx_mode
    assert output.pdf_generation_mode == pdf_mode


def test_resolve_output_intent_handles_exact_swedish_word_input_and_output_prompt() -> (
    None
):
    prompt = (
        "Skapa ett flöde som ska få ett worddokument uppladdat som input, "
        "därefter ska detta dokument analyseras. När alla steg är klara så "
        "ska det i slutändan skapas ett worddokument som output."
    )

    output = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert output.terminal_output == "docx_document"
    assert output.docx_output_mode == "generated_docx"
    assert output.pdf_generation_mode is None


def test_resolve_output_intent_keeps_singular_pdf_file_output_wording() -> None:
    output = resolve_output_intent("utdatat ska vara pdf fil", {})

    assert output.terminal_output == "pdf_document"


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


def test_resolve_output_intent_detects_uploaded_word_template_fill_output() -> None:
    prompt = (
        "Fyll i en uppladdad Word-mall som innehåller {{platshållare}}. "
        "Användaren laddar upp ett underlagsdokument och fyller i "
        "inmatningsfälten referens_id och ansvarig innan körning. "
        "Steg 1 ska extrahera strukturerad JSON ur underlaget. "
        "Steg 2 ska kombinera den extraherade JSON:en med referens_id och "
        "ansvarig till en sammanställning som matchar mallens platshållare. "
        "Steg 3 ska fylla mallen från sammanställningen."
    )

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "docx_document"
    assert intent.docx_output_mode == "template_fill_docx"


def test_resolve_output_intent_does_not_treat_word_template_reference_as_docx_output() -> (
    None
):
    prompt = "Ladda upp en Word-mall och en PDF - använd båda som referens."

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output is None
    assert intent.docx_output_mode is None


def test_resolve_output_intent_does_not_treat_word_input_form_fields_as_docx_output() -> (
    None
):
    prompt = (
        "Användaren laddar upp ett Word-dokument och fyll i inmatningsfält. "
        "Sammanfatta innehållet."
    )

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output is None
    assert intent.docx_output_mode is None


def test_resolve_output_intent_keeps_pdf_when_word_template_is_reference() -> None:
    prompt = "Jag har en DOCX-mall som referens, men slutresultatet ska vara en PDF."

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "pdf_document"
    assert intent.docx_output_mode is None


def test_audio_to_word_report_prompt_infers_audio_input_not_document_input() -> None:
    signals = extract_answer_signals(
        [{"role": "user", "content": _AUDIO_TO_WORD_REPORT_PROMPT}]
    )

    assert signals.get("input_material_mode") == {"audio"}
    assert "document_kind" not in signals
    assert "document_material_scope" not in signals

    state = build_planning_state_from_conversation(
        [
            ConversationMessage(
                role="user",
                content=_AUDIO_TO_WORD_REPORT_PROMPT,
                metadata={"ui_language": "sv"},
            )
        ]
    )

    assert state.resolved_slots["primary_runtime_input"].value == "audio"
    assert state.resolved_slots["terminal_output"].value == "docx_document"
    assert state.resolved_slots["docx_output_mode"].value == "generated_docx"
    assert "document_material_scope" not in state.resolved_slots


def test_resolve_docx_output_mode_treats_negated_rigid_template_as_generated_docx() -> (
    None
):
    prompt = (
        "Skapa ett Word-dokument. Rapporten ska inte följa en stel mall, "
        "utan struktureras utifrån innehållet."
    )

    signals = extract_answer_signals([{"role": "user", "content": prompt}])
    intent = resolve_output_intent(prompt, signals)

    assert intent.terminal_output == "docx_document"
    assert intent.docx_output_mode == "generated_docx"


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
    ("text", "expected_goal"),
    [
        (
            "Strukturera materialet till tydliga anteckningar och ett kort memo.",
            "structure_key_information",
        ),
        (
            "Ta fram rekommendationer och möjliga vägval från underlaget.",
            "decision_support",
        ),
        (
            "Granska dokumentet och identifiera risker, avvikelser och problem.",
            "risk_or_issue_review",
        ),
        (
            "Jämför underlaget mot checklistan och validera att kraven följs.",
            "compare_or_validate",
        ),
    ],
)
def test_infer_post_processing_goal_reaches_richer_goal_values(
    text: str,
    expected_goal: str,
) -> None:
    assert infer_post_processing_goal(text) == expected_goal


@pytest.mark.parametrize(
    "text",
    [
        "Jag vill ha ett transkriberingsflöde.",
        "Jag vill transkribera samtal.",
        "Create a transcription flow.",
    ],
)
def test_infer_post_processing_goal_does_not_treat_bare_transcription_as_done(
    text: str,
) -> None:
    assert infer_post_processing_goal(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Transkribera ljudet ordagrant utan sammanfattning.",
        "Transcript only, no summary.",
        "Transcribe meeting audio and produce a DOCX file with the transcription.",
    ],
)
def test_infer_post_processing_goal_detects_explicit_transcript_only(
    text: str,
) -> None:
    assert infer_post_processing_goal(text) == "stop_after_primary_operation"


def test_transcribe_document_request_does_not_imply_audio_input() -> None:
    intent = resolve_input_intent("Transkribera detta dokument.", {})

    assert intent.primary_runtime_input == "unknown"
    assert intent.audio_requested is False


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


def test_extract_answer_signals_treats_negated_swedish_runtime_fields_as_absent() -> (
    None
):
    signals = extract_answer_signals(
        [
            {
                "role": "user",
                "content": (
                    "Användaren ska inte fylla i extra formulärfält, metadatafält "
                    "eller inmatningsfält vid körning. Rapportfält som datum, "
                    "språk i ljudet, namn, kontaktuppgifter, risker och "
                    "osäkerheter ska hämtas från ljudet och transkriberingen."
                ),
            }
        ]
    )

    assert signals["runtime_metadata_fields"] == {"no_extra_metadata"}


def test_extract_answer_signals_treats_source_derived_report_fields_as_absent() -> None:
    signals = extract_answer_signals(
        [
            {
                "role": "user",
                "content": (
                    "Alla rapportfält ska hämtas från ljudet/transkriberingen: "
                    "datum, källa, språk i ljudet, ljudkvalitet, namn, "
                    "kontaktuppgifter, risker och osäkerheter. Om något saknas "
                    "ska rapporten skriva Ej nämnt i underlaget."
                ),
            }
        ]
    )

    assert signals["runtime_metadata_fields"] == {"no_extra_metadata"}


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


def test_extract_answer_signals_ignores_tool_requirements_summary_output_mode() -> None:
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

    assert signals == {}


def test_extract_answer_signals_ignores_tool_requirements_summary_input_mode() -> None:
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

    assert signals == {}


def test_extract_answer_signals_does_not_treat_edit_summary_as_user_answer() -> None:
    signals = extract_answer_signals(
        [
            {
                "role": "tool",
                "content": "Requirements presented to user.",
                "metadata": {
                    "requirements_summary": {
                        "input_description": "Primär indata vid körning: Dokument.",
                        "output_description": "Huvudsakligt slutresultat: DOCX-dokument.",
                    }
                },
            }
        ]
    )

    assert signals == {}


def test_requirements_summary_normalization_keeps_existing_audio_input() -> None:
    normalized = normalize_requirements_summary_for_flow(
        {
            "summary": "Flödet ska ta emot dokument och leverera DOCX.",
            "key_decisions": [
                {"topic": "Indata", "decision": "Dokument vid körning."},
                {"topic": "Output", "decision": "DOCX."},
            ],
            "input_description": "Primär indata vid körning: Dokument.",
            "output_description": "Huvudsakligt slutresultat: DOCX-dokument.",
            "assumptions": [],
            "manual_setup_notes": [],
        },
        conversation=[
            {
                "role": "user",
                "content": (
                    "Granska detta befintliga Flow för transkribering till DOCX "
                    "och förbättra det utan att ändra den avsedda produkten."
                ),
            }
        ],
        flow=_make_audio_docx_flow(),
        language="sv",
    )

    assert normalized["input_description"] == "Primär indata vid körning: ljud."
    assert normalized["key_decisions"][0] == {
        "topic": "Indata",
        "decision": "Behåll befintlig körningsindata: ljud.",
    }


def test_requirements_summary_normalization_preserves_explicit_input_change() -> None:
    requirements_data = {
        "summary": "Flödet ska ta emot dokument och leverera DOCX.",
        "key_decisions": [{"topic": "Indata", "decision": "Dokument vid körning."}],
        "input_description": "Primär indata vid körning: Dokument.",
        "output_description": "Huvudsakligt slutresultat: DOCX-dokument.",
        "assumptions": [],
        "manual_setup_notes": [],
    }

    normalized = normalize_requirements_summary_for_flow(
        requirements_data,
        conversation=[
            {
                "role": "user",
                "content": "Ändra indata så att användaren laddar upp dokument.",
            }
        ],
        flow=_make_audio_docx_flow(),
        language="sv",
    )

    assert normalized == requirements_data


def test_requirements_summary_normalization_preserves_create_mode_summary() -> None:
    requirements_data = {
        "summary": "Flödet ska ta emot dokument och leverera DOCX.",
        "key_decisions": [{"topic": "Indata", "decision": "Dokument vid körning."}],
        "input_description": "Primär indata vid körning: Dokument.",
        "output_description": "Huvudsakligt slutresultat: DOCX-dokument.",
        "assumptions": [],
        "manual_setup_notes": [],
    }

    normalized = normalize_requirements_summary_for_flow(
        requirements_data,
        conversation=[],
        flow=None,
        language="sv",
    )

    assert normalized == requirements_data


def test_planning_state_uses_existing_audio_input_when_edit_summary_drifts() -> None:
    state = build_planning_state_from_conversation(
        [
            ConversationMessage(
                role="user",
                content=(
                    "Granska detta befintliga Flow för transkribering till DOCX "
                    "och förbättra det utan att ändra den avsedda produkten."
                ),
            ),
            ConversationMessage(
                role="tool",
                content="Requirements presented to user.",
                metadata={
                    "requirements_summary": {
                        "summary": "Flödet ska ta emot dokument och leverera DOCX.",
                        "key_decisions": [
                            {
                                "topic": "Indata",
                                "decision": "Dokument vid körning.",
                            }
                        ],
                        "input_description": "Primär indata vid körning: Dokument.",
                        "output_description": (
                            "Huvudsakligt slutresultat: DOCX-dokument."
                        ),
                    }
                },
            ),
        ],
        flow=_make_audio_docx_flow(),
    )

    primary_runtime_input = state.resolved_slots["primary_runtime_input"]
    assert primary_runtime_input.value == "audio"
    assert primary_runtime_input.source == "flow_default"


def test_planning_state_uses_requirements_summary_without_flow_default() -> None:
    state = build_planning_state_from_conversation(
        [
            ConversationMessage(
                role="tool",
                content="Requirements presented to user.",
                metadata={
                    "requirements_summary": {
                        "summary": "Skapa en DOCX-rapport.",
                        "key_decisions": [
                            {"topic": "Output", "decision": "DOCX-dokument."}
                        ],
                        "input_description": "Primär indata vid körning: text.",
                        "output_description": (
                            "Huvudsakligt slutresultat: DOCX-dokument."
                        ),
                    }
                },
            )
        ],
    )

    terminal_output = state.resolved_slots["terminal_output"]
    assert terminal_output.value == "docx_document"
    assert terminal_output.source == "requirements_summary"


def test_resolve_output_intent_prefers_docx_output_role_over_pdf_input_reference() -> (
    None
):
    prompt = "Bygg ett flöde som tar ett uppladdat PDF-dokument och genererar en DOCX-rapport."
    signals = extract_answer_signals([{"role": "user", "content": prompt}])

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


def test_resolve_output_intent_detects_swedish_short_summary_output() -> None:
    prompt = "Jag vill kunna ladda upp ett dokument och få en kort sammanfattning."

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "structured_text"


def test_resolve_output_intent_does_not_treat_summary_reference_as_output() -> None:
    prompt = "Jag laddar upp en sammanfattning som referens."

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output is None


def test_resolve_output_intent_keeps_vague_file_review_unresolved() -> None:
    prompt = "Hjälp mig granska dom här filerna och förstå dom."

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output is None


def test_intermediate_json_extraction_with_final_prose_does_not_resolve_json() -> None:
    prompt = (
        "Användaren laddar upp 2-5 underlagsfiler. Flödet ska extrahera "
        "nyckelfakta som strukturerad JSON från varje fil eller från varje "
        "dokumentdel, sedan identifiera motsägelser mellan källorna i ett "
        "separat analyssteg, och slutligen skriva en sammanställning där "
        "fakta och motsägelser presenteras tydligt."
    )

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "structured_text"


def test_bare_structured_json_phrase_does_not_resolve_terminal_output() -> None:
    prompt = "Extrahera nyckelfakta som strukturerad JSON från varje dokument."

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output is None


def test_explicit_terminal_json_survives_intermediate_json_mentions() -> None:
    prompt = (
        "Extrahera nyckelfakta som strukturerad JSON från varje fil och "
        "jämför källorna. Slutresultatet ska vara JSON."
    )

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "structured_json"


def test_explicit_terminal_structured_json_survives_intermediate_json_mentions() -> (
    None
):
    prompt = (
        "Extrahera nyckelfakta som strukturerad JSON från varje fil och "
        "jämför källorna. Slutresultatet ska vara strukturerad JSON."
    )

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "structured_json"


@pytest.mark.parametrize(
    "prompt",
    [
        (
            "Build a flow that reads a long procurement document and returns "
            "strict JSON with ranked offers, risk flags, and missing information. "
            "Do not create Word, DOCX, PDF, or a document output."
        ),
        (
            "Analyze uploaded documents and return JSON only with the extracted "
            "obligations; no Word or DOCX file."
        ),
        (
            "Use the contract PDF as input, but the final answer must be JSON, "
            "not PDF or DOCX."
        ),
        (
            "Läs dokumentet och returnera strikt JSON med risker och luckor; "
            "skapa inte Word, DOCX, PDF eller dokument."
        ),
        (
            "Analysera PDF-underlaget men slutresultatet ska vara JSON, inte "
            "PDF eller DOCX."
        ),
        (
            "Ta emot dokument men leverera bara JSON med fält för status; "
            "inget Word-dokument."
        ),
        (
            "Slutresultatet ska vara strikt JSON med klassificeringar; "
            "Word-dokument behövs inte."
        ),
        "Leverera jsonfilen som slutresultat.",
        (
            "Analyze the procurement documents and return strict JSON with "
            "ranked suppliers and missing information."
        ),
    ],
)
def test_explicit_terminal_json_ignores_negated_document_artifacts(
    prompt: str,
) -> None:
    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "structured_json"
    assert intent.docx_output_mode is None
    assert intent.pdf_generation_mode is None


def test_later_positive_docx_marker_survives_earlier_negated_marker() -> None:
    prompt = "Skapa inte Word-utkast i mellansteget men leverera en Word-rapport."

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "docx_document"


def test_later_positive_pdf_marker_survives_earlier_negated_docx_marker() -> None:
    prompt = "Skapa inte Word-dokument, gör en PDF-rapport som slutresultat."

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "pdf_document"


def test_explicit_terminal_json_wins_over_final_prose_wording() -> None:
    prompt = (
        "Extrahera nyckelfakta som strukturerad JSON från varje fil och "
        "slutligen skriva en sammanställning för granskning. "
        "Slutresultatet ska vara JSON."
    )

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "structured_json"


def test_artifact_output_wins_over_final_prose_wording() -> None:
    prompt = "Bygg ett flöde där du slutligen skriva en sammanställning som Word-fil."

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "docx_document"


def test_intermediate_json_extraction_with_final_docx_keeps_docx() -> None:
    prompt = (
        "Extrahera nyckelfakta som strukturerad JSON från varje fil och "
        "skapa slutdokumentet som DOCX."
    )

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "docx_document"


def test_swedish_audio_review_docx_request_avoids_text_default_when_artifact_scoping_is_passive() -> (
    None
):
    prompt = (
        "Bygg ett flöde för en extern webbapp: användaren laddar upp ljud, "
        "får transkribering, en människa ska kunna granska och korrigera innan "
        "slutlig DOCX-rapport skapas. Flödet ska vara lätt att förstå via "
        "run-contract och använda strukturerad JSON där det hjälper."
    )

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output is None


def test_swedish_audio_review_docx_request_keeps_docx_despite_intermediate_json() -> (
    None
):
    prompt = (
        "Bygg ett flöde för en extern webbapp där användaren laddar upp ljud, "
        "får transkribering, kan granska och korrigera texten, och sedan får "
        "en slutlig DOCX-rapport. Använd strukturerad JSON där det hjälper "
        "API-konsumenten, men håll slutresultatet som dokument."
    )

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "docx_document"
    assert intent.docx_output_mode == "generated_docx"


def test_intermediate_json_extraction_with_final_pdf_keeps_pdf() -> None:
    prompt = (
        "Extrahera nyckelfakta som strukturerad JSON från varje fil och "
        "skapa slutrapporten som PDF."
    )

    intent = resolve_output_intent(
        prompt, extract_answer_signals([{"role": "user", "content": prompt}])
    )

    assert intent.terminal_output == "pdf_document"


def test_resolve_output_intent_structured_text_does_not_become_json_output() -> None:
    signals = extract_answer_signals([])

    intent = resolve_output_intent(
        "Strukturerad sammanställning som text.",
        signals,
    )

    assert intent.terminal_output == "structured_text"


def test_resolve_output_intent_ascii_structured_text_is_supported() -> None:
    signals = extract_answer_signals([])

    intent = resolve_output_intent(
        "Strukturerad sammanstallning som text.",
        signals,
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


def test_supported_structured_question_ids_partition_catalog_and_policy_ids() -> None:
    non_slot_policy_ids = frozenset(
        {
            "comparison_scope",
            "detail_level",
            "document_kind",
            "final_output_scope",
            "output_reader",
            "output_style",
            "output_tone",
            "processing_scope",
        }
    )

    assert frozenset(supported_structured_question_ids()) == (
        slot_resolving_legacy_question_ids() | non_slot_policy_ids
    )
    assert non_slot_policy_ids.isdisjoint(slot_resolving_legacy_question_ids())


@pytest.mark.parametrize(
    "question_id",
    [
        "final_output_mode",
        "flow_input_architecture",
        "final_pdf_type",
        "post_processing_goal",
        "structured_io_contract",
        "structured_analysis_need",
        "output_style",
        "output_tone",
        "detail_level",
    ],
)
def test_accepts_supported_structured_question_ids(question_id: str) -> None:
    assert is_supported_structured_question_id(question_id)


@pytest.mark.parametrize(
    "alias",
    [
        "file_handling_mode",
        "final_output_format",
        "final_output_type",
        "output_format",
        "primary_output_format",
        "upload_mode",
    ],
)
def test_structured_question_aliases_are_supported_but_not_public_ids(
    alias: str,
) -> None:
    assert is_supported_structured_question_id(alias)
    assert alias not in supported_structured_question_ids()


def test_rejects_unsupported_structured_question_ids() -> None:
    assert not is_supported_structured_question_id("multi_file_strategy")
