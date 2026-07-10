from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.flows.ai_builder import ai_builder_slot_classifier as classifier
from eneo.flows.ai_builder.ai_builder_slot_classifier import (
    classify_slots,
    parse_slot_classification_response,
    slot_classification_prompt_hash,
)


def _make_response(content: str) -> MagicMock:
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def test_parse_slot_classification_response_uses_canonical_slots_shape_only() -> None:
    result = parse_slot_classification_response(
        json.dumps(
            {
                "signals": [
                    {
                        "question_id": "terminal_output",
                        "value": "pdf_document",
                        "confidence": "high",
                        "reason": "old shape",
                    }
                ]
            }
        ),
        allowed_slot_values={"terminal_output": {"pdf_document"}},
    )

    assert result is not None
    assert result.slots == ()


def test_parse_slot_classification_response_filters_invalid_entries() -> None:
    result = parse_slot_classification_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "terminal_output",
                        "value": "pdf_document",
                        "confidence": "high",
                        "reason": "explicit PDF report",
                        "evidence": ["Slutrapporten ska vara en pdf fil"],
                        "evidence_level": "explicit",
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "structured_text",
                        "confidence": "high",
                        "reason": "duplicate",
                    },
                    {
                        "slot_name": "terminal_output",
                        "value": "invented",
                        "confidence": "high",
                        "reason": "invalid value",
                    },
                    {
                        "slot_name": "invented_slot",
                        "value": "pdf_document",
                        "confidence": "high",
                        "reason": "invalid slot",
                    },
                    {
                        "slot_name": "primary_runtime_input",
                        "value": "unknown",
                        "confidence": "low",
                        "reason": "ambiguous input",
                        "evidence": ["en eller flera filer"],
                    },
                ],
                "assumptions": ["PDF is requested"],
                "contradictions": ["input is ambiguous"],
            }
        ),
        allowed_slot_values={
            "terminal_output": {"pdf_document", "structured_text"},
            "primary_runtime_input": {"text", "documents"},
        },
    )

    assert result is not None
    assert [slot.slot_name for slot in result.slots] == [
        "terminal_output",
        "primary_runtime_input",
    ]
    assert result.slots[0].value == "pdf_document"
    assert result.slots[1].value == "unknown"
    assert result.slots[0].evidence == ("Slutrapporten ska vara en pdf fil",)
    assert result.slots[0].evidence_level == "explicit"
    assert result.slots[1].evidence_level == "inferred"
    assert result.assumptions == ("PDF is requested",)
    assert result.contradictions == ("input is ambiguous",)


def test_parse_slot_classification_response_downgrades_unsupported_claims() -> None:
    result = parse_slot_classification_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "terminal_output",
                        "value": "pdf_document",
                        "confidence": "high",
                        "reason": "unsupported",
                    },
                ],
                "file_roles": [
                    {
                        "file_id": str(uuid4()),
                        "role": "example_output",
                        "confidence": "high",
                        "reason": "unsupported file role",
                    },
                ],
            }
        ),
        allowed_slot_values={"terminal_output": {"pdf_document"}},
    )

    assert result is not None
    assert result.slots[0].confidence == "low"
    assert result.slots[0].evidence == ()
    assert result.file_roles[0].confidence == "low"
    assert result.file_roles[0].evidence == ()


def test_parse_slot_classification_response_filters_secondary_obligations() -> None:
    result = parse_slot_classification_response(
        json.dumps(
            {
                "slots": [],
                "secondary_obligations": [
                    "risks",
                    "actions",
                    "risks",
                    "invented",
                ],
            }
        ),
        allowed_slot_values={"post_processing_goal": {"compare_or_validate"}},
    )

    assert result is not None
    assert result.secondary_obligations == ("risks", "actions")


def test_parse_slot_classification_response_filters_file_roles() -> None:
    file_id = uuid4()
    result = parse_slot_classification_response(
        json.dumps(
            {
                "slots": [],
                "file_roles": [
                    {
                        "file_id": str(file_id),
                        "role": "example_output",
                        "confidence": "medium",
                        "reason": "user says this PDF shows the desired report",
                        "evidence": ["den här PDF:en visar önskad rapport"],
                    },
                    {
                        "file_id": str(file_id),
                        "role": "reference_material",
                        "confidence": "high",
                        "reason": "duplicate file id",
                    },
                    {
                        "file_id": str(uuid4()),
                        "role": "invented",
                        "confidence": "high",
                        "reason": "invalid role",
                    },
                    {
                        "file_id": "not-a-uuid",
                        "role": "example_output",
                        "confidence": "high",
                        "reason": "invalid file id",
                    },
                ],
            }
        ),
        allowed_slot_values={},
    )

    assert result is not None
    assert len(result.file_roles) == 1
    assert result.file_roles[0].file_id == file_id
    assert result.file_roles[0].role == "example_output"
    assert result.file_roles[0].confidence == "medium"
    assert result.file_roles[0].evidence == ("den här PDF:en visar önskad rapport",)


def test_parse_slot_classification_response_accepts_explicit_uncertainty() -> None:
    result = parse_slot_classification_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "terminal_output",
                        "value": "unknown",
                        "confidence": "high",
                        "reason": "user_explicit_uncertain",
                        "evidence": ["Jag vet inte exakt vilket format"],
                    },
                ],
            }
        ),
        allowed_slot_values={"terminal_output": {"docx_document", "structured_text"}},
    )

    assert result is not None
    assert len(result.slots) == 1
    slot = result.slots[0]
    assert slot.slot_name == "terminal_output"
    assert slot.value == "unknown"
    assert slot.confidence == "high"
    assert slot.reason == "user_explicit_uncertain"
    assert slot.evidence == ("Jag vet inte exakt vilket format",)


def test_parse_slot_classification_response_accepts_form_intake_evidence() -> None:
    result = parse_slot_classification_response(
        json.dumps(
            {
                "slots": [],
                "form_intake": {
                    "needs_form_fields": True,
                    "sectioned_form_intake": True,
                    "confidence": "high",
                    "reason": "runtime free text per heading",
                    "evidence": ["fritext under varje rubrik"],
                },
            }
        ),
        allowed_slot_values={},
    )

    assert result is not None
    assert result.form_intake is not None
    assert result.form_intake.needs_form_fields is True
    assert result.form_intake.sectioned_form_intake is True
    assert result.form_intake.confidence == "high"
    assert result.form_intake.evidence == ("fritext under varje rubrik",)


def test_parse_slot_classification_response_downgrades_unsupported_form_intake() -> (
    None
):
    result = parse_slot_classification_response(
        json.dumps(
            {
                "slots": [],
                "form_intake": {
                    "needs_form_fields": True,
                    "sectioned_form_intake": False,
                    "confidence": "high",
                    "reason": "unsupported form fields",
                },
            }
        ),
        allowed_slot_values={},
    )

    assert result is not None
    assert result.form_intake is not None
    assert result.form_intake.confidence == "low"
    assert result.form_intake.evidence == ()


def test_prompt_hash_uses_sorted_names_and_stable_json_serialization() -> None:
    text = "Sammanfatta ärendet"

    prompt_hash = slot_classification_prompt_hash(
        text=text,
        ui_language="sv",
        allowed_slot_values={
            "terminal_output": {"pdf_document", "structured_text"},
            "primary_runtime_input": {"audio", "documents"},
        },
    )

    assert prompt_hash == slot_classification_prompt_hash(
        text=text,
        ui_language="sv",
        allowed_slot_values={
            "primary_runtime_input": {"documents", "audio"},
            "terminal_output": {"structured_text", "pdf_document"},
        },
    )
    assert (
        prompt_hash
        == classifier.hashlib.sha256(
            json.dumps(
                {
                    "allowed_slot_values": {
                        "primary_runtime_input": ["audio", "documents"],
                        "terminal_output": ["pdf_document", "structured_text"],
                    },
                    "schema_version": 12,
                    "text": text,
                    "ui_language": "sv",
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
    )


def test_prompt_hash_changes_when_allowed_slot_values_change() -> None:
    base_hash = slot_classification_prompt_hash(
        text="Sammanfatta ärendet",
        ui_language="sv",
        allowed_slot_values={"terminal_output": {"pdf_document"}},
    )

    changed_hash = slot_classification_prompt_hash(
        text="Sammanfatta ärendet",
        ui_language="sv",
        allowed_slot_values={"terminal_output": {"pdf_document", "structured_text"}},
    )

    assert changed_hash != base_hash


def test_prompt_hash_changes_when_classification_bias_is_present() -> None:
    allowed = {"terminal_output": {"docx_document", "structured_text"}}
    base_hash = slot_classification_prompt_hash(
        text="en fil jag kan ladda ner",
        ui_language="sv",
        allowed_slot_values=allowed,
    )

    biased_hash = slot_classification_prompt_hash(
        text="en fil jag kan ladda ner",
        ui_language="sv",
        allowed_slot_values=allowed,
        bias=classifier.SlotClassificationBias(
            target_slot_name="terminal_output",
            asked_question_id="final_output_mode",
            latest_user_answer="en fil jag kan ladda ner",
        ),
    )

    # A biased targeted answer must not reuse the unbiased aggregate cache entry.
    assert biased_hash != base_hash


def test_prompt_hash_changes_when_uploaded_file_evidence_changes() -> None:
    allowed = {"terminal_output": {"docx_document", "structured_text"}}
    base_hash = slot_classification_prompt_hash(
        text="Jag vill bygga ett transkriberingsflöde.",
        ui_language="sv",
        allowed_slot_values=allowed,
        uploaded_file_evidence="filename: mall.docx\nfile_type: document",
    )

    changed_hash = slot_classification_prompt_hash(
        text="Jag vill bygga ett transkriberingsflöde.",
        ui_language="sv",
        allowed_slot_values=allowed,
        uploaded_file_evidence="filename: lagtext.pdf\nfile_type: document",
    )

    assert changed_hash != base_hash


def test_classification_prompt_emphasizes_the_biased_target_slot() -> None:
    messages = classifier._build_slot_classification_prompt(
        text="en fil jag kan ladda ner",
        allowed_slot_values={"terminal_output": frozenset({"docx_document"})},
        ui_language="sv",
        bias=classifier.SlotClassificationBias(
            target_slot_name="terminal_output",
            asked_question_id="final_output_mode",
            latest_user_answer="en fil jag kan ladda ner",
        ),
    )

    user_prompt = messages[-1]["content"]
    assert "terminal_output" in user_prompt
    assert "en fil jag kan ladda ner" in user_prompt


def test_classification_prompt_includes_unconfirmed_uploaded_file_evidence() -> None:
    messages = classifier._build_slot_classification_prompt(  # noqa: SLF001
        text="Jag vill bygga ett transkriberingsflöde.",
        allowed_slot_values={
            "primary_runtime_input": frozenset({"audio", "documents"}),
            "terminal_output": frozenset({"docx_document", "structured_text"}),
        },
        ui_language="sv",
        uploaded_file_evidence=(
            "filename: beslutsmall.docx\nfile_type: document\nhas_readable_text: false"
        ),
    )

    prompt = "\n".join(message["content"] for message in messages)
    assert "Unconfirmed uploaded-file evidence" in prompt
    assert "not confirmed user requirements" in prompt
    assert "filename: beslutsmall.docx" in prompt
    assert "has_readable_text: false" in prompt


def test_classification_prompt_places_evidence_bounds_in_model_contract() -> None:
    messages = classifier._build_slot_classification_prompt(  # noqa: SLF001
        text="Jag vill ha en PDF-rapport.",
        allowed_slot_values={"terminal_output": frozenset({"pdf_document"})},
        ui_language="sv",
    )

    prompt = "\n".join(message["content"] for message in messages)

    assert f"1-{classifier.CLASSIFICATION_EVIDENCE_MAX_ITEMS} evidence quotes" in prompt
    assert f"at most {classifier.CLASSIFICATION_EVIDENCE_MAX_LENGTH}" in prompt
    assert "exact_quote_str" in prompt
    assert "form_intake" in prompt
    assert (
        "Do not classify final report headings or output sections as form intake"
        in prompt
    )


def test_classification_prompt_treats_explicit_uncertainty_as_unknown() -> None:
    messages = classifier._build_slot_classification_prompt(
        text=(
            "Jag vet inte exakt vilket format slutresultatet ska vara ännu, "
            "men det ska kännas professionellt och lätt att läsa."
        ),
        allowed_slot_values={
            "terminal_output": frozenset({"docx_document", "structured_text"}),
        },
        ui_language="sv",
    )

    prompt = "\n".join(message["content"] for message in messages)
    assert "explicitly says they do not know" in prompt
    assert "`unknown`" in prompt
    assert "`high`" in prompt
    assert "user_explicit_uncertain" in prompt
    assert "do not choose the most likely option" in prompt


@pytest.mark.asyncio
async def test_classify_slots_reuses_shared_cache_for_identical_targets() -> None:
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [
                    {
                        "slot_name": "terminal_output",
                        "value": "pdf_document",
                        "confidence": "high",
                        "reason": "PDF report requested",
                        "evidence": ["få en PDF-rapport"],
                    }
                ]
            }
        )
    )
    text = f"cache-target-{uuid4()}"
    allowed_values = {"terminal_output": {"pdf_document"}}

    first = await classify_slots(
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        text=text,
        allowed_slot_values=allowed_values,
        tenant_id=uuid4(),
        ui_language="sv",
    )
    second = await classify_slots(
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        text=text,
        allowed_slot_values=allowed_values,
        tenant_id=uuid4(),
        ui_language="sv",
    )

    assert first is not None
    assert second is not None
    assert first.cached is False
    assert second.cached is True
    assert litellm_client.acompletion.await_count == 1


@pytest.mark.asyncio
async def test_classify_slots_requests_bounded_json_schema_response_format() -> None:
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(
            {
                "slots": [],
                "file_roles": [],
                "form_intake": None,
                "secondary_obligations": [],
                "assumptions": [],
                "contradictions": [],
            }
        )
    )

    await classify_slots(
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        text=f"json-format-target-{uuid4()}",
        allowed_slot_values={"primary_runtime_input": {"audio", "documents"}},
        tenant_id=uuid4(),
        ui_language="sv",
    )

    response_format = litellm_client.acompletion.await_args.kwargs["response_format"]
    assert response_format["type"] == "json_schema"
    json_schema = response_format["json_schema"]
    assert json_schema["name"] == "ai_builder_slot_classification_v12"
    assert json_schema["strict"] is False

    schema = json_schema["schema"]
    assert schema["required"] == [
        "slots",
        "file_roles",
        "form_intake",
        "secondary_obligations",
        "assumptions",
        "contradictions",
    ]
    assert schema["additionalProperties"] is False
    slot_schema = schema["properties"]["slots"]
    assert slot_schema["maxItems"] == 1
    slot_variant = slot_schema["items"]["anyOf"][0]
    assert slot_variant["properties"]["slot_name"] == {
        "type": "string",
        "enum": ["primary_runtime_input"],
    }
    assert slot_variant["properties"]["value"]["enum"] == [
        "audio",
        "documents",
        "unknown",
    ]
    assert "evidence_level" in slot_variant["required"]
    assert slot_variant["properties"]["evidence_level"]["enum"] == [
        "explicit",
        "inferred",
    ]
    assert (
        slot_variant["properties"]["reason"]["maxLength"]
        == classifier.CLASSIFICATION_REASON_MAX_LENGTH
    )
    assert (
        slot_variant["properties"]["evidence"]["maxItems"]
        == classifier.CLASSIFICATION_EVIDENCE_MAX_ITEMS
    )
    assert (
        slot_variant["properties"]["evidence"]["items"]["maxLength"]
        == classifier.CLASSIFICATION_EVIDENCE_MAX_LENGTH
    )
    assert (
        schema["properties"]["assumptions"]["maxItems"]
        == classifier.CLASSIFICATION_NOTES_MAX_ITEMS
    )
    assert (
        schema["properties"]["assumptions"]["items"]["maxLength"]
        == classifier.CLASSIFICATION_NOTE_MAX_LENGTH
    )


def test_slot_classification_prompt_separates_source_material_from_artifacts() -> None:
    messages = classifier._build_slot_classification_prompt(  # noqa: SLF001
        text="Ladda upp en ljudfil och få ett Word-dokument.",
        allowed_slot_values={
            "primary_runtime_input": frozenset({"audio", "documents"}),
        },
        ui_language="sv",
    )

    prompt = "\n".join(message["content"] for message in messages)
    assert "requested final document is terminal_output" in prompt
    assert "structured JSON mentioned as helpful intermediate/API context" in prompt
    assert "uploaded or recorded speech for transcription is audio input" in prompt


def test_slot_classification_prompt_explains_report_disposition_values() -> None:
    messages = classifier._build_slot_classification_prompt(  # noqa: SLF001
        text="Skriv ett rapportavsnitt för varje uppladdat dokument.",
        allowed_slot_values={
            "report_disposition": frozenset(
                {"both", "per_source_sections", "synthesized_overview"}
            ),
        },
        ui_language="sv",
    )

    prompt = "\n".join(message["content"] for message in messages)
    assert "For report_disposition" in prompt
    assert "per_source_sections" in prompt
    assert "synthesized_overview" in prompt
    assert "both" in prompt
    assert "each uploaded source" in prompt


def test_slot_classification_prompt_explains_example_output_evidence() -> None:
    messages = classifier._build_slot_classification_prompt(  # noqa: SLF001
        text="Bygg en rapport utifrån uppladdade dokument.",
        uploaded_file_evidence=(
            "file_id: 00000000-0000-0000-0000-000000000111\n"
            "filename: bilaga.pdf\n"
            "excerpt: så här ska rapporten se ut"
        ),
        allowed_slot_values={
            "report_disposition": frozenset(
                {"both", "per_source_sections", "synthesized_overview"}
            ),
        },
        ui_language="sv",
    )

    prompt = "\n".join(message["content"] for message in messages)
    assert "example_output means the user attached a file as an example" in prompt
    assert '"evidence": [exact_quote_str]' in prompt
    assert "attachment-only conclusions as medium confidence" in prompt
    assert '"file_roles": [{"file_id": str, "role": str' in prompt
    assert "Use the conversation and file evidence together" in prompt
    assert "Do not wait for deterministic inferred_role example_output" in prompt
    assert "report_disposition, terminal_output" in prompt
    assert "filename: bilaga.pdf" in prompt
    assert "så här ska rapporten se ut" in prompt


def test_slot_classification_system_prompt_stays_domain_neutral() -> None:
    messages = classifier._build_slot_classification_prompt(  # noqa: SLF001
        text="Skapa ett generellt flöde.",
        allowed_slot_values={
            "primary_runtime_input": frozenset({"audio", "documents", "text"}),
            "terminal_output": frozenset({"structured_json", "structured_text"}),
        },
        ui_language="sv",
    )

    system_prompt = messages[0]["content"].casefold()
    banned_tokens = (
        "case description",
        "beslutsunderlag",
        "ärende",
        "handlägg",
        "remiss",
        "tjänsteskriv",
    )
    for token in banned_tokens:
        assert token not in system_prompt


@pytest.mark.asyncio
async def test_classify_slots_logs_tenant_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps({"slots": [], "assumptions": [], "contradictions": []})
    )
    log_calls: list[dict[str, object]] = []

    def capture_info(_: str, *, extra: dict[str, object]) -> None:
        log_calls.append(extra)

    monkeypatch.setattr(classifier.logger, "info", capture_info)
    tenant_id = uuid4()

    await classify_slots(
        litellm_client=litellm_client,
        litellm_model="gpt-test",
        litellm_kwargs={},
        text=f"log-target-{uuid4()}",
        allowed_slot_values={"terminal_output": {"pdf_document"}},
        tenant_id=tenant_id,
        ui_language="sv",
    )

    assert log_calls
    assert log_calls[-1]["tenant_id"] == str(tenant_id)
    assert log_calls[-1]["model"] == "gpt-test"
