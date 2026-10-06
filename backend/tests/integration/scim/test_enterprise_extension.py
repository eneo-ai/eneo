"""Integration tests for the SCIM Enterprise User extension (RFC 7643 §4.3).

Exercise the full stack through the mounted scim_app, and assert on the stored
row where the claim is about persistence rather than the response.
"""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from eneo.database.tables.users_table import Users

CORE = "urn:ietf:params:scim:schemas:core:2.0:User"
ENTERPRISE = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
PATCH_OP = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


def _patch(*operations: dict[str, Any]) -> dict[str, Any]:
    return {"schemas": [PATCH_OP], "Operations": list(operations)}


async def _stored(db_session, user_id: str | UUID) -> tuple[str | None, Any]:
    async with db_session() as session:
        row = (
            await session.execute(select(Users).where(Users.id == UUID(str(user_id))))
        ).scalar_one()
        return row.username, row.scim_extensions


async def _set_extension(db_session, user_id: UUID, enterprise: dict[str, Any]) -> None:
    async with db_session() as session:
        row = (
            await session.execute(select(Users).where(Users.id == user_id))
        ).scalar_one()
        row.scim_extensions = {ENTERPRISE: enterprise}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_stores_enterprise_extension_and_echoes_what_was_stored(
    client, bypass_scim_auth, db_session
):
    response = await client.post(
        "/scim/v2/Users",
        json={
            "schemas": [CORE, ENTERPRISE, "urn:example:custom:1.0:User"],
            "userName": "ent.create@example.com",
            ENTERPRISE: {
                "department": "Miljö och hälsa",
                "COSTCENTER": "4130",
                "shoeSize": "44",
                "manager": {"value": "mgr-1", "displayName": "Client Asserted"},
            },
            "urn:example:custom:1.0:User": {"badge": "7"},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["schemas"] == [CORE, ENTERPRISE]
    assert body[ENTERPRISE] == {
        "costCenter": "4130",
        "department": "Miljö och hälsa",
        "manager": {"value": "mgr-1"},
    }
    assert "urn:example:custom:1.0:User" not in body

    _, stored = await _stored(db_session, body["id"])
    assert stored == {
        ENTERPRISE: {
            "department": "Miljö och hälsa",
            "costCenter": "4130",
            "manager": {"value": "mgr-1"},
        }
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_without_extension_leaves_column_null_and_response_unchanged(
    client, bypass_scim_auth, db_session
):
    response = await client.post(
        "/scim/v2/Users", json={"schemas": [CORE], "userName": "plain@example.com"}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["schemas"] == [CORE]
    assert ENTERPRISE not in body
    _, stored = await _stored(db_session, body["id"])
    assert stored is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_create_with_invalid_extension_is_rejected_and_writes_nothing(
    client, bypass_scim_auth, db_session
):
    response = await client.post(
        "/scim/v2/Users",
        json={
            "userName": "invalid.ext@example.com",
            ENTERPRISE: {"costCenter": {"nested": "object"}},
        },
    )

    assert response.status_code == 400
    assert response.json()["scimType"] == "invalidValue"
    async with db_session() as session:
        found = (
            await session.execute(
                select(Users).where(Users.username == "invalid.ext@example.com")
            )
        ).scalar_one_or_none()
    assert found is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_and_list_echo_the_stored_extension(
    client, bypass_scim_auth, db_session, scim_user
):
    await _set_extension(db_session, scim_user.id, {"division": "North"})

    get_body = (await client.get(f"/scim/v2/Users/{scim_user.id}")).json()
    list_body = (
        await client.get("/scim/v2/Users", params={"filter": 'userName eq "scim.user"'})
    ).json()

    assert get_body[ENTERPRISE] == {"division": "North"}
    assert ENTERPRISE in get_body["schemas"]
    assert list_body["Resources"][0][ENTERPRISE] == {"division": "North"}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_put_replaces_the_extension_wholesale(
    client, bypass_scim_auth, db_session, scim_user
):
    await _set_extension(
        db_session,
        scim_user.id,
        {
            "division": "North",
            "department": "HR",
            "manager": {"value": "mgr-1", "$ref": "../Users/mgr-1"},
        },
    )

    response = await client.put(
        f"/scim/v2/Users/{scim_user.id}",
        json={
            "userName": "scim.user",
            "emails": [{"value": "scim-user@example.com", "primary": True}],
            ENTERPRISE: {"department": "Finance", "manager": {"value": "mgr-2"}},
        },
    )

    assert response.status_code == 200
    _, stored = await _stored(db_session, scim_user.id)
    assert stored == {
        ENTERPRISE: {"department": "Finance", "manager": {"value": "mgr-2"}}
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_put_without_extension_clears_it(
    client, bypass_scim_auth, db_session, scim_user
):
    await _set_extension(db_session, scim_user.id, {"department": "HR"})

    response = await client.put(
        f"/scim/v2/Users/{scim_user.id}",
        json={
            "userName": "scim.user",
            "emails": [{"value": "scim-user@example.com", "primary": True}],
        },
    )

    assert response.status_code == 200
    assert ENTERPRISE not in response.json()
    _, stored = await _stored(db_session, scim_user.id)
    assert stored is None


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        (
            {"op": "Replace", "path": f"{ENTERPRISE}:department", "value": "Finance"},
            {"department": "Finance", "costCenter": "4130"},
        ),
        (
            {"op": "Add", "path": f"{ENTERPRISE}:division", "value": "North"},
            {"department": "HR", "costCenter": "4130", "division": "North"},
        ),
        (
            {"op": "Replace", "value": {ENTERPRISE: {"department": "Finance"}}},
            {"department": "Finance", "costCenter": "4130"},
        ),
        (
            {"op": "Replace", "value": {ENTERPRISE: {"department": None}}},
            {"costCenter": "4130"},
        ),
        (
            {"op": "Remove", "path": f"{ENTERPRISE}:department"},
            {"costCenter": "4130"},
        ),
        (
            {"op": "Add", "path": f"{ENTERPRISE}:manager", "value": "mgr-1"},
            {"department": "HR", "costCenter": "4130", "manager": {"value": "mgr-1"}},
        ),
    ],
    ids=[
        "replace-path",
        "add-path",
        "pathless-urn-object",
        "pathless-null-removes",
        "remove-attribute",
        "manager-bare-string",
    ],
)
async def test_patch_operation_forms(
    client, bypass_scim_auth, db_session, scim_user, operation, expected
):
    await _set_extension(
        db_session, scim_user.id, {"department": "HR", "costCenter": "4130"}
    )

    response = await client.patch(
        f"/scim/v2/Users/{scim_user.id}", json=_patch(operation)
    )

    assert response.status_code == 200
    assert response.json()[ENTERPRISE] == expected
    _, stored = await _stored(db_session, scim_user.id)
    assert stored == {ENTERPRISE: expected}


MANAGER_REF = {"$ref": "../Users/mgr-1"}
MANAGER_DISPLAY_NAME = {"displayName": "Client Asserted"}


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("operation", "expected_manager"),
    [
        (
            {"op": "Add", "path": f"{ENTERPRISE}:manager", "value": MANAGER_REF},
            {"value": "mgr-1", "$ref": "../Users/mgr-1"},
        ),
        (
            {"op": "Replace", "path": ENTERPRISE, "value": {"manager": MANAGER_REF}},
            {"value": "mgr-1", "$ref": "../Users/mgr-1"},
        ),
        (
            {"op": "Add", "value": {ENTERPRISE: {"manager": MANAGER_REF}}},
            {"value": "mgr-1", "$ref": "../Users/mgr-1"},
        ),
        (
            {"op": "Replace", "value": {f"{ENTERPRISE}:manager": MANAGER_REF}},
            {"value": "mgr-1", "$ref": "../Users/mgr-1"},
        ),
        (
            {
                "op": "Replace",
                "path": f"{ENTERPRISE}:manager",
                "value": MANAGER_DISPLAY_NAME,
            },
            {"value": "mgr-1"},
        ),
        (
            {"op": "Add", "value": {ENTERPRISE: {"manager": MANAGER_DISPLAY_NAME}}},
            {"value": "mgr-1"},
        ),
    ],
    ids=[
        "add-ref-manager-path",
        "add-ref-urn-path",
        "add-ref-pathless-urn-object",
        "add-ref-pathless-qualified-key",
        "display-name-only-manager-path",
        "display-name-only-pathless",
    ],
)
async def test_patch_manager_object_keeps_unnamed_sub_attributes(
    client, bypass_scim_auth, db_session, scim_user, operation, expected_manager
):
    await _set_extension(
        db_session, scim_user.id, {"department": "HR", "manager": {"value": "mgr-1"}}
    )

    response = await client.patch(
        f"/scim/v2/Users/{scim_user.id}", json=_patch(operation)
    )

    expected = {"department": "HR", "manager": expected_manager}
    assert response.status_code == 200
    assert response.json()[ENTERPRISE] == expected
    _, stored = await _stored(db_session, scim_user.id)
    assert stored == {ENTERPRISE: expected}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_patch_remove_whole_extension_clears_column(
    client, bypass_scim_auth, db_session, scim_user
):
    await _set_extension(db_session, scim_user.id, {"department": "HR"})

    response = await client.patch(
        f"/scim/v2/Users/{scim_user.id}",
        json=_patch({"op": "remove", "path": ENTERPRISE}),
    )

    assert response.status_code == 200
    assert response.json()["schemas"] == [CORE]
    _, stored = await _stored(db_session, scim_user.id)
    assert stored is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_patch_is_atomic_when_a_later_operation_is_invalid(
    client, bypass_scim_auth, db_session, scim_user
):
    await _set_extension(db_session, scim_user.id, {"department": "HR"})
    before = await _stored(db_session, scim_user.id)

    response = await client.patch(
        f"/scim/v2/Users/{scim_user.id}",
        json=_patch(
            {"op": "replace", "path": "userName", "value": "renamed.user"},
            {"op": "replace", "path": f"{ENTERPRISE}:department", "value": "Finance"},
            {"op": "replace", "path": f"{ENTERPRISE}:costCenter", "value": 4130},
        ),
    )

    assert response.status_code == 400
    assert response.json()["scimType"] == "invalidValue"
    assert await _stored(db_session, scim_user.id) == before


@pytest.mark.asyncio
@pytest.mark.integration
async def test_patch_unknown_extension_attribute_is_invalid_path(
    client, bypass_scim_auth, db_session, scim_user
):
    response = await client.patch(
        f"/scim/v2/Users/{scim_user.id}",
        json=_patch({"op": "replace", "path": f"{ENTERPRISE}:shoeSize", "value": "44"}),
    )

    assert response.status_code == 400
    assert response.json()["scimType"] == "invalidPath"
    _, stored = await _stored(db_session, scim_user.id)
    assert stored is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_bulk_invalid_extension_is_a_400_not_a_500(client, bypass_scim_auth):
    response = await client.post(
        "/scim/v2/Bulk",
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:BulkRequest"],
            "Operations": [
                {
                    "method": "POST",
                    "path": "/Users",
                    "bulkId": "u1",
                    "data": {
                        "userName": "bulk.ext@example.com",
                        ENTERPRISE: {"department": 7},
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    result = response.json()["Operations"][0]
    assert result["status"] == "400"
    assert result["response"]["scimType"] == "invalidValue"
