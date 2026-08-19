from __future__ import annotations

from datetime import datetime, timezone
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
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)
from eneo.spaces.space import Space


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


def _model(
    *,
    provider_id,
    name: str = "planner",
    can_access: bool = True,
    is_org_default: bool = False,
    created_at: datetime | None = None,
    classification: "SecurityClassification | None" = None,
):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        provider_id=provider_id,
        provider_type="openai",
        litellm_model_name=f"openai/{name}",
        max_input_tokens=32_000,
        max_output_tokens=4_000,
        can_access=can_access,
        is_org_default=is_org_default,
        created_at=created_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
        security_classification=classification,
    )


def _classification(level: int) -> SecurityClassification:
    return SecurityClassification(
        tenant_id=uuid4(),
        name=f"level-{level}",
        security_level=level,
        security_enabled=True,
    )


def _space(models, *, classification: SecurityClassification | None = None) -> Space:
    """A real Space, built the way a load builds one.

    The constructor assigns the model list directly rather than through the
    validating setter, which is exactly how a stored list comes to hold a model
    the space would now refuse — the state these tests care about.
    """
    return Space(
        id=uuid4(),
        tenant_id=uuid4(),
        tenant_space_id=None,
        user_id=None,
        name="Planner space",
        description=None,
        embedding_models=[],
        completion_models=models,
        transcription_models=[],
        mcp_servers=[],
        default_assistant=None,
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
        security_classification=classification,
    )


def test_listing_and_omitted_model_resolve_the_same_model() -> None:
    """A default on an inactive provider must not be what an omitted id picks.

    The listing endpoint hides such a model, so resolving to it at send time
    would run a model the session never advertised — and provider resolution
    rejects it, leaving the caller no way through.
    """
    active_provider_id = uuid4()
    inactive_default = _model(
        provider_id=uuid4(), name="inactive-default", is_org_default=True
    )
    active_alternate = _model(provider_id=active_provider_id, name="active-alternate")
    space = _space([inactive_default, active_alternate])
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
    space = _space([inactive, active])

    with pytest.raises(AIBuilderBadRequestException) as excinfo:
        resolve_requested_model(
            space,
            model_id=inactive.id,
            active_provider_ids={active_provider_id},
        )

    assert excinfo.value.code == AIBuilderErrorCode.MODEL_NOT_AVAILABLE


def test_no_eligible_model_is_named_rather_than_silently_substituted() -> None:
    only_inactive = _model(provider_id=uuid4(), name="inactive")
    space = _space([only_inactive])

    assert eligible_planner_models(space, active_provider_ids=set()) == []
    assert select_default_planner_model(space, active_provider_ids=set()) is None
    with pytest.raises(AIBuilderBadRequestException) as excinfo:
        resolve_planner_model(space, active_provider_ids=set())

    assert excinfo.value.code == AIBuilderErrorCode.NO_PLANNER_MODEL_AVAILABLE


def test_fallback_never_crosses_the_space_security_classification() -> None:
    """A space only checks its models when the list is assigned, so a stored
    list can outlive a reclassification. Choosing on the user's behalf must not
    be what quietly hands a restricted space a lower-classified model."""
    provider_id = uuid4()
    below_bar = _model(
        provider_id=provider_id, name="below-bar", classification=_classification(1)
    )
    unclassified = _model(provider_id=provider_id, name="unclassified")
    permitted = _model(
        provider_id=provider_id, name="permitted", classification=_classification(3)
    )
    space = _space(
        [below_bar, unclassified, permitted], classification=_classification(3)
    )

    listed = eligible_planner_models(space, active_provider_ids={provider_id})
    fallback = select_default_planner_model(space, active_provider_ids={provider_id})

    assert listed == [permitted]
    assert fallback is permitted
    with pytest.raises(AIBuilderBadRequestException) as excinfo:
        resolve_requested_model(
            space, model_id=below_bar.id, active_provider_ids={provider_id}
        )
    assert excinfo.value.code == AIBuilderErrorCode.MODEL_NOT_AVAILABLE


def test_inaccessible_models_are_neither_listed_nor_runnable() -> None:
    # can_access covers locked, org-disabled, effectively deprecated, migrated
    # and deleted models; an active provider does not make any of them usable.
    provider_id = uuid4()
    locked = _model(provider_id=provider_id, name="locked", can_access=False)
    usable = _model(provider_id=provider_id, name="usable")
    space = _space([locked, usable])

    assert eligible_planner_models(space, active_provider_ids={provider_id}) == [usable]
    with pytest.raises(AIBuilderBadRequestException) as excinfo:
        resolve_requested_model(
            space, model_id=locked.id, active_provider_ids={provider_id}
        )
    assert excinfo.value.code == AIBuilderErrorCode.MODEL_NOT_AVAILABLE


def test_fallback_prefers_the_organisation_default_then_the_newest() -> None:
    # Taking the first of the list would make persistence order the policy and
    # hand the planner the oldest model whenever a default drops out.
    provider_id = uuid4()
    oldest = _model(
        provider_id=provider_id,
        name="oldest",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    newest = _model(
        provider_id=provider_id,
        name="newest",
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    active_provider_ids = {provider_id}

    without_default = _space([oldest, newest])
    assert (
        select_default_planner_model(
            without_default, active_provider_ids=active_provider_ids
        )
        is newest
    )

    oldest.is_org_default = True
    with_default = _space([oldest, newest])
    assert (
        select_default_planner_model(
            with_default, active_provider_ids=active_provider_ids
        )
        is oldest
    )


def test_planner_context_reuses_admin_builder_attachment_limits() -> None:
    provider_id = uuid4()
    model = _model(provider_id=provider_id, name="gpt-5.4", is_org_default=True)
    space = _space([model])

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
