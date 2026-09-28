from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.ai_models.completion_models.completion_model import (
    CompletionModel,
    CompletionModelCreate,
    CompletionModelPublic,
    CompletionModelSecurityStatus,
    CompletionModelSparse,
    CompletionModelUpdate,
    ModelKwargs,
)
from eneo.completion_models.domain import model_kwargs_capabilities
from eneo.completion_models.domain.completion_model import (
    CompletionModel as CompletionModelDomain,
)
from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
    reasoning_effort_options_from_model_info,
    snapshot_supported_model_kwargs,
)
from eneo.completion_models.presentation.completion_model_assembler import (
    CompletionModelAssembler,
)
from eneo.tenants.tenant import TenantInDB


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


def test_missing_capability_snapshot_omits_optional_kwargs():
    model = _completion_model_sparse()

    assert model.supported_model_kwargs.temperature.supported is False
    assert model.supported_model_kwargs.reasoning_effort.supported is False


def test_provider_type_does_not_widen_missing_capability_snapshot():
    model = _completion_model_sparse(provider_type="vllm")

    assert model.supported_model_kwargs == SupportedModelKwargs()


def test_explicit_capability_evidence_round_trips_without_public_marker():
    explicit = SupportedModelKwargs(
        temperature=ModelKwargCapability(
            supported=True,
            control="slider",
            minimum=1,
            maximum=1,
            step=1,
        )
    )

    persisted = model_kwargs_capabilities.persist_explicit_model_kwargs_capabilities(
        explicit
    )
    resolved = model_kwargs_capabilities.resolve_supported_model_kwargs(
        model_kwargs_capabilities=persisted,
        reasoning=True,
    )
    public_projection = SupportedModelKwargs.model_validate(persisted)

    assert resolved == explicit
    assert public_projection == explicit
    assert "_evidence" not in public_projection.model_dump()


# The catalogue backfill develop stores, without the evidence tag this branch
# added (the migration that tagged it was squashed away).
_UNTAGGED_DEVELOP_SNAPSHOT: dict[str, object] = {
    "temperature": {"supported": False},
    "top_p": {"supported": True, "control": "slider", "minimum": 0, "maximum": 1},
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
    "presence_penalty": {"supported": False},
    "frequency_penalty": {"supported": False},
    "top_k": {"supported": False},
}


def _stored_row(capabilities: object, *, reasoning: bool = True) -> SimpleNamespace:
    """A completion model row as the ORM hands it to the API models."""
    return SimpleNamespace(
        **_completion_model_sparse(reasoning=reasoning).model_dump(
            exclude={
                "supported_model_kwargs",
                "token_limit",
                "model_kwargs_capabilities",
            }
        ),
        model_kwargs_capabilities=capabilities,
    )


def test_untagged_persisted_capabilities_are_read_as_legacy_discovery(
    caplog: pytest.LogCaptureFixture,
):
    logger_name = "eneo.completion_models.domain.model_kwargs_capabilities"
    logger = logging.getLogger(logger_name)
    was_disabled = logger.disabled
    logger.disabled = False
    try:
        with caplog.at_level(logging.DEBUG, logger=logger_name):
            resolved = model_kwargs_capabilities.resolve_supported_model_kwargs(
                model_kwargs_capabilities=_UNTAGGED_DEVELOP_SNAPSHOT,
                reasoning=True,
            )
            loaded = CompletionModelSparse.model_validate(
                _stored_row(_UNTAGGED_DEVELOP_SNAPSHOT)
            )
    finally:
        logger.disabled = was_disabled

    expected = SupportedModelKwargs.model_validate(_UNTAGGED_DEVELOP_SNAPSHOT)
    assert resolved == expected
    assert loaded.model_kwargs_capabilities == expected
    assert loaded.supported_model_kwargs == expected
    # A valid legacy record is not an incident.
    assert caplog.records == []


def test_untagged_capabilities_keep_the_settings_stored_against_them():
    stored = ModelKwargs(reasoning_effort="high", verbosity="low", top_p=0.5)
    model = CompletionModelSparse.model_validate(
        _stored_row(_UNTAGGED_DEVELOP_SNAPSHOT)
    )

    assert stored.filter_unsupported(model.supported_model_kwargs) == stored


@pytest.mark.parametrize(
    "stored",
    [
        {**_UNTAGGED_DEVELOP_SNAPSHOT, "_evidence": "invalid_tag"},
        {**_UNTAGGED_DEVELOP_SNAPSHOT, "_evidence": 123},
        {**_UNTAGGED_DEVELOP_SNAPSHOT, "_evidence": None},
        {"reasoning_effort": {"supported": True, "options": "high"}},
        ["reasoning_effort"],
        "reasoning_effort",
        # A declared range that admits no value.
        {
            **_UNTAGGED_DEVELOP_SNAPSHOT,
            "temperature": {
                "supported": True,
                "control": "slider",
                "minimum": 2,
                "maximum": 1,
            },
        },
        {
            **_UNTAGGED_DEVELOP_SNAPSHOT,
            "_evidence": "provider_discovered",
            "top_p": {
                "supported": True,
                "control": "slider",
                "minimum": 1,
                "maximum": 0,
            },
        },
        {
            **_UNTAGGED_DEVELOP_SNAPSHOT,
            "top_k": {
                "supported": True,
                "control": "slider",
                "minimum": 0.1,
                "maximum": 0.9,
            },
        },
        {
            **_UNTAGGED_DEVELOP_SNAPSHOT,
            "_evidence": "provider_discovered",
            "temperature": {"supported": True, "control": "slider", "step": 0},
        },
    ],
    ids=[
        "unknown-tag",
        "numeric-tag",
        "null-tag",
        "untagged-invalid",
        "not-a-mapping",
        "string",
        "untagged-inverted-range",
        "tagged-inverted-range",
        "untagged-top-k-without-an-integer",
        "tagged-zero-step",
    ],
)
def test_an_invalid_snapshot_fails_closed(stored: object):
    model = CompletionModelSparse.model_validate(_stored_row(stored))
    stored_kwargs = ModelKwargs(reasoning_effort="high", verbosity="low", top_p=0.5)

    # A known "no optional controls", not an absent snapshot that discovery
    # may widen, and not the legacy reading a present tag would bypass.
    assert model.model_kwargs_capabilities == SupportedModelKwargs()
    assert model.supported_model_kwargs == SupportedModelKwargs()
    assert stored_kwargs.filter_unsupported(model.supported_model_kwargs) == (
        ModelKwargs()
    )


def test_discovered_capabilities_are_snapshotted_explicitly():
    snapshot = snapshot_supported_model_kwargs(
        ["temperature", "top_p", "reasoning_effort"], reasoning=False
    )

    assert snapshot.temperature.supported is True
    assert snapshot.top_p.supported is True
    assert snapshot.reasoning_effort.supported is True
    assert snapshot.frequency_penalty.supported is False
    assert snapshot.top_k.supported is False


def test_snapshot_honors_reasoning_flag_when_discovery_misses_it():
    snapshot = snapshot_supported_model_kwargs(["temperature"], reasoning=True)

    assert snapshot.reasoning_effort.supported is True
    assert snapshot.reasoning_effort.options == ["low", "medium", "high"]
    assert snapshot.temperature.supported is True


def test_snapshot_fallback_honors_reasoning_flag():
    snapshot = snapshot_supported_model_kwargs(None, reasoning=True)

    assert snapshot.reasoning_effort.supported is True
    assert snapshot.temperature.supported is False


def test_snapshot_keeps_discovered_reasoning_options_over_fallback():
    snapshot = snapshot_supported_model_kwargs(
        ["reasoning_effort"],
        reasoning=True,
        reasoning_effort_options=["low", "medium", "high", "xhigh"],
    )

    assert snapshot.reasoning_effort.options == ["low", "medium", "high", "xhigh"]


def test_litellm_reasoning_flags_map_to_exact_supported_options():
    options = reasoning_effort_options_from_model_info(
        {
            "supports_reasoning": True,
            "supports_none_reasoning_effort": True,
            "supports_minimal_reasoning_effort": True,
            "supports_low_reasoning_effort": True,
            "supports_xhigh_reasoning_effort": True,
            "supports_max_reasoning_effort": True,
        }
    )

    assert options == ["none", "minimal", "low", "medium", "high", "xhigh", "max"]


def test_snapshot_does_not_invent_reasoning_options_after_explicit_discovery():
    snapshot = snapshot_supported_model_kwargs(
        ["reasoning_effort"],
        reasoning=False,
        reasoning_effort_options=[],
    )

    assert snapshot.reasoning_effort.supported is False


def test_admin_reasoning_flag_restores_conservative_options_after_empty_discovery():
    snapshot = snapshot_supported_model_kwargs(
        ["reasoning_effort"],
        reasoning=True,
        reasoning_effort_options=[],
    )

    assert snapshot.reasoning_effort.options == ["low", "medium", "high"]


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
    model = _completion_model_sparse(
        name="gpt-5.1",
        reasoning=False,
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
    kwargs = ModelKwargs(temperature=0.4, reasoning_effort="high", verbosity="low")

    filtered = kwargs.filter_unsupported(model.supported_model_kwargs)

    assert filtered.temperature == 0.4
    assert filtered.reasoning_effort is None
    assert filtered.verbosity is None


def test_filter_unsupported_returns_self_when_all_supported():
    model = _completion_model_sparse(
        name="gpt-5.1",
        reasoning=True,
        model_kwargs_capabilities={
            "reasoning_effort": {
                "supported": True,
                "control": "select",
                "options": ["low", "medium", "high"],
            }
        },
    )
    kwargs = ModelKwargs(reasoning_effort="medium")

    filtered = kwargs.filter_unsupported(model.supported_model_kwargs)

    assert filtered is kwargs


def test_filter_unsupported_strips_unadvertised_select_values():
    model = _completion_model_sparse(
        reasoning=True,
        model_kwargs_capabilities={
            "reasoning_effort": {
                "supported": True,
                "control": "select",
                "options": ["low", "medium", "high"],
            }
        },
    )

    filtered = ModelKwargs(reasoning_effort="ultra").filter_unsupported(
        model.supported_model_kwargs
    )

    assert filtered.reasoning_effort is None


def test_a_select_without_options_is_refused_and_a_stored_one_offers_nothing():
    declaration = {"reasoning_effort": {"supported": True, "control": "select"}}

    with pytest.raises(ValidationError):
        _completion_model_sparse(reasoning=True, model_kwargs_capabilities=declaration)
    model = CompletionModelSparse.model_validate(_stored_row(declaration))

    assert model.supported_model_kwargs == SupportedModelKwargs()


def test_filter_unsupported_preserves_response_format():
    model = _completion_model_sparse(reasoning=False)
    kwargs = ModelKwargs(response_format={"type": "json_object"})

    filtered = kwargs.filter_unsupported(model.supported_model_kwargs)

    assert filtered.response_format == {"type": "json_object"}


def test_reasoning_flag_does_not_widen_missing_capability_snapshot():
    model = _completion_model_sparse(name="gpt-5.1", reasoning=True)

    assert model.supported_model_kwargs.temperature.supported is False
    assert model.supported_model_kwargs.reasoning_effort.supported is False
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


def test_invalid_stored_capability_metadata_omits_optional_kwargs(
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
        supports_strict_tool_schema=False,
        base_url=None,
        litellm_model_name=None,
        model_kwargs_capabilities={"temperature": {"control": "dial"}},
        provider_type=None,
    )

    logger_name = "eneo.completion_models.domain.model_kwargs_capabilities"
    logger = logging.getLogger(logger_name)
    was_disabled = logger.disabled
    # Integration logging setup disables existing loggers; keep this assertion order-independent.
    logger.disabled = False
    try:
        with caplog.at_level(logging.WARNING, logger=logger_name):
            model = CompletionModelSparse.model_validate(source_model)
    finally:
        logger.disabled = was_disabled

    assert model.model_kwargs_capabilities == SupportedModelKwargs()
    assert model.supported_model_kwargs.temperature.supported is False
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
        supports_strict_tool_schema=False,
        base_url=None,
        litellm_model_name=None,
        model_kwargs_capabilities={"temperature": {"control": "dial"}},
        input_cost_per_token=None,
        output_cost_per_token=None,
        security_classification=None,
        tenant_id=uuid4(),
        provider_id=uuid4(),
        migrated_to_model_id=None,
        deleted_at=None,
    )
    domain_model = CompletionModelDomain.create_from_db(
        db_model,
        tenant=TenantInDB.model_construct(id=uuid4(), name="Test Tenant"),
        provider_name=None,
        provider_type=None,
    )

    public_model = CompletionModelAssembler().from_completion_model_to_model(
        domain_model
    )

    assert domain_model.model_kwargs_capabilities == SupportedModelKwargs()
    assert public_model.supported_model_kwargs.temperature.supported is False


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


def test_sparse_completion_model_preserves_provider_identity_without_widening():
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
        supports_strict_tool_schema=False,
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
    assert sparse_model.supported_model_kwargs.top_p.supported is False
    assert sparse_model.supported_model_kwargs.top_k.supported is False


def test_sparse_projection_preserves_provider_type_without_widening():
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
        supports_strict_tool_schema=False,
        base_url=None,
        litellm_model_name=None,
        model_kwargs_capabilities=None,
        provider_type="vllm",
    )

    sparse_model = CompletionModelSparse.model_validate(admin_model)

    assert sparse_model.provider_type == "vllm"
    assert sparse_model.supported_model_kwargs.top_p.supported is False
    assert sparse_model.supported_model_kwargs.top_k.supported is False


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
        is_effectively_deprecated=False,
        litellm_deprecation_date=None,
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
        supports_strict_tool_schema=False,
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
        migrated_to_model_id=None,
    )

    public_model = CompletionModelAssembler().from_completion_model_to_model(
        source_model
    )

    assert public_model.litellm_model_name == "mistral/mistral-large-latest"
    assert public_model.provider_type == "mistral"
    assert public_model.supported_model_kwargs.reasoning_effort.supported is True
    assert public_model.supported_model_kwargs.top_p.supported is False


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        (0.0, True),
        (1.3, True),
        (2.0, True),
        (2.01, False),
        (-0.5, False),
        (999.0, False),
        (None, True),
    ],
)
def test_a_slider_accepts_only_values_within_its_advertised_range(
    value: float | None, accepted: bool
):
    slider = ModelKwargCapability(
        supported=True, control="slider", minimum=0, maximum=2, step=0.01
    )

    assert slider.accepts(value) is accepted
    stored = ModelKwargs(temperature=value)
    assert (
        stored.filter_unsupported(SupportedModelKwargs(temperature=slider)) == stored
    ) is accepted


@pytest.mark.parametrize(
    "bounds",
    [
        {"minimum": 2, "maximum": 1},
        {"minimum": float("nan")},
        {"maximum": float("inf")},
        {"minimum": float("-inf"), "maximum": 1},
    ],
    ids=["inverted", "nan-minimum", "infinite-maximum", "infinite-minimum"],
)
def test_a_capability_range_must_be_finite_and_ordered(bounds: dict[str, float]):
    with pytest.raises(ValidationError):
        ModelKwargCapability(supported=True, control="slider", **bounds)


def test_a_capability_range_may_be_a_single_value():
    capability = ModelKwargCapability(
        supported=True, control="slider", minimum=1, maximum=1
    )

    assert capability.accepts(1.0) is True
    assert capability.accepts(0.5) is False


@pytest.mark.parametrize(
    "step",
    [float("inf"), float("nan"), 0.0, -0.1],
    ids=["inf", "nan", "zero", "negative"],
)
def test_a_capability_step_must_be_finite_and_positive(step: float):
    with pytest.raises(ValidationError):
        ModelKwargCapability(supported=True, control="slider", step=step)


_SLIDER = {"supported": True, "control": "slider", "minimum": 0, "maximum": 2}
_NUMBER_AS_SELECT = {"supported": True, "control": "select", "options": ["1"]}
_LEVELS_AS_SELECT = {"supported": True, "control": "select", "options": ["low"]}
_LEVELS_AS_SLIDER = {"supported": True, "control": "slider"}


@pytest.mark.parametrize(
    ("setting", "declaration", "valid"),
    [
        # Numbers: offered only as a slider.
        *[
            case
            for setting in (
                "temperature",
                "top_p",
                "presence_penalty",
                "frequency_penalty",
                "top_k",
            )
            for case in (
                (setting, _SLIDER, True),
                (setting, _NUMBER_AS_SELECT, False),
                (setting, {"supported": True}, False),
            )
        ],
        # top_k is a whole number: its slider must admit one.
        ("top_k", {**_SLIDER, "minimum": 0.1, "maximum": 0.9}, False),
        ("top_k", {**_SLIDER, "step": 0.5}, False),
        # Named levels: offered only as a select with options; which levels
        # a route offers (even an unfamiliar one) is its own declaration.
        *[
            case
            for setting in ("reasoning_effort", "verbosity")
            for case in (
                (setting, _LEVELS_AS_SELECT, True),
                (setting, {**_LEVELS_AS_SELECT, "options": ["auto"]}, True),
                (setting, _LEVELS_AS_SLIDER, False),
                (setting, {**_LEVELS_AS_SELECT, "options": []}, False),
                (setting, {**_LEVELS_AS_SELECT, "options": None}, False),
                (setting, {**_LEVELS_AS_SELECT, "options": [""]}, False),
                (setting, {**_LEVELS_AS_SELECT, "options": ["  "]}, False),
                # A blank next to a real option is left to the route's filter.
                (setting, {**_LEVELS_AS_SELECT, "options": ["", "high"]}, True),
            )
        ],
        # A setting that is not offered may carry any shape: it offers nothing.
        ("temperature", {**_NUMBER_AS_SELECT, "supported": False}, True),
        ("verbosity", {**_LEVELS_AS_SLIDER, "supported": False}, True),
    ],
)
def test_an_offered_setting_is_declared_in_a_shape_its_values_fit(
    setting: str, declaration: dict[str, object], valid: bool
):
    stored = CompletionModelSparse.model_validate(_stored_row({setting: declaration}))

    if valid:
        offered = SupportedModelKwargs.model_validate({setting: declaration})
        assert stored.model_kwargs_capabilities == offered
    else:
        # Refused as input; a stored snapshot fails closed.
        with pytest.raises(ValidationError):
            SupportedModelKwargs.model_validate({setting: declaration})
        assert stored.model_kwargs_capabilities == SupportedModelKwargs()


def test_the_declaration_rule_follows_the_model_setting_types():
    # One rule per setting, matching what ModelKwargs stores for it.
    rules = model_kwargs_capabilities.OFFERABLE_MODEL_SETTINGS
    assert set(rules) == set(SupportedModelKwargs.model_fields)
    for name, rule in rules.items():
        annotation = str(ModelKwargs.model_fields[name].annotation)
        if rule is str:
            assert "str" in annotation
        elif rule is int:
            assert "int" in annotation
        else:
            assert "float" in annotation
