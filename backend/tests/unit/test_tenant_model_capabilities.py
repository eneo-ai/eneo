from unittest.mock import patch

import pytest

from eneo.completion_models.infrastructure.tenant_model_capabilities import (
    StructuredOutputCapabilityDecision,
    StructuredOutputDecisionSource,
    StructuredOutputMode,
    resolve_reasoning_effort_options,
    resolve_structured_output_capability,
    schema_response_format,
    unsupported_structured_output_decision,
)


def test_reasoning_effort_options_follow_litellm_model_metadata() -> None:
    with (
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.get_supported_openai_params",
            return_value=("reasoning_effort", "verbosity"),
        ),
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm.get_model_info",
            return_value={
                "supports_reasoning": True,
                "supports_none_reasoning_effort": True,
                "supports_minimal_reasoning_effort": False,
                "supports_low_reasoning_effort": None,
                "supports_xhigh_reasoning_effort": True,
            },
        ),
    ):
        options = resolve_reasoning_effort_options(
            litellm_model="openai/gpt-5.6-terra",
            provider_type="openai",
        )

    assert options == ("none", "low", "medium", "high", "xhigh")


def test_reasoning_effort_options_honor_litellm_level_flags() -> None:
    with (
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.get_supported_openai_params",
            return_value=("reasoning_effort",),
        ),
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm.get_model_info",
            return_value={
                "supports_reasoning": True,
                "supports_minimal_reasoning_effort": True,
                "supports_low_reasoning_effort": False,
                "supports_xhigh_reasoning_effort": False,
            },
        ),
    ):
        options = resolve_reasoning_effort_options(
            litellm_model="openai/reasoning-model",
            provider_type="openai",
        )

    assert options == ("minimal", "medium", "high")


def test_reasoning_effort_options_include_max_only_when_litellm_confirms_it() -> None:
    with (
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.get_supported_openai_params",
            return_value=("reasoning_effort",),
        ),
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm.get_model_info",
            return_value={
                "supports_reasoning": True,
                "supports_low_reasoning_effort": None,
                "supports_xhigh_reasoning_effort": False,
                "supports_max_reasoning_effort": True,
            },
        ),
    ):
        options = resolve_reasoning_effort_options(
            litellm_model="anthropic/claude-opus-4-6",
            provider_type="anthropic",
        )

    assert options == ("low", "medium", "high", "max")


def test_reasoning_effort_options_fail_closed_without_provider_support() -> None:
    with patch(
        "eneo.completion_models.infrastructure.tenant_model_capabilities.get_supported_openai_params",
        return_value=("temperature",),
    ):
        options = resolve_reasoning_effort_options(
            litellm_model="openai/plain-model",
            provider_type="openai",
        )

    assert options == ()


def test_reasoning_effort_options_fail_closed_when_metadata_is_unavailable() -> None:
    with (
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.get_supported_openai_params",
            return_value=("reasoning_effort",),
        ),
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.litellm.get_model_info",
            side_effect=RuntimeError("metadata unavailable"),
        ),
    ):
        options = resolve_reasoning_effort_options(
            litellm_model="openai/custom-model",
            provider_type="openai",
        )

    assert options == ()


def test_schema_support_selects_strict_json_schema() -> None:
    with (
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.supports_response_schema",
            return_value=True,
        ) as schema_support,
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.get_supported_openai_params",
            return_value=("response_format",),
        ) as supported_params,
    ):
        decision = resolve_structured_output_capability(
            litellm_model="openai/gpt-4o-mini",
            provider_type="openai",
        )

    assert decision.mode is StructuredOutputMode.STRICT_JSON_SCHEMA
    assert decision.source is StructuredOutputDecisionSource.LITELLM_RESPONSE_SCHEMA
    assert decision.supports_response_schema is True
    assert decision.supports_response_format is True
    schema_support.assert_called_once_with(
        model="openai/gpt-4o-mini",
        custom_llm_provider="openai",
    )
    supported_params.assert_called_once_with(
        model="openai/gpt-4o-mini",
        custom_llm_provider="openai",
    )


def test_response_format_without_schema_selects_json_object() -> None:
    with (
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.supports_response_schema",
            return_value=False,
        ),
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.get_supported_openai_params",
            return_value=("temperature", "response_format"),
        ),
    ):
        decision = resolve_structured_output_capability(
            litellm_model="openai/gpt-3.5-turbo",
            provider_type="openai",
        )

    assert decision.mode is StructuredOutputMode.JSON_OBJECT
    assert decision.source is StructuredOutputDecisionSource.LITELLM_RESPONSE_FORMAT
    assert decision.supports_response_schema is False
    assert decision.supports_response_format is True


def test_no_provider_support_selects_prompt_validation() -> None:
    with (
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.supports_response_schema",
            return_value=False,
        ),
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.get_supported_openai_params",
            return_value=("temperature",),
        ),
    ):
        decision = resolve_structured_output_capability(
            litellm_model="anthropic/claude-3-5-haiku-20241022",
            provider_type="anthropic",
        )

    assert decision.mode is StructuredOutputMode.PROMPT_WITH_PYDANTIC_VALIDATION
    assert decision.source is StructuredOutputDecisionSource.NO_PROVIDER_SUPPORT
    assert decision.supports_response_schema is False
    assert decision.supports_response_format is False


def test_support_check_failures_fall_back_to_prompt_validation() -> None:
    with (
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.supports_response_schema",
            side_effect=RuntimeError("schema metadata failed"),
        ),
        patch(
            "eneo.completion_models.infrastructure.tenant_model_capabilities.get_supported_openai_params",
            side_effect=RuntimeError("param metadata failed"),
        ),
    ):
        decision = resolve_structured_output_capability(
            litellm_model="custom/model",
            provider_type="openai",
        )

    assert decision.mode is StructuredOutputMode.PROMPT_WITH_PYDANTIC_VALIDATION
    assert decision.source is StructuredOutputDecisionSource.NO_PROVIDER_SUPPORT
    assert decision.supports_response_schema is None
    assert decision.supports_response_format is None


def test_unsupported_structured_output_decision_preserves_probe_evidence() -> None:
    decision = unsupported_structured_output_decision(
        supports_response_schema=False,
        supports_response_format=None,
    )

    assert decision.mode is StructuredOutputMode.PROMPT_WITH_PYDANTIC_VALIDATION
    assert decision.source is StructuredOutputDecisionSource.NO_PROVIDER_SUPPORT
    assert decision.supports_response_schema is False
    assert decision.supports_response_format is None


def test_decision_rejects_inconsistent_fields() -> None:
    with pytest.raises(ValueError, match="response-schema decisions"):
        StructuredOutputCapabilityDecision(
            mode=StructuredOutputMode.JSON_OBJECT,
            source=StructuredOutputDecisionSource.LITELLM_RESPONSE_SCHEMA,
            supports_response_schema=True,
            supports_response_format=True,
        )


@pytest.mark.parametrize(
    "keyword", ["uniqueItems", "contains", "$ref", "patternProperties"]
)
@pytest.mark.parametrize("provider", ["hosted_vllm", "lm_studio", "openai"])
def test_unsupported_grammar_uses_existing_json_mode(keyword, provider):
    schema = {
        "type": "object",
        "properties": {"facts": {"type": "array", keyword: True}},
    }
    with patch(
        "eneo.completion_models.infrastructure.tenant_model_capabilities.supports_response_schema",
        return_value=True,
    ):
        assert (
            schema_response_format(
                litellm_model=f"{provider}/local-model",
                provider_type=provider,
                schema=schema,
                name="test_output",
            )
            is None
        )
    assert keyword in schema["properties"]["facts"]


@pytest.mark.parametrize("provider", ["hosted_vllm", "vllm"])
def test_vllm_schema_is_passed_through_litellm_without_mutating_contract(provider):
    from copy import deepcopy

    from litellm.llms.hosted_vllm.chat.transformation import HostedVLLMChatConfig

    # Property names are data, not schema keywords.
    schema = {
        "type": "object",
        "properties": {"uniqueItems": {"type": "string"}},
        "required": ["uniqueItems"],
        "additionalProperties": False,
    }
    original = deepcopy(schema)
    response_format = schema_response_format(
        litellm_model="hosted_vllm/local-model",
        provider_type=provider,
        schema=schema,
        name="test_output",
    )
    sent = HostedVLLMChatConfig().map_openai_params(
        non_default_params={"response_format": response_format},
        optional_params={},
        model="local-model",
        drop_params=True,
    )
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["schema"] == original
    sent["response_format"]["json_schema"]["schema"]["properties"].clear()
    assert schema == original


def test_native_schema_request_requires_support_for_other_providers():
    with patch(
        "eneo.completion_models.infrastructure.tenant_model_capabilities.supports_response_schema",
        return_value=False,
    ):
        assert (
            schema_response_format(
                litellm_model="custom/model",
                provider_type="openai",
                schema={"type": "object"},
                name="test_output",
            )
            is None
        )
