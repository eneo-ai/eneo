"""Stored model settings survive a load, an unrelated edit and a save.

The stored settings stay as saved; only a request filters them against what
the model accepts now. Covered: an untagged (pre-evidence-tag) snapshot, a
snapshot that does not validate, and a stored effort the model's snapshot no
longer offers, for assistants and apps.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
    persist_discovered_model_kwargs_capabilities,
)
from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.app_table import Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.spaces_table import SpacesCompletionModels
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserUpdate

_LOW_MEDIUM_HIGH = {
    "supported": True,
    "control": "select",
    "options": ["low", "medium", "high"],
}
# The catalogue backfill develop stores, without an `_evidence` tag.
_UNTAGGED_SNAPSHOT: dict[str, object] = {
    "temperature": {"supported": False},
    "top_p": {"supported": True, "control": "slider", "minimum": 0, "maximum": 1},
    "reasoning_effort": _LOW_MEDIUM_HIGH,
    "verbosity": _LOW_MEDIUM_HIGH,
    "presence_penalty": {"supported": False},
    "frequency_penalty": {"supported": False},
    "top_k": {"supported": False},
}
_MALFORMED_SNAPSHOT: dict[str, object] = {
    **_UNTAGGED_SNAPSHOT,
    "_evidence": "not-a-tag",
}
# A discovered snapshot that no longer offers "none" (the migration removed
# it), stored against an effort of "none".
_TAGGED_SNAPSHOT = persist_discovered_model_kwargs_capabilities(
    SupportedModelKwargs(
        top_p=ModelKwargCapability(
            supported=True, control="slider", minimum=0, maximum=1
        ),
        reasoning_effort=ModelKwargCapability.model_validate(_LOW_MEDIUM_HIGH),
        verbosity=ModelKwargCapability.model_validate(_LOW_MEDIUM_HIGH),
    )
)
_SETTINGS: dict[str, object] = {
    "reasoning_effort": "high",
    "verbosity": "low",
    "top_p": 0.5,
}
_EXCLUDED_SETTINGS: dict[str, object] = {**_SETTINGS, "reasoning_effort": "none"}

_CASES = [
    pytest.param(_UNTAGGED_SNAPSHOT, _SETTINGS, id="untagged-snapshot"),
    pytest.param(_MALFORMED_SNAPSHOT, _SETTINGS, id="malformed-snapshot"),
    pytest.param(
        {"reasoning_effort": {"supported": True, "options": "high"}},
        _SETTINGS,
        id="invalid-snapshot",
    ),
    pytest.param(_TAGGED_SNAPSHOT, _EXCLUDED_SETTINGS, id="excluded-effort"),
]


async def _token_and_space(client, db_container, admin_user) -> tuple[str, UUID]:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"stored-settings-{uuid4().hex[:8]}",
                permissions=[
                    Permission.ASSISTANTS,
                    Permission.APPS,
                    Permission.SHARED_SPACES,
                ],
                tenant_id=admin_user.tenant_id,
            )
        )
    async with db_container() as container:
        admin = await container.user_repo().update(
            UserUpdate(id=admin_user.id, roles=[ModelId(id=role.id)])
        )
        assert admin is not None
        token = container.auth_service().create_access_token_for_user(admin)
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"stored-settings-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return token, UUID(response.json()["id"])


async def _seed_model(
    session, completion_model_factory, space_id: UUID, capabilities: object
) -> UUID:
    model = await completion_model_factory(
        session, f"stored-settings-{uuid4().hex[:8]}", reasoning=True
    )
    # Stored as JSON exactly as given (develop stores untagged snapshots).
    await session.execute(
        sa.update(CompletionModels)
        .where(CompletionModels.id == model.id)
        .values(model_kwargs_capabilities=capabilities)
    )
    session.add(SpacesCompletionModels(space_id=space_id, completion_model_id=model.id))
    return model.id


def _set(values: object) -> dict[str, object]:
    assert isinstance(values, dict)
    return {key: value for key, value in values.items() if value is not None}


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(("capabilities", "stored"), _CASES)
async def test_an_assistant_rename_keeps_its_stored_model_settings(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    completion_model_factory,
    assistant_factory,
    capabilities: object,
    stored: dict[str, object],
):
    _ = patch_auth_service_jwt
    token, space_id = await _token_and_space(client, db_container, admin_user)
    async with db_container() as container:
        session = container.session()
        model_id = await _seed_model(
            session, completion_model_factory, space_id, capabilities
        )
        assistant = await assistant_factory(
            session, "stored settings", model_id, kwargs=dict(stored), space_id=space_id
        )
        assistant_id = assistant.id
    headers = {"Authorization": f"Bearer {token}"}

    loaded = await client.get(f"/api/v1/assistants/{assistant_id}/", headers=headers)
    edited = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"name": "renamed"},
        headers=headers,
    )

    assert loaded.status_code == 200, loaded.text
    assert edited.status_code == 200, edited.text
    assert edited.json()["name"] == "renamed"
    async with db_container() as container:
        row = await container.session().scalar(
            sa.select(Assistants.completion_model_kwargs).where(
                Assistants.id == assistant_id
            )
        )
    # The save writes the stored settings back unchanged, and they are shown.
    assert _set(row) == stored
    assert _set(loaded.json()["completion_model_kwargs"]) == stored
    assert _set(edited.json()["completion_model_kwargs"]) == stored


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(("capabilities", "stored"), _CASES)
async def test_an_app_rename_keeps_its_stored_model_settings(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    completion_model_factory,
    app_factory,
    capabilities: object,
    stored: dict[str, object],
):
    _ = patch_auth_service_jwt
    token, space_id = await _token_and_space(client, db_container, admin_user)
    async with db_container() as container:
        session = container.session()
        model_id = await _seed_model(
            session, completion_model_factory, space_id, capabilities
        )
        app = await app_factory(
            session,
            "stored settings",
            model_id,
            space_id=space_id,
            completion_model_kwargs=dict(stored),
        )
        app_id = app.id

    edited = await client.patch(
        f"/api/v1/apps/{app_id}/",
        json={"name": "renamed"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert edited.status_code == 200, edited.text
    assert edited.json()["name"] == "renamed"
    async with db_container() as container:
        row = await container.session().scalar(
            sa.select(Apps.completion_model_kwargs).where(Apps.id == app_id)
        )
    assert _set(row) == stored
    assert _set(edited.json()["completion_model_kwargs"]) == stored


@pytest.mark.asyncio
@pytest.mark.integration
async def test_an_untagged_snapshot_offers_its_stored_options(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    completion_model_factory,
    assistant_factory,
):
    _ = patch_auth_service_jwt
    token, space_id = await _token_and_space(client, db_container, admin_user)
    async with db_container() as container:
        session = container.session()
        model_id = await _seed_model(
            session, completion_model_factory, space_id, _UNTAGGED_SNAPSHOT
        )
        assistant = await assistant_factory(
            session, "legacy", model_id, kwargs=dict(_SETTINGS), space_id=space_id
        )
        assistant_id = assistant.id

    loaded = await client.get(
        f"/api/v1/assistants/{assistant_id}/",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert loaded.status_code == 200, loaded.text
    supported = loaded.json()["completion_model"]["supported_model_kwargs"]
    assert supported["reasoning_effort"]["options"] == ["low", "medium", "high"]
    assert supported["verbosity"]["supported"] is True
    assert supported["top_p"]["supported"] is True


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    "capabilities",
    [
        _MALFORMED_SNAPSHOT,
        {"reasoning_effort": {"supported": True, "options": "x"}},
        {
            **_UNTAGGED_SNAPSHOT,
            "top_p": {
                "supported": True,
                "control": "slider",
                "minimum": 1,
                "maximum": 0,
            },
        },
    ],
    ids=["malformed-snapshot", "invalid-snapshot", "inverted-range-snapshot"],
)
async def test_an_invalid_snapshot_offers_no_controls(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    completion_model_factory,
    assistant_factory,
    capabilities: dict[str, object],
):
    _ = patch_auth_service_jwt
    token, space_id = await _token_and_space(client, db_container, admin_user)
    async with db_container() as container:
        session = container.session()
        model_id = await _seed_model(
            session, completion_model_factory, space_id, capabilities
        )
        assistant = await assistant_factory(
            session, "invalid", model_id, kwargs=dict(_SETTINGS), space_id=space_id
        )
        assistant_id = assistant.id

    loaded = await client.get(
        f"/api/v1/assistants/{assistant_id}/",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Fails closed: a record that does not validate is not read as a legacy
    # snapshot, so the model offers nothing.
    assert loaded.status_code == 200, loaded.text
    supported = loaded.json()["completion_model"]["supported_model_kwargs"]
    assert not any(capability["supported"] for capability in supported.values())


# Editing model settings: a value the edit changes must be offered by the
# model; a value left as stored against the same model is kept; on another
# model every value must be offered.
_EDIT_CASES = [
    pytest.param(
        {**_EXCLUDED_SETTINGS, "top_p": 0.7},
        False,
        200,
        id="stale-effort-kept-while-another-value-changes",
    ),
    pytest.param(
        {**_EXCLUDED_SETTINGS, "reasoning_effort": "xhigh"},
        False,
        400,
        id="changed-effort-not-offered",
    ),
    pytest.param(
        {**_EXCLUDED_SETTINGS, "reasoning_effort": "medium"},
        False,
        200,
        id="changed-effort-offered",
    ),
    pytest.param(
        dict(_EXCLUDED_SETTINGS), True, 400, id="stale-effort-on-another-model"
    ),
    pytest.param(
        {**_EXCLUDED_SETTINGS, "top_p": 1.5},
        False,
        400,
        id="changed-value-outside-the-advertised-range",
    ),
]


async def _seed_edit_target(
    db_container, completion_model_factory, space_id: UUID
) -> tuple[UUID, UUID]:
    async with db_container() as container:
        session = container.session()
        model_id = await _seed_model(
            session, completion_model_factory, space_id, _TAGGED_SNAPSHOT
        )
        other_model_id = await _seed_model(
            session, completion_model_factory, space_id, _TAGGED_SNAPSHOT
        )
    return model_id, other_model_id


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(("submitted", "other_model", "status"), _EDIT_CASES)
async def test_an_assistant_settings_edit_is_checked_against_its_model(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    completion_model_factory,
    assistant_factory,
    submitted: dict[str, object],
    other_model: bool,
    status: int,
):
    _ = patch_auth_service_jwt
    token, space_id = await _token_and_space(client, db_container, admin_user)
    model_id, other_model_id = await _seed_edit_target(
        db_container, completion_model_factory, space_id
    )
    async with db_container() as container:
        assistant = await assistant_factory(
            container.session(),
            "edited",
            model_id,
            kwargs=dict(_EXCLUDED_SETTINGS),
            space_id=space_id,
        )
        assistant_id = assistant.id
    body: dict[str, object] = {"completion_model_kwargs": submitted}
    if other_model:
        body["completion_model"] = {"id": str(other_model_id)}

    response = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == status, response.text
    if status == 400:
        assert "unsupported by the selected model" in response.text
    async with db_container() as container:
        row = await container.session().scalar(
            sa.select(Assistants.completion_model_kwargs).where(
                Assistants.id == assistant_id
            )
        )
    assert _set(row) == (submitted if status == 200 else _EXCLUDED_SETTINGS)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(("submitted", "other_model", "status"), _EDIT_CASES)
async def test_an_app_settings_edit_is_checked_against_its_model(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    completion_model_factory,
    app_factory,
    submitted: dict[str, object],
    other_model: bool,
    status: int,
):
    _ = patch_auth_service_jwt
    token, space_id = await _token_and_space(client, db_container, admin_user)
    model_id, other_model_id = await _seed_edit_target(
        db_container, completion_model_factory, space_id
    )
    async with db_container() as container:
        app = await app_factory(
            container.session(),
            "edited",
            model_id,
            space_id=space_id,
            completion_model_kwargs=dict(_EXCLUDED_SETTINGS),
        )
        app_id = app.id
    body: dict[str, object] = {"completion_model_kwargs": submitted}
    if other_model:
        body["completion_model"] = {"id": str(other_model_id)}

    response = await client.patch(
        f"/api/v1/apps/{app_id}/",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == status, response.text
    if status == 400:
        assert "unsupported by the selected model" in response.text
    async with db_container() as container:
        row = await container.session().scalar(
            sa.select(Apps.completion_model_kwargs).where(Apps.id == app_id)
        )
    assert _set(row) == (submitted if status == 200 else _EXCLUDED_SETTINGS)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize("token_value", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize("resource", ["assistant", "app"])
async def test_a_settings_edit_with_a_non_finite_number_is_refused(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    completion_model_factory,
    assistant_factory,
    app_factory,
    token_value: str,
    resource: str,
):
    _ = patch_auth_service_jwt
    token, space_id = await _token_and_space(client, db_container, admin_user)
    model_id, _ = await _seed_edit_target(
        db_container, completion_model_factory, space_id
    )
    async with db_container() as container:
        session = container.session()
        if resource == "assistant":
            item = await assistant_factory(
                session, "finite", model_id, kwargs=dict(_SETTINGS), space_id=space_id
            )
        else:
            item = await app_factory(
                session,
                "finite",
                model_id,
                space_id=space_id,
                completion_model_kwargs=dict(_SETTINGS),
            )
        item_id = item.id
    # The JSON parser accepts these tokens; the typed settings must not.
    body = '{"completion_model_kwargs": {"top_p": %s}}' % token_value
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    if resource == "assistant":
        response = await client.post(
            f"/api/v1/assistants/{item_id}/", content=body, headers=headers
        )
    else:
        response = await client.patch(
            f"/api/v1/apps/{item_id}/", content=body, headers=headers
        )

    assert response.status_code == 422, response.text
    table = Assistants if resource == "assistant" else Apps
    async with db_container() as container:
        row = await container.session().scalar(
            sa.select(table.completion_model_kwargs).where(table.id == item_id)
        )
    assert _set(row) == _SETTINGS
