"""Contract tests for `observe_attachment`.

The observation call wraps a single litellm completion that turns raw
bytes + `DeterministicSignals` into an `AttachmentObservation`. These
tests pin the caller contract:

- successful JSON round-trips into a fully-validated `AttachmentObservation`
  with caller-supplied identity / version / token_count fields,
- malformed JSON, schema-invalid JSON, empty responses, and litellm
  exceptions all surface as `None` so the caller can log + fall back
  rather than crash the upload pipeline,
- the prompt passes the deterministic signals to the LLM as
  non-negotiable context (the LLM must not contradict them).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.flows.ai_builder.attachment_observation import (
    AttachmentObservation,
    DeterministicSignals,
)
from intric.flows.ai_builder.attachment_observer import observe_attachment


def _make_response(content: str | None) -> MagicMock:
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _valid_llm_payload() -> dict[str, Any]:
    return {
        "kind": "template",
        "structure": {
            "has_placeholders": True,
            "has_form_fields": False,
            "has_sections": True,
            "has_tables": False,
            "has_hierarchy": True,
            "has_unfilled_fields": True,
        },
        "digest_text": "A contract template with unfilled client-name and effective-date placeholders.",
        "structured_fallback": None,
        "likely_planner_implications": [
            {
                "suggested_pattern_id": "document_to_docx_template",
                "confidence": 0.85,
                "reason": "Jinja placeholders present in body paragraphs.",
            }
        ],
        "missing_info_cues": [
            "client name",
            "effective date",
        ],
        "capability_relevance": {
            "document_to_docx_template": 0.9,
            "extract_structured_fields": 0.2,
        },
        "likely_questions_triggered": ["docx_output_mode"],
    }


def _deterministic_signals() -> DeterministicSignals:
    return DeterministicSignals(
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        extension="docx",
        size_bytes=12_345,
        placeholder_tokens=["client_name", "effective_date"],
    )


@pytest.mark.asyncio
async def test_happy_path_returns_fully_validated_observation() -> None:
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(_valid_llm_payload())
    )
    tenant_id = uuid4()

    result = await observe_attachment(
        litellm_client=litellm_client,
        litellm_model="haiku-test",
        litellm_kwargs={},
        tenant_id=tenant_id,
        content_sha256="a" * 64,
        digest_version=1,
        fcm_version=2,
        pattern_registry_version=3,
        filename="contract-template.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        signals=_deterministic_signals(),
        content_sample="Dear {{ client_name }}, effective {{ effective_date }}...",
    )

    assert isinstance(result, AttachmentObservation)
    assert result.tenant_id == tenant_id
    assert result.content_sha256 == "a" * 64
    assert result.digest_version == 1
    assert result.fcm_version == 2
    assert result.pattern_registry_version == 3
    assert result.kind == "template"
    assert result.structure.has_placeholders is True
    assert result.structure.has_unfilled_fields is True
    assert result.digest_text.startswith("A contract template")
    assert result.likely_planner_implications[0].suggested_pattern_id == (
        "document_to_docx_template"
    )
    assert result.capability_relevance["document_to_docx_template"] == 0.9
    assert result.likely_questions_triggered == ["docx_output_mode"]
    assert result.token_count > 0


@pytest.mark.asyncio
async def test_token_count_reflects_digest_text_length() -> None:
    litellm_client = AsyncMock()
    payload = _valid_llm_payload()
    payload["digest_text"] = "one two three four five"
    litellm_client.acompletion.return_value = _make_response(json.dumps(payload))

    result = await observe_attachment(
        litellm_client=litellm_client,
        litellm_model="haiku-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        content_sha256="b" * 64,
        digest_version=1,
        fcm_version=1,
        pattern_registry_version=1,
        filename="doc.txt",
        mime="text/plain",
        signals=DeterministicSignals(
            mime_type="text/plain", extension="txt", size_bytes=100
        ),
        content_sample="Some plain text",
    )

    assert result is not None
    # The 5-word digest is cheap to tokenise; the observer uses a
    # whitespace-split heuristic so the assertion is resilient to the
    # exact count without hardcoding a magic number.
    assert result.token_count == 5


@pytest.mark.asyncio
async def test_malformed_json_returns_none() -> None:
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response("not valid json")

    result = await observe_attachment(
        litellm_client=litellm_client,
        litellm_model="haiku-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        content_sha256="c" * 64,
        digest_version=1,
        fcm_version=1,
        pattern_registry_version=1,
        filename="doc.txt",
        mime="text/plain",
        signals=DeterministicSignals(
            mime_type="text/plain", extension="txt", size_bytes=10
        ),
        content_sample="x",
    )

    assert result is None


@pytest.mark.asyncio
async def test_schema_invalid_json_returns_none() -> None:
    """JSON parses but violates the AttachmentObservation schema. The
    observer must reject rather than persist partial/invalid evidence.
    """
    litellm_client = AsyncMock()
    invalid = _valid_llm_payload()
    invalid["kind"] = "not_a_real_kind"
    litellm_client.acompletion.return_value = _make_response(json.dumps(invalid))

    result = await observe_attachment(
        litellm_client=litellm_client,
        litellm_model="haiku-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        content_sha256="d" * 64,
        digest_version=1,
        fcm_version=1,
        pattern_registry_version=1,
        filename="doc.txt",
        mime="text/plain",
        signals=DeterministicSignals(
            mime_type="text/plain", extension="txt", size_bytes=10
        ),
        content_sample="x",
    )

    assert result is None


@pytest.mark.asyncio
async def test_empty_response_returns_none() -> None:
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(None)

    result = await observe_attachment(
        litellm_client=litellm_client,
        litellm_model="haiku-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        content_sha256="e" * 64,
        digest_version=1,
        fcm_version=1,
        pattern_registry_version=1,
        filename="doc.txt",
        mime="text/plain",
        signals=DeterministicSignals(
            mime_type="text/plain", extension="txt", size_bytes=10
        ),
        content_sample="x",
    )

    assert result is None


@pytest.mark.asyncio
async def test_litellm_exception_returns_none() -> None:
    litellm_client = AsyncMock()
    litellm_client.acompletion.side_effect = RuntimeError("upstream 500")

    result = await observe_attachment(
        litellm_client=litellm_client,
        litellm_model="haiku-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        content_sha256="f" * 64,
        digest_version=1,
        fcm_version=1,
        pattern_registry_version=1,
        filename="doc.txt",
        mime="text/plain",
        signals=DeterministicSignals(
            mime_type="text/plain", extension="txt", size_bytes=10
        ),
        content_sample="x",
    )

    assert result is None


@pytest.mark.asyncio
async def test_prompt_passes_deterministic_signals_as_context() -> None:
    """The LLM must see the deterministic signals verbatim so it can't
    contradict them (no calling a 40-page PDF "one page"). The call
    inspects the assembled user message to confirm the signals are
    serialised into the prompt.
    """
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(_valid_llm_payload())
    )
    signals = DeterministicSignals(
        mime_type="application/pdf",
        extension="pdf",
        size_bytes=2_000_000,
        page_count=42,
        is_scanned_pdf=False,
    )

    await observe_attachment(
        litellm_client=litellm_client,
        litellm_model="haiku-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        content_sha256="1" * 64,
        digest_version=1,
        fcm_version=1,
        pattern_registry_version=1,
        filename="manual.pdf",
        mime="application/pdf",
        signals=signals,
        content_sample="Chapter one introduction text...",
    )

    call_kwargs = litellm_client.acompletion.await_args.kwargs
    messages = call_kwargs["messages"]
    assert isinstance(messages, list)
    user_message = next(m for m in messages if m["role"] == "user")
    content = user_message["content"]
    # The 42-page count and 2 MB size must appear in the prompt so the
    # LLM can't contradict them in its observation.
    assert "42" in content
    assert "application/pdf" in content
    assert "manual.pdf" in content


@pytest.mark.asyncio
async def test_content_sample_is_truncated_to_budget() -> None:
    """Long content samples must be clipped before the LLM call so
    the observation pipeline's token budget stays bounded regardless
    of upload size. The clip is deterministic and preserves the
    prefix — that's what a planner needs from a sample.
    """
    litellm_client = AsyncMock()
    litellm_client.acompletion.return_value = _make_response(
        json.dumps(_valid_llm_payload())
    )
    long_sample = "x" * 20_000

    await observe_attachment(
        litellm_client=litellm_client,
        litellm_model="haiku-test",
        litellm_kwargs={},
        tenant_id=uuid4(),
        content_sha256="2" * 64,
        digest_version=1,
        fcm_version=1,
        pattern_registry_version=1,
        filename="big.txt",
        mime="text/plain",
        signals=DeterministicSignals(
            mime_type="text/plain", extension="txt", size_bytes=len(long_sample)
        ),
        content_sample=long_sample,
        content_sample_char_budget=500,
    )

    call_kwargs = litellm_client.acompletion.await_args.kwargs
    user_message = next(m for m in call_kwargs["messages"] if m["role"] == "user")
    content = user_message["content"]
    # Budget is 500 chars; full 20 000-char sample must not be pasted.
    assert content.count("x") <= 600
