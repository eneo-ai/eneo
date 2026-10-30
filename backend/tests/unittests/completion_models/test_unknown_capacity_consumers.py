from types import SimpleNamespace

import pytest

from eneo.completion_models.domain.model_capacity import (
    ModelCapacity,
    UnknownModelCapacityError,
)
from eneo.completion_models.domain.skill_activation import SkillActivationRuntime
from eneo.completion_models.domain.skill_context import skill_context_token_allowance
from eneo.completion_models.infrastructure.adapters.tenant_model_adapter import (
    TenantModelAdapter,
)
from eneo.files.attachment_budget import attachment_token_ceiling
from tests.unittests.completion_models.test_model_token_limits import _load_model


def _adapter(output=None, input_tokens=None):
    adapter = object.__new__(TenantModelAdapter)
    adapter.model = _load_model(output, input_tokens=input_tokens)
    adapter.litellm_model = "openai/custom"
    adapter.provider_type = "openai"
    adapter.credential_resolver = SimpleNamespace(
        provider_type="openai",
        get_api_key=lambda **kwargs: "key",
        get_credential_field=lambda **kwargs: None,
    )
    return adapter


@pytest.mark.parametrize(
    "consumer",
    [
        lambda: attachment_token_ceiling(None),
        lambda: skill_context_token_allowance(
            max_input_tokens=None, context_share_percent=10
        ),
        lambda: _adapter().get_token_limit_of_model(),
        lambda: SkillActivationRuntime.create(
            base_instructions="",
            skills=(),
            blocked_keys=frozenset(),
            selective_activation_enabled=False,
            max_activations_per_turn=1,
            context_share_percent=10,
            model_route="openai/custom",
            max_input_tokens=None,
            supports_tool_calling=False,
        ),
    ],
)
def test_input_decisions_refuse_unknown_with_dimension(consumer):
    with pytest.raises(UnknownModelCapacityError) as error:
        consumer()
    assert error.value.missing_dimensions == ("max_input_tokens",)


@pytest.mark.parametrize("method", ["get_response", "prepare_streaming"])
@pytest.mark.parametrize(
    "kwargs", [None, {}, {"max_tokens": 50}, {"max_completion_tokens": 50}]
)
@pytest.mark.usefixtures("declared_capabilities")
async def test_dispatch_refuses_missing_output_even_with_explicit_cap(
    method, kwargs, monkeypatch
):
    from unittest.mock import AsyncMock, Mock

    from eneo.completion_models.infrastructure.adapters.base_adapter import (
        ProviderInput,
    )

    adapter = _adapter(input_tokens=100)
    adapter.prepare_provider_input = Mock(
        return_value=ProviderInput(messages=[], tools=[], built_in_tools=[])
    )
    observer = SimpleNamespace(started=AsyncMock())
    transport = AsyncMock()
    monkeypatch.setattr(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        transport,
    )
    with pytest.raises(UnknownModelCapacityError) as error:
        await getattr(adapter, method)(
            context=SimpleNamespace(),
            model_kwargs=kwargs,
            **(
                {"provider_call_observer": observer} if method == "get_response" else {}
            ),
        )
    assert error.value.missing_dimensions == ("max_output_tokens",)
    transport.assert_not_awaited()
    observer.started.assert_not_awaited()


def test_known_dimension_does_not_require_other_dimensions():
    assert _adapter(input_tokens=100).get_token_limit_of_model() == 99
    assert (
        skill_context_token_allowance(max_input_tokens=100, context_share_percent=10)
        == 10
    )


@pytest.mark.parametrize("dimension", ["input", "output"])
def test_capacity_exposes_required_dimension(dimension):
    capacity = ModelCapacity(None, None)
    with pytest.raises(UnknownModelCapacityError) as error:
        getattr(capacity, f"require_{dimension}_tokens")()
    assert error.value.missing_dimensions == (f"max_{dimension}_tokens",)
    assert getattr(ModelCapacity(100, 80), f"require_{dimension}_tokens")() == (
        100 if dimension == "input" else 80
    )


def test_assistant_model_projection_preserves_unknown_limits():
    from eneo.assistants.api.assistant_models import ModelInfo

    public = ModelInfo(name="Unknown", max_input_tokens=None, max_output_tokens=None)
    assert public.token_limit is None
    assert public.model_dump()["max_output_tokens"] is None


def test_resolving_provider_credentials_does_not_make_a_capacity_decision():
    route, kwargs = _adapter().resolve_litellm_params()
    assert route == "openai/custom"
    assert kwargs["api_key"] == "key"


@pytest.mark.parametrize("method", ["get_response", "prepare_streaming"])
async def test_provider_refuses_unknown_input_before_transport(method, monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from eneo.completion_models.infrastructure.adapters.base_adapter import (
        ProviderInput,
    )

    adapter = _adapter(output=80)
    adapter.prepare_provider_input = MagicMock(
        return_value=ProviderInput(messages=[], tools=[], built_in_tools=[])
    )
    adapter._get_dropped_params = MagicMock(return_value=set())
    adapter._get_effective_params = MagicMock(return_value={})
    adapter._observed_provider_call = AsyncMock(
        side_effect=AssertionError("transport reached")
    )
    monkeypatch.setattr(
        "eneo.completion_models.infrastructure.adapters.tenant_model_adapter._acompletion_call",
        adapter._observed_provider_call,
    )
    with pytest.raises(UnknownModelCapacityError) as error:
        await getattr(adapter, method)(
            context=MagicMock(), model_kwargs={"max_tokens": 40}
        )
    assert error.value.missing_dimensions == ("max_input_tokens",)
    adapter._observed_provider_call.assert_not_awaited()


@pytest.fixture
def declared_capabilities(monkeypatch):
    monkeypatch.setattr(
        "litellm.get_supported_openai_params",
        lambda **kwargs: ["max_tokens", "max_completion_tokens"],
    )
