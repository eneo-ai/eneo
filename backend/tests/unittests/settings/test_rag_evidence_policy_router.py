from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from eneo.roles.permissions import Permission
from eneo.settings.settings import (
    FlowRagEvidencePolicyPublic,
    FlowRagEvidencePolicyUpdate,
)
from eneo.settings.settings_router import (
    get_rag_evidence_policy,
    settings_admin_router,
    update_rag_evidence_policy,
)


def _policy(**overrides: int) -> FlowRagEvidencePolicyPublic:
    values: dict[str, int] = {
        "max_sources_with_recorded_passages": 25,
        "max_recorded_passages_per_source": 5,
        "max_recorded_passage_bytes": 4096,
        "max_recorded_passage_bytes_per_step": 131072,
        "max_recorded_passage_bytes_per_run_view": 2097152,
    }
    values.update(overrides)
    return FlowRagEvidencePolicyPublic(version=1, **values)


def _container(service: AsyncMock) -> MagicMock:
    container = MagicMock()
    container.settings_service.return_value = service
    container.user.return_value = SimpleNamespace(
        id="u", tenant_id="t", permissions=[Permission.ADMIN]
    )
    return container


@pytest.mark.asyncio
async def test_get_rag_evidence_policy_delegates_to_service() -> None:
    service = AsyncMock()
    service.get_rag_evidence_policy.return_value = _policy(
        max_sources_with_recorded_passages=60
    )

    response = await get_rag_evidence_policy(container=_container(service))

    assert response.max_sources_with_recorded_passages == 60
    service.get_rag_evidence_policy.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_patch_rag_evidence_policy_preserves_null_reset_intent() -> None:
    service = AsyncMock()
    service.update_rag_evidence_policy.return_value = _policy()
    payload = FlowRagEvidencePolicyUpdate(max_recorded_passage_bytes=None)

    response = await update_rag_evidence_policy(
        payload=payload,
        container=_container(service),
    )

    assert response.max_recorded_passage_bytes == 4096
    assert payload.model_dump(exclude_unset=True) == {
        "max_recorded_passage_bytes": None
    }
    service.update_rag_evidence_policy.assert_awaited_once_with(payload)


def test_update_payload_rejects_a_value_above_its_ceiling() -> None:
    with pytest.raises(ValueError):
        FlowRagEvidencePolicyUpdate(max_recorded_passage_bytes=1_000_000)


def test_rag_evidence_policy_openapi_is_complete_for_admin_clients() -> None:
    app = FastAPI()
    app.include_router(settings_admin_router, prefix="/api/v1/settings")
    schema = app.openapi()
    path = schema["paths"]["/api/v1/settings/flow-rag-evidence-policy"]

    assert path["get"]["operationId"] == "get_rag_evidence_policy"
    assert path["patch"]["operationId"] == "update_rag_evidence_policy"
    assert set(path["get"]["responses"]) >= {"200", "403"}
    assert set(path["patch"]["responses"]) >= {"200", "400", "403", "422"}

    schemas = schema["components"]["schemas"]
    for schema_name in (
        "FlowRagEvidencePolicyPublic",
        "FlowRagEvidencePolicyUpdate",
    ):
        policy_schema = schemas[schema_name]
        assert policy_schema["example"]
        for field_name in (
            "max_sources_with_recorded_passages",
            "max_recorded_passages_per_source",
            "max_recorded_passage_bytes",
            "max_recorded_passage_bytes_per_step",
            "max_recorded_passage_bytes_per_run_view",
        ):
            assert policy_schema["properties"][field_name]["description"]
