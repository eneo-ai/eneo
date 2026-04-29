from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.ai_models.completion_models.completion_model import (
    CompletionModel,
    CompletionModelCreate,
    CompletionModelPublic,
    CompletionModelSecurityStatus,
    CompletionModelSparse,
    CompletionModelUpdate,
    ModelKwargs,
)
from intric.completion_models.domain.completion_model import (
    CompletionModel as CompletionModelDomain,
)
from intric.completion_models.presentation.completion_model_assembler import (
    CompletionModelAssembler,
)


def _completion_model_sparse(**overrides: object) -> CompletionModelSparse:
    now = datetime.now(timezone.utc)
    values = {
        "id": uuid4(),
        "created_at": now,
        "updated_at": now,
        "name": "gpt-4o",
        "nickname": "GPT-4o",
        "family": "openai",
        "max_input_tokens": 128000,
        "max_output_tokens": 4096,
        "is_deprecated": False,
        "vision": False,
        "reasoning": False,
        "supports_tool_calling": True,
    }
    values.update(overrides)
    return CompletionModelSparse(**values)


def test_completion_models_describe_user_configurable_kwargs():
    model = _completion_model_sparse()

    assert model.supported_model_kwargs.temperature.supported is True
    assert model.supported_model_kwargs.temperature.minimum == 0
    assert model.supported_model_kwargs.temperature.maximum == 2
    assert model.supported_model_kwargs.reasoning_effort.supported is False


def test_tenant_models_expose_advanced_sampling_kwargs():
    model = _completion_model_sparse(provider_type="vllm")

    assert model.supported_model_kwargs.temperature.supported is True
    assert model.supported_model_kwargs.top_p.supported is True
    assert model.supported_model_kwargs.presence_penalty.supported is True
    assert model.supported_model_kwargs.frequency_penalty.supported is True
    assert model.supported_model_kwargs.top_k.supported is True


def test_capability_override_wins_over_model_name_and_reasoning_flag():
    model = _completion_model_sparse(
        name="gpt-5.1",
        reasoning=True,
        model_kwargs_capabilities={
            "temperature": {
                "supported": True,
                "control": "slider",
                "minimum": 0,
                "maximum": 2,
                "step": 0.01,
            }
        },
    )

    assert model.supported_model_kwargs.temperature.supported is True
    assert model.supported_model_kwargs.reasoning_effort.supported is False
    assert model.supported_model_kwargs.verbosity.supported is False


def test_reasoning_flag_disables_stored_reasoning_effort_capability():
    model = _completion_model_sparse(
        name="gpt-5.1",
        reasoning=False,
        model_kwargs_capabilities={
            "reasoning_effort": {
                "supported": True,
                "control": "select",
                "options": ["low", "medium", "high"],
            },
            "verbosity": {
                "supported": True,
                "control": "select",
                "options": ["low", "medium", "high"],
            },
        },
    )

    assert model.supported_model_kwargs.reasoning_effort.supported is False
    assert model.supported_model_kwargs.verbosity.supported is True


def test_filter_unsupported_strips_disabled_kwargs():
    model = _completion_model_sparse(name="gpt-5.1", reasoning=False)
    kwargs = ModelKwargs(temperature=0.4, reasoning_effort="high", verbosity="low")

    filtered = kwargs.filter_unsupported(model.supported_model_kwargs)

    assert filtered.temperature == 0.4
    assert filtered.reasoning_effort is None
    assert filtered.verbosity is None


def test_filter_unsupported_returns_self_when_all_supported():
    model = _completion_model_sparse(name="gpt-5.1", reasoning=True)
    kwargs = ModelKwargs(reasoning_effort="medium")

    filtered = kwargs.filter_unsupported(model.supported_model_kwargs)

    assert filtered is kwargs


def test_filter_unsupported_preserves_response_format():
    model = _completion_model_sparse(reasoning=False)
    kwargs = ModelKwargs(response_format={"type": "json_object"})

    filtered = kwargs.filter_unsupported(model.supported_model_kwargs)

    assert filtered.response_format == {"type": "json_object"}


def test_reasoning_fallback_is_name_agnostic():
    model = _completion_model_sparse(name="gpt-5.1", reasoning=True)

    assert model.supported_model_kwargs.temperature.supported is False
    assert model.supported_model_kwargs.reasoning_effort.supported is True
    assert model.supported_model_kwargs.reasoning_effort.options == [
        "low",
        "medium",
        "high",
    ]
    assert model.supported_model_kwargs.verbosity.supported is False


def test_explicit_reasoning_capabilities_expose_verbosity_and_none_option():
    model = _completion_model_sparse(
        name="reasoning-model",
        reasoning=True,
        model_kwargs_capabilities={
            "reasoning_effort": {
                "supported": True,
                "control": "select",
                "options": ["none", "low", "medium", "high"],
            },
            "verbosity": {
                "supported": True,
                "control": "select",
                "options": ["low", "medium", "high"],
            },
        },
    )

    assert model.supported_model_kwargs.reasoning_effort.options == [
        "none",
        "low",
        "medium",
        "high",
    ]
    assert model.supported_model_kwargs.verbosity.supported is True
    assert model.supported_model_kwargs.verbosity.options == ["low", "medium", "high"]


def test_invalid_api_capability_metadata_is_rejected():
    with pytest.raises(ValidationError):
        _completion_model_sparse(
            model_kwargs_capabilities={"temperature": {"control": "dial"}}
        )


def test_invalid_stored_capability_metadata_falls_back(
    caplog: pytest.LogCaptureFixture,
):
    now = datetime.now(timezone.utc)
    source_model = SimpleNamespace(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="stored-model",
        nickname="Stored Model",
        family=None,
        max_input_tokens=128000,
        max_output_tokens=4096,
        is_deprecated=False,
        nr_billion_parameters=None,
        hf_link=None,
        stability=None,
        hosting=None,
        open_source=None,
        description=None,
        deployment_name=None,
        org=None,
        vision=False,
        reasoning=False,
        supports_tool_calling=True,
        base_url=None,
        litellm_model_name=None,
        model_kwargs_capabilities={"temperature": {"control": "dial"}},
        provider_type=None,
    )

    with caplog.at_level(
        logging.WARNING,
        logger="intric.completion_models.domain.model_kwargs_capabilities",
    ):
        model = CompletionModelSparse.model_validate(source_model)

    assert model.model_kwargs_capabilities is None
    assert model.supported_model_kwargs.temperature.supported is True
    assert "Invalid completion model kwargs capabilities" in caplog.text


def test_domain_model_normalizes_invalid_capabilities_before_public_assembly():
    now = datetime.now(timezone.utc)
    db_model = SimpleNamespace(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="stored-model",
        nickname="Stored Model",
        family=None,
        max_input_tokens=128000,
        max_output_tokens=4096,
        vision=False,
        hosting=None,
        org=None,
        stability=None,
        open_source=None,
        description=None,
        nr_billion_parameters=None,
        hf_link=None,
        is_deprecated=False,
        deployment_name=None,
        is_enabled=True,
        is_default=False,
        reasoning=False,
        supports_tool_calling=True,
        base_url=None,
        litellm_model_name=None,
        model_kwargs_capabilities={"temperature": {"control": "dial"}},
        security_classification=None,
        tenant_id=uuid4(),
        provider_id=uuid4(),
    )
    domain_model = CompletionModelDomain.create_from_db(
        db_model,
        user=SimpleNamespace(tenant=None),
        provider_name=None,
        provider_type=None,
    )

    public_model = CompletionModelAssembler().from_completion_model_to_model(
        domain_model
    )

    assert domain_model.model_kwargs_capabilities is None
    assert public_model.supported_model_kwargs.temperature.supported is True


def test_completion_model_input_schemas_accept_explicit_capability_metadata():
    for model_type in [CompletionModelCreate, CompletionModelUpdate]:
        properties = model_type.model_json_schema(mode="validation")["properties"]

        assert "model_kwargs_capabilities" in properties
        assert "supported_model_kwargs" not in properties


def test_completion_model_response_schemas_expose_resolved_capabilities():
    for model_type in [
        CompletionModelPublic,
        CompletionModelSecurityStatus,
        CompletionModelSparse,
    ]:
        properties = model_type.model_json_schema(mode="serialization")["properties"]

        assert "model_kwargs_capabilities" in properties
        assert "supported_model_kwargs" in properties


def test_sparse_completion_model_preserves_provider_capabilities():
    now = datetime.now(timezone.utc)
    source_model = SimpleNamespace(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="meta-llama/Llama-3.1-70B-Instruct",
        nickname="Llama 3.1",
        family=None,
        max_input_tokens=128000,
        max_output_tokens=4096,
        is_deprecated=False,
        nr_billion_parameters=70,
        hf_link=None,
        stability=None,
        hosting="self-hosted",
        open_source=True,
        description=None,
        deployment_name=None,
        org=None,
        vision=False,
        reasoning=False,
        supports_tool_calling=True,
        base_url="https://vllm.example.local/v1",
        litellm_model_name="vllm/meta-llama/Llama-3.1-70B-Instruct",
        model_kwargs_capabilities=None,
        provider_type="vllm",
    )

    sparse_model = CompletionModelAssembler.from_completion_model_to_sparse(
        source_model
    )

    assert sparse_model.provider_type == "vllm"
    assert sparse_model.litellm_model_name == "vllm/meta-llama/Llama-3.1-70B-Instruct"
    assert sparse_model.supported_model_kwargs.top_p.supported is True
    assert sparse_model.supported_model_kwargs.top_k.supported is True


def test_sparse_projection_preserves_admin_completion_model_provider_type():
    now = datetime.now(timezone.utc)
    admin_model = CompletionModel(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="meta-llama/Llama-3.1-70B-Instruct",
        nickname="Llama 3.1",
        family=None,
        max_input_tokens=128000,
        max_output_tokens=4096,
        is_deprecated=False,
        nr_billion_parameters=70,
        hf_link=None,
        stability=None,
        hosting="self-hosted",
        open_source=True,
        description=None,
        deployment_name=None,
        org=None,
        vision=False,
        reasoning=False,
        supports_tool_calling=True,
        base_url=None,
        litellm_model_name=None,
        model_kwargs_capabilities=None,
        provider_type="vllm",
    )

    sparse_model = CompletionModelSparse.model_validate(admin_model)

    assert sparse_model.provider_type == "vllm"
    assert sparse_model.supported_model_kwargs.top_p.supported is True
    assert sparse_model.supported_model_kwargs.top_k.supported is True


def test_public_completion_model_preserves_litellm_capabilities():
    now = datetime.now(timezone.utc)
    source_model = SimpleNamespace(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="mistral-large-latest",
        nickname="Mistral Large",
        family=None,
        max_input_tokens=128000,
        max_output_tokens=4096,
        is_deprecated=False,
        nr_billion_parameters=None,
        hf_link=None,
        stability=None,
        hosting=None,
        open_source=None,
        description=None,
        deployment_name=None,
        org=None,
        vision=False,
        reasoning=True,
        supports_tool_calling=True,
        base_url=None,
        litellm_model_name="mistral/mistral-large-latest",
        model_kwargs_capabilities={
            "reasoning_effort": {
                "supported": True,
                "control": "select",
                "options": ["low", "medium", "high"],
            }
        },
        is_org_enabled=True,
        is_org_default=False,
        can_access=True,
        is_locked=False,
        lock_reason=None,
        security_classification=None,
        tenant_id=uuid4(),
        provider_id=uuid4(),
        provider_name="Mistral",
        provider_type="mistral",
    )

    public_model = CompletionModelAssembler().from_completion_model_to_model(
        source_model
    )

    assert public_model.litellm_model_name == "mistral/mistral-large-latest"
    assert public_model.provider_type == "mistral"
    assert public_model.supported_model_kwargs.reasoning_effort.supported is True
    assert public_model.supported_model_kwargs.top_p.supported is False
