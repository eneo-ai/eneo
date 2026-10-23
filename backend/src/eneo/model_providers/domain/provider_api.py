"""Where a provider lists its models, and how to authenticate that request.

The model picker lists live models from these URLs. The connection check
calls the same kind of URL: listing models is the cheapest authenticated call
most provider APIs offer, and it generates (and bills) no tokens.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Default base URLs for providers that don't ask the user for one.
# Any provider configured with its own ``endpoint`` wins over the default.
DEFAULT_ENDPOINTS: dict[str, str] = {
    "openai": "https://api.openai.com",
    "anthropic": "https://api.anthropic.com",
}

# Model lists of hosted APIs that need no endpoint setting. Only the
# connection check calls these; the model picker keeps LiteLLM's catalog.
_HOSTED_MODEL_LISTS: dict[str, str] = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models",
    "mistral": "https://api.mistral.ai/v1/models",
    "cohere": "https://api.cohere.com/v1/models",
    "groq": "https://api.groq.com/openai/v1/models",
    "deepseek": "https://api.deepseek.com/models",
    "xai": "https://api.x.ai/v1/models",
    "together_ai": "https://api.together.xyz/v1/models",
    "fireworks_ai": "https://api.fireworks.ai/inference/v1/models",
}

# Azure lists models on its data plane. The API version is pinned to a GA
# version that has the route: the one an admin configures is for inference
# and need not serve it.
AZURE_MODELS_API_VERSION = "2024-10-21"

_KEY_REJECTED_STATUSES = frozenset({401, 403})


@dataclass(frozen=True)
class ProviderRequest:
    url: str
    headers: dict[str, str]
    # Statuses with which the provider refuses the key. Google answers an
    # invalid key with 400 INVALID_ARGUMENT rather than 401.
    key_rejected_statuses: frozenset[int] = _KEY_REJECTED_STATUSES


def auth_headers_for(provider_type: str, api_key: str) -> dict[str, str]:
    """Auth header set per provider. Bearer for everyone except Anthropic,
    which uses its own header pair."""
    if provider_type == "anthropic":
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {api_key}"}


def normalize_endpoint_base(base: str) -> str:
    """Strip a trailing slash and an optional ``/v1`` suffix so users can
    paste either ``https://api.example.com`` or ``https://api.example.com/v1``
    without us producing ``/v1/v1/models``."""
    s = base.rstrip("/")
    if s.endswith("/v1"):
        s = s[:-3].rstrip("/")
    return s


def configured_endpoint(config: Mapping[str, Any]) -> str:
    """The provider's own base URL from its config, or "" when it has none."""
    endpoint = config.get("endpoint")
    return endpoint.strip() if isinstance(endpoint, str) else ""


def models_list_request(
    provider_type: str, api_key: str, endpoint: str
) -> ProviderRequest | None:
    """The OpenAI-style ``GET /v1/models`` the model picker lists from.

    None when there is nothing to list from: Azure's model list covers every
    model in the region rather than the deployed ones, and other hosted APIs
    have no base URL without an ``endpoint``.
    """
    if provider_type == "azure":
        return None
    base = endpoint or DEFAULT_ENDPOINTS.get(provider_type)
    if not base:
        return None
    return ProviderRequest(
        url=f"{normalize_endpoint_base(base)}/v1/models",
        headers=auth_headers_for(provider_type, api_key),
    )


def connection_check_request(
    provider_type: str, api_key: str, endpoint: str
) -> ProviderRequest | None:
    """The cheap authenticated call that shows whether a provider answers
    and accepts its key, or None when there is no such call to make."""
    if provider_type == "azure":
        if not endpoint:
            return None
        return ProviderRequest(
            url=(
                f"{endpoint.rstrip('/')}/openai/models"
                f"?api-version={AZURE_MODELS_API_VERSION}"
            ),
            headers={"api-key": api_key},
        )
    listing = models_list_request(provider_type, api_key, endpoint)
    if listing is not None:
        return listing
    url = _HOSTED_MODEL_LISTS.get(provider_type)
    if url is None:
        return None
    if provider_type == "gemini":
        return ProviderRequest(
            url=url,
            headers={"x-goog-api-key": api_key},
            key_rejected_statuses=_KEY_REJECTED_STATUSES | {400},
        )
    return ProviderRequest(url=url, headers={"Authorization": f"Bearer {api_key}"})


def connection_check_supported(provider_type: str, endpoint: str) -> bool:
    return connection_check_request(provider_type, "", endpoint) is not None
