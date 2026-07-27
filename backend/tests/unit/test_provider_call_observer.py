from __future__ import annotations

import pytest

from eneo.completion_models.domain.provider_call_observer import (
    ProviderCallObserverError,
    build_provider_call_request_facts,
)


def _golden_request_facts(*, temperature: float = 0.2):
    return build_provider_call_request_facts(
        requested_model="openai/gpt-5-mini",
        provider="openai",
        messages=[
            {"role": "system", "content": "prompt"},
            {"role": "user", "content": "question with rag A"},
        ],
        request_kwargs={
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        },
        reason="initial",
    )


def test_request_facts_preserve_the_version_one_fingerprint_contract() -> None:
    facts = _golden_request_facts()

    assert facts.request_schema_version == 1
    assert (
        facts.provider_request_hash
        == "52cfe10b0461c01100e6f2643ca3b296baf8fcac9c88dae0ff521c98b0eb9f5a"
    )


def test_request_fingerprint_changes_when_existing_hash_material_changes() -> None:
    assert (
        _golden_request_facts(temperature=0.3).provider_request_hash
        != _golden_request_facts().provider_request_hash
    )


def test_request_facts_derive_canonical_capabilities_from_effective_request() -> None:
    facts = build_provider_call_request_facts(
        requested_model="openai/test-model",
        provider="openai",
        messages=[
            {"role": "system", "content": "Answer accurately."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this image."},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AA=="},
                    },
                ],
            },
        ],
        request_kwargs={
            "reasoning_effort": "medium",
            "response_format": {"type": "json_schema"},
            "tools": [{"type": "function", "function": {"name": "lookup"}}],
        },
        reason="initial",
    )

    assert facts.request_schema_version == 1
    assert facts.requested_capabilities == (
        "image_input",
        "reasoning",
        "structured_output",
        "tool_calling",
    )


@pytest.mark.parametrize("content", ["plain text", None, ["not-a-block", None]])
def test_request_facts_tolerate_non_image_message_content(content: object) -> None:
    facts = build_provider_call_request_facts(
        requested_model="openai/test-model",
        provider="openai",
        messages=[{"role": "assistant", "content": content}],
        request_kwargs={
            "reasoning_effort": "none",
            "response_format": {"type": "text"},
            "tools": [],
        },
        reason="tool_round",
    )

    assert facts.response_format == "other"
    assert facts.requested_capabilities == ()


def test_non_serializable_hash_material_is_rejected_without_leaking() -> None:
    with pytest.raises(ProviderCallObserverError) as exc_info:
        build_provider_call_request_facts(
            requested_model="openai/test-model",
            provider="openai",
            messages=[{"role": "user", "content": "hello"}],
            request_kwargs={"stop": object()},
            reason="initial",
        )

    assert (
        str(exc_info.value)
        == "Provider request evidence could not be serialized safely."
    )
    assert "object" not in str(exc_info.value)


def test_request_facts_reject_recursive_hash_material() -> None:
    recursive_stop: list[object] = []
    recursive_stop.append(recursive_stop)

    with pytest.raises(ProviderCallObserverError):
        build_provider_call_request_facts(
            requested_model="openai/test-model",
            provider="openai",
            messages=[{"role": "user", "content": "hello"}],
            request_kwargs={"stop": recursive_stop},
            reason="initial",
        )
