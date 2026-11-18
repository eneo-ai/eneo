"""Which provider types Eneo can use, decided statically from LiteLLM.

Never call ``litellm.get_llm_provider`` to answer this: for ``github_copilot``
and ``chatgpt`` it starts an OAuth device flow that waits for minutes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum

import litellm

# Imported without a fallback on purpose: if a LiteLLM upgrade moves this
# internal module, startup and CI must fail rather than silently reject every
# provider that only this registry knows (aihubmix, crusoe, gmi, ...).
from litellm.llms.openai_like.json_loader import (  # pyright: ignore[reportMissingTypeStubs]  # internal LiteLLM module without stubs
    JSONProviderRegistry,
)

from eneo.tenants.provider_field_config import get_canonical_provider_type

# LiteLLM routes these, but only after a sign-in in a browser that a server
# process cannot complete.
INTERACTIVE_SIGN_IN_PROVIDERS = frozenset({"github_copilot", "chatgpt"})


class ProviderTypeProblem(Enum):
    UNKNOWN_ROUTE = "unknown_route"
    INTERACTIVE_SIGN_IN = "interactive_sign_in"


def provider_type_problem(provider_type: str) -> ProviderTypeProblem | None:
    """Why Eneo cannot use ``provider_type``, or None when it can.

    Aliases such as ``vllm`` are resolved to their canonical type first.
    """
    canonical = get_canonical_provider_type(provider_type)
    if canonical in INTERACTIVE_SIGN_IN_PROVIDERS:
        return ProviderTypeProblem.INTERACTIVE_SIGN_IN
    if canonical in litellm.provider_list or JSONProviderRegistry.exists(canonical):
        return None
    return ProviderTypeProblem.UNKNOWN_ROUTE


def is_supported_provider_type(provider_type: str) -> bool:
    return provider_type_problem(provider_type) is None


def bucket_placements(
    models_by_provider: Mapping[str, Iterable[str]],
) -> dict[str, str]:
    """Map model keys to the one supported provider LiteLLM lists them under.

    The cost map files some rows under pricing buckets rather than provider
    types (``bedrock_converse``, ``vertex_ai-language-models``);
    ``litellm.models_by_provider`` is LiteLLM's own mapping of those rows to
    the provider that routes them. A key listed under more than one supported
    provider is left out, because its route would be a guess.
    """
    homes: dict[str, set[str]] = {}
    for provider, model_keys in models_by_provider.items():
        if not is_supported_provider_type(provider):
            continue
        canonical = get_canonical_provider_type(provider)
        for model_key in model_keys:
            homes.setdefault(model_key, set()).add(canonical)
    return {
        model_key: next(iter(providers))
        for model_key, providers in homes.items()
        if len(providers) == 1
    }
