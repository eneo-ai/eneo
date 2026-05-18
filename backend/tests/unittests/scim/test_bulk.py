from unittest.mock import AsyncMock, patch
from uuid import uuid4

from httpx import AsyncClient

from intric.scim.app import scim_app
from intric.scim.deps import get_scim_group_service, get_scim_user_service
from tests.unittests.scim.conftest import TEST_BEARER_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_BEARER_TOKEN}"}


def _make_scim_user(username: str = "jane@example.com"):
    from datetime import datetime, timezone

    from intric.scim.schemas.user import ScimMeta, ScimUser

    uid = str(uuid4())
    return ScimUser(
        id=uid,
        userName=username,
        active=True,
        meta=ScimMeta(
            resourceType="User",
            created=datetime.now(timezone.utc),
            lastModified=datetime.now(timezone.utc),
        ),
    )


def _make_scim_group(name: str = "Engineering"):
    from datetime import datetime, timezone

    from intric.scim.schemas.group import ScimGroup
    from intric.scim.schemas.user import ScimMeta

    gid = str(uuid4())
    return ScimGroup(
        id=gid,
        displayName=name,
        meta=ScimMeta(
            resourceType="Group",
            created=datetime.now(timezone.utc),
            lastModified=datetime.now(timezone.utc),
        ),
    )


class TestBulkBasics:
    async def test_rejects_missing_token(self, client: AsyncClient):
        res = await client.post(
            "/scim/v2/Bulk",
            json={
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:BulkRequest"],
                "Operations": [],
            },
        )
        assert res.status_code == 401

    async def test_returns_200(self, client: AsyncClient):
        with patch("intric.scim.resources.bulk.ScimUserService") as _:
            res = await client.post(
                "/scim/v2/Bulk",
                json={
                    "schemas": ["urn:ietf:params:scim:api:messages:2.0:BulkRequest"],
                    "Operations": [],
                },
                headers=AUTH,
            )
        assert res.status_code == 200

    async def test_returns_bulk_response_schema(self, client: AsyncClient):
        res = await client.post(
            "/scim/v2/Bulk",
            json={
                "schemas": ["urn:ietf:params:scim:api:messages:2.0:BulkRequest"],
                "Operations": [],
            },
            headers=AUTH,
        )
        assert (
            "urn:ietf:params:scim:api:messages:2.0:BulkResponse"
            in res.json()["schemas"]
        )

    async def test_invalid_path_returns_400_in_operations(self, client: AsyncClient):
        res = await client.post(
            "/scim/v2/Bulk",
            json={
                "Operations": [{"method": "DELETE", "path": "/InvalidResource/123"}],
            },
            headers=AUTH,
        )
        assert res.status_code == 200
        op = res.json()["Operations"][0]
        assert op["status"] == "400"


class TestBulkCreate:
    async def test_post_user_returns_201(self, client: AsyncClient):
        user = _make_scim_user()
        mock_svc = AsyncMock()
        mock_svc.create_user.return_value = user
        scim_app.dependency_overrides[get_scim_user_service] = lambda: mock_svc
        try:
            res = await client.post(
                "/scim/v2/Bulk",
                json={
                    "Operations": [
                        {
                            "method": "POST",
                            "path": "/Users",
                            "bulkId": "abc",
                            "data": {
                                "userName": "jane@example.com",
                                "schemas": [
                                    "urn:ietf:params:scim:schemas:core:2.0:User"
                                ],
                            },
                        }
                    ]
                },
                headers=AUTH,
            )
        finally:
            scim_app.dependency_overrides.pop(get_scim_user_service, None)
        ops = res.json()["Operations"]
        assert ops[0]["status"] == "201"
        assert ops[0]["bulkId"] == "abc"
        assert "/scim/v2/Users/" in ops[0]["location"]

    async def test_post_group_returns_201(self, client: AsyncClient):
        group = _make_scim_group()
        mock_svc = AsyncMock()
        mock_svc.create_group.return_value = group
        scim_app.dependency_overrides[get_scim_group_service] = lambda: mock_svc
        try:
            res = await client.post(
                "/scim/v2/Bulk",
                json={
                    "Operations": [
                        {
                            "method": "POST",
                            "path": "/Groups",
                            "bulkId": "grp1",
                            "data": {
                                "displayName": "Engineering",
                                "schemas": [
                                    "urn:ietf:params:scim:schemas:core:2.0:Group"
                                ],
                            },
                        }
                    ]
                },
                headers=AUTH,
            )
        finally:
            scim_app.dependency_overrides.pop(get_scim_group_service, None)
        ops = res.json()["Operations"]
        assert ops[0]["status"] == "201"
        assert ops[0]["bulkId"] == "grp1"

    async def test_conflict_returns_409_in_operations(self, client: AsyncClient):
        from intric.scim.domain.errors import ScimUserConflictError

        mock_svc = AsyncMock()
        mock_svc.create_user.side_effect = ScimUserConflictError("already exists")
        scim_app.dependency_overrides[get_scim_user_service] = lambda: mock_svc
        try:
            res = await client.post(
                "/scim/v2/Bulk",
                json={
                    "Operations": [
                        {
                            "method": "POST",
                            "path": "/Users",
                            "data": {
                                "userName": "jane@example.com",
                                "schemas": [
                                    "urn:ietf:params:scim:schemas:core:2.0:User"
                                ],
                            },
                        }
                    ]
                },
                headers=AUTH,
            )
        finally:
            scim_app.dependency_overrides.pop(get_scim_user_service, None)
        ops = res.json()["Operations"]
        assert ops[0]["status"] == "409"
        assert ops[0]["response"]["scimType"] == "uniqueness"

    async def test_validation_error_returns_400_in_operations(
        self, client: AsyncClient
    ):
        from intric.scim.domain.errors import ScimValidationError

        mock_svc = AsyncMock()
        mock_svc.create_group.side_effect = ScimValidationError(
            "Group members must belong to the authenticated tenant"
        )
        scim_app.dependency_overrides[get_scim_group_service] = lambda: mock_svc
        try:
            res = await client.post(
                "/scim/v2/Bulk",
                json={
                    "Operations": [
                        {
                            "method": "POST",
                            "path": "/Groups",
                            "data": {
                                "displayName": "Engineering",
                                "schemas": [
                                    "urn:ietf:params:scim:schemas:core:2.0:Group"
                                ],
                            },
                        }
                    ]
                },
                headers=AUTH,
            )
        finally:
            scim_app.dependency_overrides.pop(get_scim_group_service, None)

        ops = res.json()["Operations"]
        assert ops[0]["status"] == "400"
        assert ops[0]["response"]["scimType"] == "invalidValue"


class TestBulkFailOnErrors:
    async def test_stops_after_fail_on_errors(self, client: AsyncClient):
        from intric.scim.domain.errors import ScimUserNotFoundError

        mock_svc = AsyncMock()
        mock_svc.delete_user.side_effect = ScimUserNotFoundError("not found")
        scim_app.dependency_overrides[get_scim_user_service] = lambda: mock_svc
        uid1, uid2, uid3 = str(uuid4()), str(uuid4()), str(uuid4())
        try:
            res = await client.post(
                "/scim/v2/Bulk",
                json={
                    "failOnErrors": 1,
                    "Operations": [
                        {"method": "DELETE", "path": f"/Users/{uid1}"},
                        {"method": "DELETE", "path": f"/Users/{uid2}"},
                        {"method": "DELETE", "path": f"/Users/{uid3}"},
                    ],
                },
                headers=AUTH,
            )
        finally:
            scim_app.dependency_overrides.pop(get_scim_user_service, None)
        ops = res.json()["Operations"]
        assert len(ops) == 1
        assert ops[0]["status"] == "404"


class TestBulkIdReference:
    async def test_bulkid_resolved_in_subsequent_operation(self, client: AsyncClient):
        user = _make_scim_user()
        mock_svc = AsyncMock()
        mock_svc.create_user.return_value = user
        mock_svc.delete_user.return_value = None
        scim_app.dependency_overrides[get_scim_user_service] = lambda: mock_svc
        try:
            res = await client.post(
                "/scim/v2/Bulk",
                json={
                    "Operations": [
                        {
                            "method": "POST",
                            "path": "/Users",
                            "bulkId": "newuser",
                            "data": {
                                "userName": "jane@example.com",
                                "schemas": [
                                    "urn:ietf:params:scim:schemas:core:2.0:User"
                                ],
                            },
                        },
                        {
                            "method": "DELETE",
                            "path": "/Users/bulkId:newuser",
                        },
                    ]
                },
                headers=AUTH,
            )
        finally:
            scim_app.dependency_overrides.pop(get_scim_user_service, None)
        ops = res.json()["Operations"]
        assert ops[0]["status"] == "201"
        assert ops[1]["status"] == "204"
        mock_svc.delete_user.assert_called_once()
