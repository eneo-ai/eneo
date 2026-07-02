from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import cast

import litellm

from eneo.main.logging import get_logger

logger = get_logger(__name__)


class StructuredOutputMode(str, Enum):
    STRICT_JSON_SCHEMA = "strict_json_schema"
    JSON_OBJECT = "json_object"
    PROMPT_WITH_PYDANTIC_VALIDATION = "prompt_with_pydantic_validation"


class StructuredOutputDecisionSource(str, Enum):
    LITELLM_RESPONSE_SCHEMA = "litellm_response_schema"
    LITELLM_RESPONSE_FORMAT = "litellm_response_format"
    NO_PROVIDER_SUPPORT = "no_provider_support"


@dataclass(frozen=True, slots=True)
class StructuredOutputCapabilityDecision:
    mode: StructuredOutputMode
    source: StructuredOutputDecisionSource
    supports_response_schema: bool | None
    supports_response_format: bool | None

    def __post_init__(self) -> None:
        if self.source is StructuredOutputDecisionSource.LITELLM_RESPONSE_SCHEMA:
            if (
                self.mode is not StructuredOutputMode.STRICT_JSON_SCHEMA
                or self.supports_response_schema is not True
            ):
                raise ValueError("response-schema decisions must use strict JSON mode")
        elif self.source is StructuredOutputDecisionSource.LITELLM_RESPONSE_FORMAT:
            if (
                self.mode is not StructuredOutputMode.JSON_OBJECT
                or self.supports_response_schema is True
                or self.supports_response_format is not True
            ):
                raise ValueError("response-format decisions must use JSON object mode")
        elif self.source is StructuredOutputDecisionSource.NO_PROVIDER_SUPPORT:
            if (
                self.mode is not StructuredOutputMode.PROMPT_WITH_PYDANTIC_VALIDATION
                or self.supports_response_schema is True
                or self.supports_response_format is True
            ):
                raise ValueError("unsupported decisions must use prompt validation")


def resolve_structured_output_capability(
    *,
    litellm_model: str,
    provider_type: str,
) -> StructuredOutputCapabilityDecision:
    supports_schema = _safe_supports_response_schema(
        litellm_model=litellm_model,
        provider_type=provider_type,
    )
    supports_format = _safe_supports_response_format(
        litellm_model=litellm_model,
        provider_type=provider_type,
    )

    if supports_schema is True:
        return StructuredOutputCapabilityDecision(
            mode=StructuredOutputMode.STRICT_JSON_SCHEMA,
            source=StructuredOutputDecisionSource.LITELLM_RESPONSE_SCHEMA,
            supports_response_schema=supports_schema,
            supports_response_format=supports_format,
        )
    if supports_format is True:
        return StructuredOutputCapabilityDecision(
            mode=StructuredOutputMode.JSON_OBJECT,
            source=StructuredOutputDecisionSource.LITELLM_RESPONSE_FORMAT,
            supports_response_schema=supports_schema,
            supports_response_format=supports_format,
        )
    return unsupported_structured_output_decision(
        supports_response_schema=supports_schema,
        supports_response_format=supports_format,
    )


def unsupported_structured_output_decision(
    *,
    supports_response_schema: bool | None = None,
    supports_response_format: bool | None = None,
) -> StructuredOutputCapabilityDecision:
    return StructuredOutputCapabilityDecision(
        mode=StructuredOutputMode.PROMPT_WITH_PYDANTIC_VALIDATION,
        source=StructuredOutputDecisionSource.NO_PROVIDER_SUPPORT,
        supports_response_schema=supports_response_schema,
        supports_response_format=supports_response_format,
    )


def get_supported_openai_params(
    *,
    model: str,
    custom_llm_provider: str | None = None,
) -> tuple[str, ...] | None:
    params = cast(
        list[str] | None,
        getattr(litellm, "get_supported_openai_params")(
            model=model,
            custom_llm_provider=custom_llm_provider,
        ),
    )
    return tuple(params) if params is not None else None


def supports_response_schema(
    *,
    model: str,
    custom_llm_provider: str | None = None,
) -> bool:
    return bool(
        getattr(litellm, "supports_response_schema")(
            model=model,
            custom_llm_provider=custom_llm_provider,
        )
    )


def _safe_supports_response_schema(
    *,
    litellm_model: str,
    provider_type: str,
) -> bool | None:
    try:
        return supports_response_schema(
            model=litellm_model,
            custom_llm_provider=provider_type,
        )
    except Exception:
        logger.warning(
            "LiteLLM response schema capability check failed",
            exc_info=True,
            extra={
                "litellm_model": litellm_model,
                "provider_type": provider_type,
            },
        )
        return None


def _safe_supports_response_format(
    *,
    litellm_model: str,
    provider_type: str,
) -> bool | None:
    try:
        supported_params = get_supported_openai_params(
            model=litellm_model,
            custom_llm_provider=provider_type,
        )
    except Exception:
        logger.warning(
            "LiteLLM response format capability check failed",
            exc_info=True,
            extra={
                "litellm_model": litellm_model,
                "provider_type": provider_type,
            },
        )
        return None
    if supported_params is None:
        return None
    return "response_format" in supported_params


__all__ = [
    "StructuredOutputCapabilityDecision",
    "StructuredOutputDecisionSource",
    "StructuredOutputMode",
    "get_supported_openai_params",
    "resolve_structured_output_capability",
    "supports_response_schema",
    "unsupported_structured_output_decision",
]
