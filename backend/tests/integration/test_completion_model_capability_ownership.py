"""Discovery records unknown reasoning levels, and nothing sent changes.

Discovery that cannot read the route's model metadata records the reasoning
levels as unknown, not as unsupported, and that survives persistence. An
unknown setting is not offered, like an unsupported one, so what reaches the
provider is exactly what origin sends for the unsupported record it stored
before.

Discovery outcomes are stubbed per route name, so these tests do not depend
on LiteLLM's model registry; the installed registry's answer for the measured
route is observed separately (test_tenant_model_service.py, the probe).
"""

from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update

from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.authentication.auth_service import AuthService
from eneo.completion_models.infrastructure.tenant_model_capabilities import (
    stored_request_model_kwargs,
)
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.model_providers_table import ModelProviders

# Route names and what discovery answers for each.
_UNMAPPED = "gemma4-31b-it"  # LiteLLM forwards the parameter, has no model info
_NO_LEVELS = "known-without-levels"  # model info without reasoning
_LEVELS = "known-with-levels"  # model info with the standard levels
_PARAMS = ["temperature", "top_p", "reasoning_effort"]
_MODEL_INFO: dict[str, Mapping[str, object] | Exception] = {
    _UNMAPPED: RuntimeError("This model isn't mapped yet."),
    _NO_LEVELS: {},
    _LEVELS: {"supports_reasoning": True},
}
_SERVICE = "eneo.tenant_models.application.tenant_model_service."

_TENANT_MODELS = "/api/v1/admin/tenant-models/completion/"
_UNSUPPORTED = {
    "step": None,
    "control": None,
    "maximum": None,
    "minimum": None,
    "options": None,
    "supported": False,
}
_SLIDER = {**_UNSUPPORTED, "supported": True, "control": "slider", "step": 0.01}
# The snapshot existing databases hold for the measured route: discovery
# could not read its model metadata and recorded the levels as unsupported.
_MISRECORDED_SNAPSHOT = {
    "_evidence": "provider_discovered",
    "temperature": {**_SLIDER, "minimum": 0.0, "maximum": 2.0},
    "top_p": {**_SLIDER, "minimum": 0.0, "maximum": 1.0},
    "reasoning_effort": _UNSUPPORTED,
    "verbosity": _UNSUPPORTED,
    "presence_penalty": _UNSUPPORTED,
    "frequency_penalty": _UNSUPPORTED,
    "top_k": _UNSUPPORTED,
}


@pytest.fixture(autouse=True)
def discovery(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str] | None]:
    """Stubbed LiteLLM metadata; a test may change a route's parameters."""
    params: dict[str, list[str] | None] = {
        _UNMAPPED: _PARAMS,
        _NO_LEVELS: _PARAMS,
        _LEVELS: _PARAMS,
    }

    def route_name(route: str) -> str:
        return route.removeprefix("openai/")

    def supported_params(route: str) -> list[str] | None:
        return params[route_name(route)]

    def model_info(route: str) -> Mapping[str, object]:
        info = _MODEL_INFO[route_name(route)]
        if isinstance(info, Exception):
            raise info
        return info

    monkeypatch.setattr(_SERVICE + "get_supported_openai_params", supported_params)
    monkeypatch.setattr(_SERVICE + "get_model_info", model_info)
    return params


@pytest.fixture
async def admin_headers(db_container, patch_auth_service_jwt, admin_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        assert isinstance(auth_service, AuthService)
        token = auth_service.create_access_token_for_user(admin_user)
    return {"Authorization": f"Bearer {token}"}


async def _provider(db_container, admin_user) -> UUID:
    async with db_container() as container:
        session = container.session()
        provider = ModelProviders(
            tenant_id=admin_user.tenant_id,
            name=f"gdm-{uuid4()}",
            provider_type="openai",
            credentials={"api_key": container.encryption_service().encrypt("test-key")},
            config={"endpoint": "https://gdm.invalid/api/v1"},
            is_active=True,
        )
        session.add(provider)
        await session.flush()
        provider_id = provider.id
        await session.commit()
    return provider_id


async def _create(client, headers, provider_id: UUID, name: str = _UNMAPPED) -> dict:
    response = await client.post(
        _TENANT_MODELS,
        headers=headers,
        json={
            "provider_id": str(provider_id),
            "name": name,
            "display_name": f"{name} {uuid4()}",
            "max_input_tokens": 128000,
            "max_output_tokens": 16384,
            "reasoning": True,
            "supports_tool_calling": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _put(client, headers, model_id: str, payload: dict) -> dict:
    response = await client.put(
        f"{_TENANT_MODELS}{model_id}/", headers=headers, json=payload
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _stored(db_container, model_id: str) -> dict:
    async with db_container() as container:
        stored = await container.session().scalar(
            select(CompletionModels.model_kwargs_capabilities).where(
                CompletionModels.id == UUID(model_id)
            )
        )
    assert isinstance(stored, dict)
    return stored


async def _store(db_container, model_ids: list[str], snapshot: dict) -> None:
    async with db_container() as container:
        session = container.session()
        await session.execute(
            update(CompletionModels)
            .where(CompletionModels.id.in_([UUID(id) for id in model_ids]))
            .values(model_kwargs_capabilities=snapshot)
        )
        await session.commit()


def _edit_form_save(model: dict, **changes: object) -> dict:
    """What the admin edit dialog sends: every field, the reasoning flag and
    the unchanged name included, never the capability record."""
    return {
        "name": model["name"],
        "display_name": model["nickname"],
        "description": model.get("description"),
        "hosting": model["hosting"],
        "open_source": model["open_source"],
        "vision": model["vision"],
        "reasoning": model["reasoning"],
        "supports_tool_calling": model["supports_tool_calling"],
        "input_cost_per_token": None,
        "output_cost_per_token": None,
        "is_default": False,
        **changes,
    }


async def _final_provider_kwargs(
    db_container, admin_user, model_id: str, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, object], dict[str, object]]:
    """What reaches the provider for a request with stored settings (effort
    "high", temperature 0.2), through the resolved route (the Builder's path)
    and the model adapter (assistants, apps and flow steps)."""
    # The transport's own LiteLLM reads, stubbed like discovery: the route
    # forwards reasoning_effort and LiteLLM has no model info for it.
    transport = "eneo.completion_models.infrastructure.tenant_model_capabilities."
    monkeypatch.setattr(
        transport + "get_supported_openai_params", lambda **_: tuple(_PARAMS)
    )

    def no_model_info(**_: object) -> Mapping[str, object]:
        raise RuntimeError("This model isn't mapped yet.")

    monkeypatch.setattr(transport + "litellm.get_model_info", no_model_info)
    stored = ModelKwargs(reasoning_effort="high", temperature=0.2)
    sent = {"reasoning_effort", "temperature"}
    async with db_container(user=admin_user) as container:
        model = await container.completion_model_repo2().one(model_id=UUID(model_id))
        service = container.completion_service()
        route = await service.resolve_model_route(model)
        adapter = await service._get_adapter(model)
        sendable = stored_request_model_kwargs(
            stored, route.supported_model_kwargs, completion_model_id=model.id
        )
        via_route = route.prepare_provider_kwargs(sendable)
        via_adapter = adapter._prepare_kwargs(model_kwargs=sendable)
    return (
        {key: value for key, value in via_route.items() if key in sent},
        {key: value for key, value in via_adapter.items() if key in sent},
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("name", "unknown", "options"),
    [
        (_UNMAPPED, True, None),
        (_NO_LEVELS, False, None),
        (_LEVELS, False, ["low", "medium", "high"]),
    ],
    ids=["metadata-missing", "known-without-levels", "known-levels"],
)
async def test_discovery_records_what_the_route_metadata_says(
    client, db_container, admin_user, admin_headers, name, unknown, options
):
    provider_id = await _provider(db_container, admin_user)

    created = await _create(client, admin_headers, provider_id, name=name)

    stored = await _stored(db_container, created["id"])
    assert stored["_evidence"] == "provider_discovered"
    effort = stored["reasoning_effort"]
    assert (effort["unknown"], effort["options"]) == (unknown, options)
    assert effort["supported"] is (options is not None)
    # Unknown is about the levels only; the sampling controls LiteLLM
    # forwards for the route are recorded as before.
    assert stored["temperature"]["supported"] is True
    # Read back from the database after an unrelated save, it is unchanged.
    saved = await _put(
        client,
        admin_headers,
        created["id"],
        _edit_form_save(created, display_name=f"Renamed {uuid4()}"),
    )
    assert saved["supported_model_kwargs"]["reasoning_effort"]["unknown"] is unknown
    assert (await _stored(db_container, created["id"])) == stored


@pytest.mark.integration
async def test_recording_unknown_levels_sends_what_origin_sends(
    client, db_container, admin_user, admin_headers, monkeypatch
):
    """The only change of this slice to a stored record is unknown instead of
    unsupported at discovery. The final provider kwargs for the same row,
    with the record origin stores and with the one discovery stores now, are
    identical on both request paths."""
    provider_id = await _provider(db_container, admin_user)
    created = await _create(client, admin_headers, provider_id)
    assert (await _stored(db_container, created["id"]))["reasoning_effort"][
        "unknown"
    ] is True
    now = await _final_provider_kwargs(
        db_container, admin_user, created["id"], monkeypatch
    )

    await _store(db_container, [created["id"]], _MISRECORDED_SNAPSHOT)
    on_origin = await _final_provider_kwargs(
        db_container, admin_user, created["id"], monkeypatch
    )

    assert now == on_origin
    # The stored effort is not offered either way; what is sent besides the
    # stored temperature is the transport's own absent-effort value.
    assert now == ({"reasoning_effort": "low", "temperature": 0.2},) * 2
