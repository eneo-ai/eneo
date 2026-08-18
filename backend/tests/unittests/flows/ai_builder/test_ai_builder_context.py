from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.flows.ai_builder.ai_builder_context import (
    build_planner_context,
    eligible_planner_models,
    resolve_planner_model,
    resolve_requested_model,
    select_default_planner_model,
    serialize_space_kbs,
    serialize_space_models,
)
from eneo.flows.ai_builder.ai_builder_error_contract import (
    AIBuilderBadRequestException,
    AIBuilderErrorCode,
)


def test_serialize_space_models_keeps_local_id_for_catalog_input() -> None:
    model_id = uuid4()
    space = SimpleNamespace(
        completion_models=[
            SimpleNamespace(id=model_id, name="gpt-5.4-nano", provider_type="openai")
        ]
    )

    assert serialize_space_models(space) == [
        {
            "id": str(model_id),
            "ref": str(model_id),
            "name": "gpt-5.4-nano",
            "display_name": "gpt-5.4-nano",
            "provider": "openai",
        }
    ]


def test_serialize_space_kbs_keeps_local_id_for_catalog_input() -> None:
    kb_id = uuid4()
    space = SimpleNamespace(
        collections=[
            SimpleNamespace(
                id=kb_id,
                name="Policy",
                description="Local policy reference material.",
            )
        ]
    )

    assert serialize_space_kbs(space) == [
        {
            "id": str(kb_id),
            "ref": str(kb_id),
            "name": "Policy",
            "display_name": "Policy",
            "description": "Local policy reference material.",
        }
    ]


def _model(*, provider_id, name: str = "planner"):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        provider_id=provider_id,
        provider_type="openai",
        litellm_model_name=f"openai/{name}",
        max_input_tokens=32_000,
        max_output_tokens=4_000,
    )


def test_listing_and_omitted_model_resolve_the_same_model() -> None:
    """A default on an inactive provider must not be what an omitted id picks.

    The listing endpoint hides such a model, so resolving to it at send time
    would run a model the session never advertised — and provider resolution
    rejects it, leaving the caller no way through.
    """
    active_provider_id = uuid4()
    inactive_default = _model(provider_id=uuid4(), name="inactive-default")
    active_alternate = _model(provider_id=active_provider_id, name="active-alternate")
    space = SimpleNamespace(
        completion_models=[inactive_default, active_alternate],
        collections=[],
        get_default_completion_model=lambda: inactive_default,
    )
    active_provider_ids = {active_provider_id}

    listed = eligible_planner_models(space, active_provider_ids=active_provider_ids)
    advertised_default = select_default_planner_model(
        space, active_provider_ids=active_provider_ids
    )
    sent = resolve_requested_model(
        space, model_id=None, active_provider_ids=active_provider_ids
    )

    assert listed == [active_alternate]
    assert advertised_default is active_alternate
    assert sent is active_alternate


def test_explicitly_requesting_an_inactive_model_is_rejected_as_unavailable() -> None:
    active_provider_id = uuid4()
    inactive = _model(provider_id=uuid4(), name="inactive")
    active = _model(provider_id=active_provider_id, name="active")
    space = SimpleNamespace(
        completion_models=[inactive, active],
        collections=[],
        get_default_completion_model=lambda: active,
    )

    with pytest.raises(AIBuilderBadRequestException) as excinfo:
        resolve_requested_model(
            space,
            model_id=inactive.id,
            active_provider_ids={active_provider_id},
        )

    assert excinfo.value.code == AIBuilderErrorCode.MODEL_NOT_AVAILABLE


def test_no_eligible_model_is_named_rather_than_silently_substituted() -> None:
    only_inactive = _model(provider_id=uuid4(), name="inactive")
    space = SimpleNamespace(
        completion_models=[only_inactive],
        collections=[],
        get_default_completion_model=lambda: only_inactive,
    )

    assert eligible_planner_models(space, active_provider_ids=set()) == []
    assert select_default_planner_model(space, active_provider_ids=set()) is None
    with pytest.raises(AIBuilderBadRequestException) as excinfo:
        resolve_planner_model(space, active_provider_ids=set())

    assert excinfo.value.code == AIBuilderErrorCode.NO_PLANNER_MODEL_AVAILABLE


def test_planner_context_reuses_admin_builder_attachment_limits() -> None:
    provider_id = uuid4()
    model = SimpleNamespace(
        id=uuid4(),
        name="planner",
        provider_id=provider_id,
        provider_type="openai",
        litellm_model_name="openai/gpt-5.4",
        max_input_tokens=32_000,
        max_output_tokens=4_000,
    )
    space = SimpleNamespace(
        completion_models=[model],
        collections=[],
        get_default_completion_model=lambda: model,
    )

    context = build_planner_context(
        space,
        active_provider_ids={provider_id},
        tenant_flow_settings={
            "ai_builder": {
                "max_template_inspection_uncompressed_bytes": 64 * 1024 * 1024,
                "max_template_placeholders": 73,
            },
        },
    )

    assert (
        context.attachment_context_policy.max_template_uncompressed_bytes
        == 64 * 1024 * 1024
    )
    assert context.attachment_context_policy.max_template_placeholders == 73
