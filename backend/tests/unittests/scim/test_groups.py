from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from eneo.scim.app import scim_app
from eneo.scim.auth import require_scim_auth
from eneo.scim.deps import get_scim_group_service
from eneo.scim.domain.errors import ScimGroupConflictError, ScimGroupNotFoundError
from eneo.scim.schemas.group import ScimGroup
from eneo.scim.schemas.user import ScimMeta
from eneo.scim.services.group_service import ScimGroupService
from eneo.server.main import app

TEST_TOKEN = "test-scim-token"
AUTH = {"Authorization": f"Bearer {TEST_TOKEN}"}


def _make_scim_group(display_name: str = "Engineering") -> ScimGroup:
    return ScimGroup(
        id=str(uuid4()),
        displayName=display_name,
        members=[],
        meta=ScimMeta(resourceType="Group"),
    )


@pytest.fixture
def mock_service() -> AsyncMock:
    return AsyncMock(spec=ScimGroupService)


@pytest.fixture
async def client(mock_service: AsyncMock) -> AsyncClient:
    scim_app.dependency_overrides[require_scim_auth] = lambda: None
    scim_app.dependency_overrides[get_scim_group_service] = lambda: mock_service
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    scim_app.dependency_overrides.clear()


CREATE_PAYLOAD = {
    "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
    "displayName": "Engineering",
}


class TestCreateGroup:
    async def test_returns_201(self, client: AsyncClient, mock_service: AsyncMock):
        mock_service.create_group.return_value = _make_scim_group()
        res = await client.post("/scim/v2/Groups", json=CREATE_PAYLOAD, headers=AUTH)
        assert res.status_code == 201

    async def test_returns_group_schema(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.create_group.return_value = _make_scim_group()
        res = await client.post("/scim/v2/Groups", json=CREATE_PAYLOAD, headers=AUTH)
        assert "urn:ietf:params:scim:schemas:core:2.0:Group" in res.json()["schemas"]

    async def test_returns_id(self, client: AsyncClient, mock_service: AsyncMock):
        mock_service.create_group.return_value = _make_scim_group()
        res = await client.post("/scim/v2/Groups", json=CREATE_PAYLOAD, headers=AUTH)
        assert res.json()["id"]

    async def test_returns_meta_resource_type(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.create_group.return_value = _make_scim_group()
        res = await client.post("/scim/v2/Groups", json=CREATE_PAYLOAD, headers=AUTH)
        assert res.json()["meta"]["resourceType"] == "Group"

    async def test_conflict_returns_409(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.create_group.side_effect = ScimGroupConflictError("already exists")
        res = await client.post("/scim/v2/Groups", json=CREATE_PAYLOAD, headers=AUTH)
        assert res.status_code == 409

    async def test_conflict_returns_scim_error_schema(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.create_group.side_effect = ScimGroupConflictError("already exists")
        res = await client.post("/scim/v2/Groups", json=CREATE_PAYLOAD, headers=AUTH)
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in res.json()["schemas"]

    async def test_conflict_returns_uniqueness_scim_type(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.create_group.side_effect = ScimGroupConflictError("already exists")
        res = await client.post("/scim/v2/Groups", json=CREATE_PAYLOAD, headers=AUTH)
        assert res.json()["scimType"] == "uniqueness"

    async def test_returns_location_header(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        group = _make_scim_group()
        mock_service.create_group.return_value = group
        res = await client.post("/scim/v2/Groups", json=CREATE_PAYLOAD, headers=AUTH)
        assert f"/scim/v2/Groups/{group.id}" in res.headers.get("location", "")


class TestGetGroup:
    async def test_returns_200(self, client: AsyncClient, mock_service: AsyncMock):
        group = _make_scim_group()
        mock_service.get_group.return_value = group
        res = await client.get(f"/scim/v2/Groups/{group.id}", headers=AUTH)
        assert res.status_code == 200

    async def test_returns_correct_group(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        group = _make_scim_group()
        mock_service.get_group.return_value = group
        res = await client.get(f"/scim/v2/Groups/{group.id}", headers=AUTH)
        assert res.json()["id"] == group.id
        assert res.json()["displayName"] == group.displayName

    async def test_not_found_returns_404(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.get_group.side_effect = ScimGroupNotFoundError()
        res = await client.get(f"/scim/v2/Groups/{uuid4()}", headers=AUTH)
        assert res.status_code == 404

    async def test_not_found_returns_scim_error_schema(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.get_group.side_effect = ScimGroupNotFoundError()
        res = await client.get(f"/scim/v2/Groups/{uuid4()}", headers=AUTH)
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in res.json()["schemas"]


class TestListGroups:
    async def test_returns_200(self, client: AsyncClient, mock_service: AsyncMock):
        mock_service.list_groups.return_value = ([], 0)
        res = await client.get("/scim/v2/Groups", headers=AUTH)
        assert res.status_code == 200

    async def test_returns_list_response_schema(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.list_groups.return_value = ([], 0)
        res = await client.get("/scim/v2/Groups", headers=AUTH)
        assert (
            "urn:ietf:params:scim:api:messages:2.0:ListResponse"
            in res.json()["schemas"]
        )

    async def test_returns_total_results(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        groups = [_make_scim_group(), _make_scim_group("Backend")]
        mock_service.list_groups.return_value = (groups, 2)
        res = await client.get("/scim/v2/Groups", headers=AUTH)
        assert res.json()["totalResults"] == 2

    async def test_passes_filter_to_service(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.list_groups.return_value = ([], 0)
        await client.get(
            '/scim/v2/Groups?filter=displayName eq "Engineering"', headers=AUTH
        )
        mock_service.list_groups.assert_called_once_with(
            filter_str='displayName eq "Engineering"',
            sort_by=None,
            sort_order=None,
            start_index=1,
            count=None,
        )

    async def test_passes_sort_to_service(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.list_groups.return_value = ([], 0)
        await client.get(
            "/scim/v2/Groups?sortBy=displayName&sortOrder=ascending", headers=AUTH
        )
        mock_service.list_groups.assert_called_once_with(
            filter_str=None,
            sort_by="displayName",
            sort_order="ascending",
            start_index=1,
            count=None,
        )

    async def test_pagination_returns_startindex_and_itemsperpage(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        page = [_make_scim_group(f"G{i}") for i in range(2)]
        mock_service.list_groups.return_value = (page, 5)
        res = await client.get("/scim/v2/Groups?startIndex=1&count=2", headers=AUTH)
        body = res.json()
        assert body["startIndex"] == 1
        assert body["itemsPerPage"] == 2
        assert body["totalResults"] == 5
        assert len(body["Resources"]) == 2

    async def test_pagination_second_page(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        page = [_make_scim_group(f"G{i}") for i in range(2)]
        mock_service.list_groups.return_value = (page, 5)
        res = await client.get("/scim/v2/Groups?startIndex=3&count=2", headers=AUTH)
        body = res.json()
        assert body["startIndex"] == 3
        assert body["itemsPerPage"] == 2
        assert len(body["Resources"]) == 2


class TestReplaceGroup:
    async def test_returns_200(self, client: AsyncClient, mock_service: AsyncMock):
        group = _make_scim_group()
        mock_service.replace_group.return_value = group
        res = await client.put(
            f"/scim/v2/Groups/{group.id}", json=CREATE_PAYLOAD, headers=AUTH
        )
        assert res.status_code == 200

    async def test_returns_updated_group_body(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        group = _make_scim_group()
        mock_service.replace_group.return_value = group
        res = await client.put(
            f"/scim/v2/Groups/{group.id}", json=CREATE_PAYLOAD, headers=AUTH
        )
        assert res.json()["id"] == group.id
        assert "urn:ietf:params:scim:schemas:core:2.0:Group" in res.json()["schemas"]

    async def test_not_found_returns_404(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.replace_group.side_effect = ScimGroupNotFoundError()
        res = await client.put(
            f"/scim/v2/Groups/{uuid4()}", json=CREATE_PAYLOAD, headers=AUTH
        )
        assert res.status_code == 404

    async def test_not_found_returns_scim_error_schema(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.replace_group.side_effect = ScimGroupNotFoundError()
        res = await client.put(
            f"/scim/v2/Groups/{uuid4()}", json=CREATE_PAYLOAD, headers=AUTH
        )
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in res.json()["schemas"]

    async def test_conflict_returns_409(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.replace_group.side_effect = ScimGroupConflictError(
            "already exists"
        )
        res = await client.put(
            f"/scim/v2/Groups/{uuid4()}", json=CREATE_PAYLOAD, headers=AUTH
        )
        assert res.status_code == 409
        assert res.json()["scimType"] == "uniqueness"


class TestPatchGroup:
    async def test_add_member_returns_200(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        group = _make_scim_group()
        mock_service.patch_group.return_value = group
        payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "Add", "path": "members", "value": [{"value": str(uuid4())}]}
            ],
        }
        res = await client.patch(
            f"/scim/v2/Groups/{group.id}", json=payload, headers=AUTH
        )
        assert res.status_code == 200

    async def test_remove_member_returns_200(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        group = _make_scim_group()
        mock_service.patch_group.return_value = group
        uid = uuid4()
        payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "Remove", "path": f'members[value eq "{uid}"]'}],
        }
        res = await client.patch(
            f"/scim/v2/Groups/{group.id}", json=payload, headers=AUTH
        )
        assert res.status_code == 200

    async def test_replace_displayname_returns_200(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        group = _make_scim_group("Renamed")
        mock_service.patch_group.return_value = group
        payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "Replace", "path": "displayName", "value": "Renamed"}
            ],
        }
        res = await client.patch(
            f"/scim/v2/Groups/{group.id}", json=payload, headers=AUTH
        )
        assert res.status_code == 200
        assert res.json()["displayName"] == "Renamed"

    async def test_not_found_returns_404(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.patch_group.side_effect = ScimGroupNotFoundError()
        payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "Add", "path": "members", "value": [{"value": str(uuid4())}]}
            ],
        }
        res = await client.patch(
            f"/scim/v2/Groups/{uuid4()}", json=payload, headers=AUTH
        )
        assert res.status_code == 404

    async def test_conflict_returns_409(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.patch_group.side_effect = ScimGroupConflictError("already exists")
        payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "Replace", "path": "displayName", "value": "Taken"}],
        }
        res = await client.patch(
            f"/scim/v2/Groups/{uuid4()}", json=payload, headers=AUTH
        )
        assert res.status_code == 409
        assert res.json()["scimType"] == "uniqueness"


class TestDeleteGroup:
    async def test_returns_204(self, client: AsyncClient, mock_service: AsyncMock):
        mock_service.delete_group.return_value = None
        res = await client.delete(f"/scim/v2/Groups/{uuid4()}", headers=AUTH)
        assert res.status_code == 204

    async def test_not_found_returns_404(
        self, client: AsyncClient, mock_service: AsyncMock
    ):
        mock_service.delete_group.side_effect = ScimGroupNotFoundError()
        res = await client.delete(f"/scim/v2/Groups/{uuid4()}", headers=AUTH)
        assert res.status_code == 404
