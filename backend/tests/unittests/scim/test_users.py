from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from intric.scim.app import scim_app
from intric.scim.auth import require_scim_auth
from intric.scim.deps import get_scim_user_service
from intric.scim.domain.errors import ScimUserConflictError, ScimUserNotFoundError
from intric.scim.schemas.user import ScimMeta, ScimUser
from intric.scim.services.user_service import ScimUserService
from intric.server.main import app

TEST_TOKEN = "test-scim-token"
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


def _make_scim_user(user_name: str = "jane@example.com") -> ScimUser:
    return ScimUser(
        id=str(uuid4()),
        userName=user_name,
        active=True,
        meta=ScimMeta(resourceType="User"),
    )


@pytest.fixture
def mock_service() -> AsyncMock:
    return AsyncMock(spec=ScimUserService)


@pytest.fixture
async def client(mock_service: AsyncMock) -> AsyncClient:
    from tests.unittests.scim.conftest import _check_test_token

    scim_app.dependency_overrides[require_scim_auth] = _check_test_token
    scim_app.dependency_overrides[get_scim_user_service] = lambda: mock_service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    scim_app.dependency_overrides.clear()


CREATE_PAYLOAD = {
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
    "userName": "jane@example.com",
    "emails": [{"value": "jane@example.com", "primary": True}],
    "active": True,
}


class TestCreateUser:
    async def test_returns_201(self, client: AsyncClient, mock_service: AsyncMock):
        mock_service.create_user.return_value = _make_scim_user()
        res = await client.post("/scim/v2/Users", json=CREATE_PAYLOAD, headers=AUTH)
        assert res.status_code == 201

    async def test_returns_user_schema(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.create_user.return_value = _make_scim_user()
        res = await client.post("/scim/v2/Users", json=CREATE_PAYLOAD, headers=AUTH)
        assert "urn:ietf:params:scim:schemas:core:2.0:User" in res.json()["schemas"]

    async def test_returns_id(self, client: AsyncClient, mock_service: AsyncMock):
        mock_service.create_user.return_value = _make_scim_user()
        res = await client.post("/scim/v2/Users", json=CREATE_PAYLOAD, headers=AUTH)
        assert res.json()["id"]

    async def test_returns_meta_resource_type(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.create_user.return_value = _make_scim_user()
        res = await client.post("/scim/v2/Users", json=CREATE_PAYLOAD, headers=AUTH)
        assert res.json()["meta"]["resourceType"] == "User"

    async def test_conflict_returns_409(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.create_user.side_effect = ScimUserConflictError("already exists")
        res = await client.post("/scim/v2/Users", json=CREATE_PAYLOAD, headers=AUTH)
        assert res.status_code == 409

    async def test_conflict_returns_scim_error_schema(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.create_user.side_effect = ScimUserConflictError("already exists")
        res = await client.post("/scim/v2/Users", json=CREATE_PAYLOAD, headers=AUTH)
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in res.json()["schemas"]

    async def test_conflict_returns_uniqueness_scim_type(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.create_user.side_effect = ScimUserConflictError("already exists")
        res = await client.post("/scim/v2/Users", json=CREATE_PAYLOAD, headers=AUTH)
        assert res.json()["scimType"] == "uniqueness"

    async def test_conflict_returns_status_as_string(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.create_user.side_effect = ScimUserConflictError("already exists")
        res = await client.post("/scim/v2/Users", json=CREATE_PAYLOAD, headers=AUTH)
        assert res.json()["status"] == "409"

    async def test_returns_location_header(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        user = _make_scim_user()
        mock_service.create_user.return_value = user
        res = await client.post("/scim/v2/Users", json=CREATE_PAYLOAD, headers=AUTH)
        assert f"/scim/v2/Users/{user.id}" in res.headers.get("location", "")


class TestGetUser:
    async def test_returns_200(self, client: AsyncClient, mock_service: AsyncMock):
        user = _make_scim_user()
        mock_service.get_user.return_value = user
        res = await client.get(f"/scim/v2/Users/{user.id}", headers=AUTH)
        assert res.status_code == 200

    async def test_returns_correct_user(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        user = _make_scim_user()
        mock_service.get_user.return_value = user
        res = await client.get(f"/scim/v2/Users/{user.id}", headers=AUTH)
        assert res.json()["id"] == user.id
        assert res.json()["userName"] == user.userName

    async def test_not_found_returns_404(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.get_user.side_effect = ScimUserNotFoundError()
        res = await client.get(f"/scim/v2/Users/{uuid4()}", headers=AUTH)
        assert res.status_code == 404

    async def test_not_found_returns_scim_error_schema(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.get_user.side_effect = ScimUserNotFoundError()
        res = await client.get(f"/scim/v2/Users/{uuid4()}", headers=AUTH)
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in res.json()["schemas"]


class TestListUsers:
    async def test_returns_200(self, client: AsyncClient, mock_service: AsyncMock):
        mock_service.list_users.return_value = ([], 0)
        res = await client.get("/scim/v2/Users", headers=AUTH)
        assert res.status_code == 200

    async def test_returns_list_response_schema(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.list_users.return_value = ([], 0)
        res = await client.get("/scim/v2/Users", headers=AUTH)
        assert (
            "urn:ietf:params:scim:api:messages:2.0:ListResponse"
            in res.json()["schemas"]
        )

    async def test_returns_total_results(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        users = [_make_scim_user(), _make_scim_user()]
        mock_service.list_users.return_value = (users, 2)
        res = await client.get("/scim/v2/Users", headers=AUTH)
        assert res.json()["totalResults"] == 2

    async def test_passes_filter_to_service(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.list_users.return_value = ([], 0)
        await client.get(
            '/scim/v2/Users?filter=userName eq "jane@example.com"', headers=AUTH
        )
        mock_service.list_users.assert_called_once_with(
            filter_str='userName eq "jane@example.com"',
            sort_by=None,
            sort_order=None,
            start_index=1,
            count=None,
        )

    async def test_passes_sort_to_service(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.list_users.return_value = ([], 0)
        await client.get(
            "/scim/v2/Users?sortBy=userName&sortOrder=descending", headers=AUTH
        )
        mock_service.list_users.assert_called_once_with(
            filter_str=None,
            sort_by="userName",
            sort_order="descending",
            start_index=1,
            count=None,
        )

    async def test_pagination_returns_startindex_and_itemsperpage(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        page = [_make_scim_user() for _ in range(2)]
        mock_service.list_users.return_value = (page, 5)
        res = await client.get("/scim/v2/Users?startIndex=1&count=2", headers=AUTH)
        body = res.json()
        assert body["startIndex"] == 1
        assert body["itemsPerPage"] == 2
        assert body["totalResults"] == 5
        assert len(body["Resources"]) == 2

    async def test_pagination_second_page(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        page = [_make_scim_user(f"user{i}@example.com") for i in range(2)]
        mock_service.list_users.return_value = (page, 5)
        res = await client.get("/scim/v2/Users?startIndex=3&count=2", headers=AUTH)
        body = res.json()
        assert body["startIndex"] == 3
        assert body["itemsPerPage"] == 2
        assert len(body["Resources"]) == 2

    async def test_default_pagination_returns_all(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        users = [_make_scim_user() for _ in range(3)]
        mock_service.list_users.return_value = (users, 3)
        res = await client.get("/scim/v2/Users", headers=AUTH)
        body = res.json()
        assert body["startIndex"] == 1
        assert body["totalResults"] == 3
        assert len(body["Resources"]) == 3


class TestReplaceUser:
    async def test_returns_200(self, client: AsyncClient, mock_service: AsyncMock):
        user = _make_scim_user()
        mock_service.replace_user.return_value = user
        res = await client.put(
            f"/scim/v2/Users/{user.id}", json=CREATE_PAYLOAD, headers=AUTH
        )
        assert res.status_code == 200

    async def test_returns_updated_user_body(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        user = _make_scim_user()
        mock_service.replace_user.return_value = user
        res = await client.put(
            f"/scim/v2/Users/{user.id}", json=CREATE_PAYLOAD, headers=AUTH
        )
        assert res.json()["id"] == user.id
        assert "urn:ietf:params:scim:schemas:core:2.0:User" in res.json()["schemas"]

    async def test_not_found_returns_404(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.replace_user.side_effect = ScimUserNotFoundError()
        res = await client.put(
            f"/scim/v2/Users/{uuid4()}", json=CREATE_PAYLOAD, headers=AUTH
        )
        assert res.status_code == 404

    async def test_not_found_returns_scim_error_schema(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.replace_user.side_effect = ScimUserNotFoundError()
        res = await client.put(
            f"/scim/v2/Users/{uuid4()}", json=CREATE_PAYLOAD, headers=AUTH
        )
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in res.json()["schemas"]

    async def test_conflict_returns_409(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.replace_user.side_effect = ScimUserConflictError("already exists")
        res = await client.put(
            f"/scim/v2/Users/{uuid4()}", json=CREATE_PAYLOAD, headers=AUTH
        )
        assert res.status_code == 409
        assert res.json()["scimType"] == "uniqueness"


class TestPatchUser:
    async def test_returns_200(self, client: AsyncClient, mock_service: AsyncMock):
        user = _make_scim_user()
        mock_service.patch_user.return_value = user
        payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "Replace", "path": "active", "value": False}],
        }
        res = await client.patch(
            f"/scim/v2/Users/{user.id}", json=payload, headers=AUTH
        )
        assert res.status_code == 200

    async def test_deactivate_user_returns_active_false(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        user = _make_scim_user()
        user.active = False
        mock_service.patch_user.return_value = user
        payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "Replace", "path": "active", "value": False}],
        }
        res = await client.patch(
            f"/scim/v2/Users/{user.id}", json=payload, headers=AUTH
        )
        assert res.json()["active"] is False

    async def test_deactivate_user_returns_state_inactive(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        user = _make_scim_user()
        user.active = False
        mock_service.patch_user.return_value = user
        payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "Replace", "path": "active", "value": False}],
        }
        res = await client.patch(
            f"/scim/v2/Users/{user.id}", json=payload, headers=AUTH
        )
        assert res.json()["active"] is False

    async def test_replace_username(self, client: AsyncClient, mock_service: AsyncMock):
        user = _make_scim_user("updated@example.com")
        mock_service.patch_user.return_value = user
        payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "Replace", "path": "userName", "value": "updated@example.com"}
            ],
        }
        res = await client.patch(
            f"/scim/v2/Users/{user.id}", json=payload, headers=AUTH
        )
        assert res.json()["userName"] == "updated@example.com"

    async def test_not_found_returns_404(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.patch_user.side_effect = ScimUserNotFoundError()
        payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "Replace", "path": "active", "value": False}],
        }
        res = await client.patch(
            f"/scim/v2/Users/{uuid4()}", json=payload, headers=AUTH
        )
        assert res.status_code == 404

    async def test_conflict_returns_409(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.patch_user.side_effect = ScimUserConflictError("already exists")
        payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "Replace", "path": "userName", "value": "taken@example.com"}
            ],
        }
        res = await client.patch(
            f"/scim/v2/Users/{uuid4()}", json=payload, headers=AUTH
        )
        assert res.status_code == 409
        assert res.json()["scimType"] == "uniqueness"


class TestDeleteUser:
    async def test_returns_204(self, client: AsyncClient, mock_service: AsyncMock):
        mock_service.delete_user.return_value = None
        res = await client.delete(f"/scim/v2/Users/{uuid4()}", headers=AUTH)
        assert res.status_code == 204

    async def test_not_found_returns_404(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.delete_user.side_effect = ScimUserNotFoundError()
        res = await client.delete(f"/scim/v2/Users/{uuid4()}", headers=AUTH)
        assert res.status_code == 404
