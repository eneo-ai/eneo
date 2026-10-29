"""The static rule for which provider types Eneo can use (#1258).

The admin wizard and ``POST /model-providers/`` both use this rule, so a
provider type that can never answer is neither offered nor stored.
"""

import socket
from typing import Any

import litellm
import pytest
from litellm.llms.openai_like.json_loader import JSONProviderRegistry

from eneo.model_providers.infrastructure.provider_type_support import (
    INTERACTIVE_SIGN_IN_PROVIDERS,
    ProviderTypeProblem,
    bucket_placements,
    is_supported_provider_type,
    provider_type_problem,
)
from eneo.tenants.provider_field_config import PROVIDER_FIELD_DEFINITIONS


@pytest.mark.parametrize(
    "provider_type",
    [
        "openai",
        "azure",
        "anthropic",
        "mistral",
        "gemini",
        "bedrock",
        "vertex_ai",
        "hosted_vllm",
        "vllm",
        "OpenAI",
        *PROVIDER_FIELD_DEFINITIONS,
    ],
)
def test_routable_types_are_supported(provider_type: str) -> None:
    assert provider_type_problem(provider_type) is None


@pytest.mark.parametrize(
    ("provider_type", "problem"),
    [
        ("bedrock_converse", ProviderTypeProblem.UNKNOWN_ROUTE),
        ("vertex_ai-anthropic_models", ProviderTypeProblem.UNKNOWN_ROUTE),
        ("fireworks_ai-embedding-models", ProviderTypeProblem.UNKNOWN_ROUTE),
        ("not-a-provider", ProviderTypeProblem.UNKNOWN_ROUTE),
        ("", ProviderTypeProblem.UNKNOWN_ROUTE),
        ("github_copilot", ProviderTypeProblem.INTERACTIVE_SIGN_IN),
        ("ChatGPT", ProviderTypeProblem.INTERACTIVE_SIGN_IN),
    ],
)
def test_unusable_types_name_their_reason(
    provider_type: str, problem: ProviderTypeProblem
) -> None:
    assert provider_type_problem(provider_type) is problem


def test_a_type_only_the_json_registry_knows_is_supported() -> None:
    json_only = [
        provider
        for provider in JSONProviderRegistry.list_providers()
        if provider not in litellm.provider_list
    ]

    assert json_only, "LiteLLM no longer has JSON-only providers; drop this test"
    assert all(is_supported_provider_type(provider) for provider in json_only)


def test_the_interactive_exclusions_are_still_needed() -> None:
    """When LiteLLM stops routing one of these, remove it from the list."""
    assert INTERACTIVE_SIGN_IN_PROVIDERS <= set(litellm.provider_list)


def test_bucket_rows_go_to_their_one_supported_provider() -> None:
    placements = bucket_placements(
        {
            "bedrock": ["converse-only", "shared"],
            "anthropic": ["shared"],
            "bedrock_converse": ["bucket-only"],
            "github_copilot": ["copilot-only"],
            "vllm": ["vllm-only"],
        }
    )

    assert placements == {"converse-only": "bedrock", "vllm-only": "hosted_vllm"}


def test_the_rule_agrees_with_litellms_parser_on_the_bundled_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a LiteLLM upgrade that renames, adds or drops provider types.

    ``get_llm_provider`` is the source of truth but must never run for the
    interactive providers: it would start their OAuth device flow. The network
    is blocked in case another provider starts one too.
    """

    def _no_network(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("network access is blocked in this test")

    monkeypatch.setattr(socket.socket, "connect", _no_network)
    provider_types = {
        info["litellm_provider"]
        for info in litellm.model_cost.values()
        if info.get("litellm_provider")
    } - INTERACTIVE_SIGN_IN_PROVIDERS
    assert provider_types

    def _parser_accepts(provider_type: str) -> bool:
        try:
            litellm.get_llm_provider(f"{provider_type}/model")
        except Exception:
            return False
        return True

    disagreements = {
        provider_type
        for provider_type in provider_types
        if is_supported_provider_type(provider_type) != _parser_accepts(provider_type)
    }
    assert not disagreements
