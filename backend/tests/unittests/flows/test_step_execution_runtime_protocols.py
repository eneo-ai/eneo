"""Tests for the typed Protocols introduced for step_execution_runtime deps.

These tests pin the Protocol contract: a fake assistant exposing exactly
the surface the runtime requires must be accepted by the helper functions
and by `StepExecutionRuntimeDeps`. They also lock the empty-string fallback
in `json_mode_cache_key` / `_resolve_litellm_model_name` (a model with
empty identifiers must surface as the "unknown" sentinel so the JSON-mode
capability cache stays consistent across lookups for the same model).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from intric.ai_models.completion_models.completion_model import ModelKwargs

if TYPE_CHECKING:
    from intric.collections.domain.collection import Collection
    from intric.integration.domain.entities.integration_knowledge import (
        IntegrationKnowledge,
    )
    from intric.websites.domain.website import Website


@dataclass
class _FakeCompletionModel:
    """Minimal fake satisfying RuntimeCompletionModelProtocol structurally."""

    id: UUID
    name: str
    provider_type: str | None
    litellm_model_name: str | None


@dataclass
class _FakeAssistant:
    """Minimal fake satisfying RuntimeAssistantProtocol structurally.

    Only declares the surface the runtime inspects synchronously; async
    `get_response` is not exercised by these unit tests. List properties
    are typed against the same domain types the Protocol declares so the
    fake honors the contract instead of evading it via list[Any].
    """

    completion_model: _FakeCompletionModel | None
    completion_model_kwargs: ModelKwargs
    _collections: list[Collection] = field(default_factory=list)
    _websites: list[Website] = field(default_factory=list)
    _integration_knowledge_list: list[IntegrationKnowledge] = field(
        default_factory=list
    )

    @property
    def collections(self) -> list[Collection]:
        return self._collections

    @property
    def websites(self) -> list[Website]:
        return self._websites

    @property
    def integration_knowledge_list(self) -> list[IntegrationKnowledge]:
        return self._integration_knowledge_list

    def has_knowledge(self) -> bool:
        return False

    def get_prompt_text(self) -> str:
        return "system prompt"

    async def get_response(self, **_kwargs: Any) -> Any:
        raise NotImplementedError


def _build_assistant(
    *,
    model_id: UUID | None = None,
    model_name: str = "gpt-test",
    provider: str | None = "openai",
    litellm_name: str | None = "openai/gpt-test",
    kwargs: ModelKwargs | None = None,
) -> _FakeAssistant:
    return _FakeAssistant(
        completion_model=_FakeCompletionModel(
            id=model_id or uuid4(),
            name=model_name,
            provider_type=provider,
            litellm_model_name=litellm_name,
        ),
        completion_model_kwargs=kwargs or ModelKwargs(temperature=0.5, top_p=0.9),
    )


def test_protocols_are_exported() -> None:
    from intric.flows.runtime.protocols import (
        RuntimeAssistantProtocol,
        RuntimeCompletionModelProtocol,
    )

    assert RuntimeAssistantProtocol is not None
    assert RuntimeCompletionModelProtocol is not None


def test_effective_model_parameters_accepts_protocol_implementer() -> None:
    from intric.flows.runtime.step_execution_runtime import effective_model_parameters

    params = effective_model_parameters(_build_assistant())
    assert params["model_name"] == "gpt-test"
    assert params["provider"] == "openai"
    assert params["temperature"] == 0.5
    assert params["parameter_semantics"]["temperature"] == {"mode": "configured"}
    assert params["parameter_semantics"]["reasoning_effort"] == {
        "mode": "model_default"
    }


def test_json_mode_cache_key_handles_empty_model_name() -> None:
    """An empty model name must surface as the 'unknown' sentinel.

    The runtime caches JSON-mode capability per model identifier triple.
    An empty name (uncommon but possible during fixture/migration edge
    cases) must not produce a divergent cache key, otherwise capability
    learned for the same model is silently invalidated.
    """
    from intric.flows.runtime.step_execution_runtime import json_mode_cache_key

    assistant = _build_assistant(model_name="")
    parts = json_mode_cache_key(assistant).split(":")
    assert parts[1] == "unknown"


def test_json_mode_cache_key_handles_missing_completion_model() -> None:
    from intric.flows.runtime.step_execution_runtime import json_mode_cache_key

    assistant = _FakeAssistant(
        completion_model=None,
        completion_model_kwargs=ModelKwargs(),
    )
    assert json_mode_cache_key(assistant) == "unknown:unknown:none"


def test_requested_model_name_returns_none_for_empty_name() -> None:
    """Empty string name must collapse to None for downstream callers."""
    from intric.flows.runtime.step_execution_runtime import requested_model_name

    assert requested_model_name(_build_assistant(model_name="")) is None


def test_requested_model_name_returns_name_when_present() -> None:
    from intric.flows.runtime.step_execution_runtime import requested_model_name

    assert requested_model_name(_build_assistant(model_name="gpt-4o")) == "gpt-4o"


def test_requested_model_name_returns_none_without_completion_model() -> None:
    from intric.flows.runtime.step_execution_runtime import requested_model_name

    assistant = _FakeAssistant(
        completion_model=None,
        completion_model_kwargs=ModelKwargs(),
    )
    assert requested_model_name(assistant) is None


def test_resolve_litellm_model_name_prefers_explicit() -> None:
    from intric.flows.runtime.step_execution_runtime import (
        _resolve_litellm_model_name,
    )

    assistant = _build_assistant(litellm_name="azure/gpt-4o")
    assert _resolve_litellm_model_name(assistant) == "azure/gpt-4o"


def test_resolve_litellm_model_name_falls_back_to_provider_and_name() -> None:
    from intric.flows.runtime.step_execution_runtime import (
        _resolve_litellm_model_name,
    )

    assistant = _build_assistant(
        litellm_name=None, provider="openai", model_name="gpt-test"
    )
    assert _resolve_litellm_model_name(assistant) == "openai/gpt-test"


def test_resolve_litellm_model_name_returns_none_without_completion_model() -> None:
    from intric.flows.runtime.step_execution_runtime import (
        _resolve_litellm_model_name,
    )

    assistant = _FakeAssistant(
        completion_model=None,
        completion_model_kwargs=ModelKwargs(),
    )
    assert _resolve_litellm_model_name(assistant) is None
