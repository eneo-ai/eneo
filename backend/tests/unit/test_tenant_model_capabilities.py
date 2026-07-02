from unittest.mock import patch

import pytest

from eneo.completion_models.infrastructure.tenant_model_capabilities import (
    StructuredOutputCapabilityDecision,
    StructuredOutputDecisionSource,
    StructuredOutputMode,
    resolve_structured_output_capability,
    unsupported_structured_output_decision,
)


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
