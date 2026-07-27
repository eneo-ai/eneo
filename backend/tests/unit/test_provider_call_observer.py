from __future__ import annotations

from typing import Mapping, Sequence, cast

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


def test_request_facts_preserve_the_version_two_fingerprint_contract() -> None:
    facts = _golden_request_facts()

    assert facts.request_schema_version == 2
    assert (
        facts.provider_request_hash
        == "eef28b63aba95721aed6c663f946c2a2eb2b2a5d974b01c7c4c990e8ccd46fe8"
    )


@pytest.mark.parametrize(
    ("overrides", "request_kwargs"),
    [
        ({"requested_model": "openai/gpt-5"}, {}),
        ({"provider": "azure"}, {}),
        (
            {
                "messages": [
                    {"role": "system", "content": "different prompt"},
                    {"role": "user", "content": "question with rag A"},
                ]
            },
            {},
        ),
        (
            {
                "messages": [
                    {"role": "system", "content": "prompt"},
                    {"role": "user", "content": "different question"},
                ]
            },
            {},
        ),
        (
            {
                "messages": [
                    {"role": "system", "content": "prompt"},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "question with rag A"},
                            {
                                "type": "file",
                                "file": {"file_id": "included-file-1"},
                            },
                        ],
                    },
                ]
            },
            {},
        ),
        (
            {
                "messages": [
                    {"role": "system", "content": "prompt"},
                    {"role": "user", "content": "question with rag B"},
                ]
            },
            {},
        ),
        ({}, {"temperature": 0.3}),
    ],
)
def test_request_fingerprint_changes_with_effective_request_material(
    overrides: dict[str, object], request_kwargs: dict[str, object]
) -> None:
    baseline = _golden_request_facts()
    candidate = build_provider_call_request_facts(
        requested_model=str(overrides.get("requested_model", "openai/gpt-5-mini")),
        provider=str(overrides.get("provider", "openai")),
        messages=cast(
            Sequence[Mapping[str, object]],
            overrides.get(
                "messages",
                [
                    {"role": "system", "content": "prompt"},
                    {"role": "user", "content": "question with rag A"},
                ],
            ),
        ),
        request_kwargs={
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            **request_kwargs,
        },
        reason="initial",
    )

    assert candidate.provider_request_hash != baseline.provider_request_hash


def test_request_fingerprint_ignores_non_effective_adapter_kwargs() -> None:
    baseline = _golden_request_facts()
    candidate = build_provider_call_request_facts(
        requested_model="openai/gpt-5-mini",
        provider="openai",
        messages=[
            {"role": "system", "content": "prompt"},
            {"role": "user", "content": "question with rag A"},
        ],
        request_kwargs={
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "adapter_trace_context": "not sent to provider",
        },
        reason="initial",
    )

    assert candidate.provider_request_hash == baseline.provider_request_hash


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

    assert facts.request_schema_version == 2
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


@pytest.mark.parametrize(
    ("requested_model", "provider"),
    [("", "openai"), ("openai/test-model", "")],
)
def test_request_facts_reject_empty_model_identifiers(
    requested_model: str, provider: str
) -> None:
    with pytest.raises(
        ProviderCallObserverError,
        match="requires non-empty model identifiers",
    ):
        build_provider_call_request_facts(
            requested_model=requested_model,
            provider=provider,
            messages=[{"role": "user", "content": "hello"}],
            request_kwargs={},
            reason="initial",
        )


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
