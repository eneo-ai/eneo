from unittest.mock import AsyncMock, patch
from uuid import uuid4

from httpx import AsyncClient

from eneo.scim.app import scim_app
from eneo.scim.deps import get_scim_group_service, get_scim_user_service
from tests.unittests.scim.conftest import TEST_BEARER_TOKEN

AUTH = {"Authorization": f"Bearer {TEST_BEARER_TOKEN}"}


def _make_scim_user(username: str = "jane@example.com"):
    from datetime import datetime, timezone

    from eneo.scim.schemas.user import ScimMeta, ScimUser

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

    from eneo.scim.schemas.group import ScimGroup
    from eneo.scim.schemas.user import ScimMeta

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
        with patch("eneo.scim.resources.bulk.ScimUserService") as _:
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
        from eneo.scim.domain.errors import ScimUserConflictError

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

    async def test_unhandled_exception_returns_generic_500_and_logs(
        self, client: AsyncClient, caplog
    ):
        """Anything that isn't ScimHttpError / ScimValidationError must NOT
        leak its raw `str(e)` into the response body. SQLAlchemy IntegrityError
        renders with constraint names, column names, the SQL statement, and
        bound parameter values — none of which belong in an HTTP response.
        Instead, log the exception (with traceback) and return a generic
        message, matching the non-bulk endpoint's behaviour."""
        import logging

        from eneo.scim.resources.bulk import logger as bulk_logger

        sentinel = (
            "duplicate key value violates unique constraint "
            '"idx_unique_active_user_email" DETAIL: Key (email)=(secret@x.com) '
            "already exists. [SQL: INSERT INTO users ...] "
            '[parameters: {"email": "secret@x.com"}]'
        )

        mock_svc = AsyncMock()
        mock_svc.create_user.side_effect = RuntimeError(sentinel)
        scim_app.dependency_overrides[get_scim_user_service] = lambda: mock_svc
        try:
            with caplog.at_level(logging.ERROR):
                bulk_logger.addHandler(caplog.handler)
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
                    bulk_logger.removeHandler(caplog.handler)
        finally:
            scim_app.dependency_overrides.pop(get_scim_user_service, None)

        ops = res.json()["Operations"]
        assert ops[0]["status"] == "500"
        body_str = str(ops[0]["response"])
        # Generic message — no leak of constraint name, column, SQL, params
        assert ops[0]["response"]["detail"] == "Internal server error"
        for leak in (
            "idx_unique_active_user_email",
            "secret@x.com",
            "INSERT INTO users",
            "parameters",
            "DETAIL:",
        ):
            assert leak not in body_str, f"Response leaked: {leak!r}"

        # The full exception detail must still be reachable for operators.
        leak_logged = any(
            "secret@x.com" in (r.getMessage() + str(getattr(r, "exc_info", "") or ""))
            or (r.exc_info and "secret@x.com" in str(r.exc_info[1]))
            for r in caplog.records
        )
        assert leak_logged, (
            f"Expected exception detail in logs. Got: "
            f"{[(r.levelname, r.message) for r in caplog.records]}"
        )

    async def test_validation_error_returns_400_in_operations(
        self, client: AsyncClient
    ):
        from eneo.scim.domain.errors import ScimValidationError

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
        from eneo.scim.domain.errors import ScimUserNotFoundError

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


class TestBulkLimits:
    async def test_exceeds_max_operations_returns_413(self, client: AsyncClient):
        # 101 operations is one over the advertised maxOperations (100).
        ops = [{"method": "DELETE", "path": f"/Users/{uuid4()}"} for _ in range(101)]
        res = await client.post(
            "/scim/v2/Bulk",
            json={"Operations": ops},
            headers=AUTH,
        )
        assert res.status_code == 413
        body = res.json()
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in body["schemas"]
        assert body["status"] == "413"
        assert body["scimType"] == "tooMany"

    async def test_at_max_operations_not_rejected(self, client: AsyncClient):
        # Exactly 100 operations must NOT trip the limit (guards off-by-one).
        ops = [{"method": "DELETE", "path": f"/Users/{uuid4()}"} for _ in range(100)]
        res = await client.post(
            "/scim/v2/Bulk",
            json={"Operations": ops},
            headers=AUTH,
        )
        assert res.status_code == 200

    async def test_exceeds_payload_size_returns_413(self, client: AsyncClient):
        # Patch the byte limit to a tiny value so any normal request body
        # exceeds it — avoids building a real >1 MiB payload in the test.
        with patch("eneo.scim.resources.bulk.SCIM_BULK_MAX_PAYLOAD_BYTES", 10):
            res = await client.post(
                "/scim/v2/Bulk",
                json={
                    "Operations": [{"method": "DELETE", "path": f"/Users/{uuid4()}"}]
                },
                headers=AUTH,
            )
        assert res.status_code == 413
        body = res.json()
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in body["schemas"]
        assert body["status"] == "413"


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

    async def test_bulkid_resolved_in_group_member_value(self, client: AsyncClient):
        """A bulkId reference inside Group.members[].value (not just the path)
        must be resolved to the created user's real id before it reaches the
        group service — otherwise UUID('bulkId:newuser') blows up with a 500."""
        user = _make_scim_user()
        group = _make_scim_group()
        user_svc = AsyncMock()
        user_svc.create_user.return_value = user
        group_svc = AsyncMock()
        group_svc.create_group.return_value = group
        scim_app.dependency_overrides[get_scim_user_service] = lambda: user_svc
        scim_app.dependency_overrides[get_scim_group_service] = lambda: group_svc
        try:
            res = await client.post(
                "/scim/v2/Bulk",
                json={
                    "Operations": [
                        {
                            "method": "POST",
                            "path": "/Users",
                            "bulkId": "newuser",
                            "data": {"userName": "jane@example.com"},
                        },
                        {
                            "method": "POST",
                            "path": "/Groups",
                            "bulkId": "newgroup",
                            "data": {
                                "displayName": "Engineering",
                                "members": [{"value": "bulkId:newuser"}],
                            },
                        },
                    ]
                },
                headers=AUTH,
            )
        finally:
            scim_app.dependency_overrides.pop(get_scim_user_service, None)
            scim_app.dependency_overrides.pop(get_scim_group_service, None)
        ops = res.json()["Operations"]
        assert ops[0]["status"] == "201"
        assert ops[1]["status"] == "201"
        group_svc.create_group.assert_called_once()
        created = group_svc.create_group.call_args.args[0]
        # bulkId:newuser resolved to the real user id, not passed through raw
        assert [m.value for m in created.members] == [user.id]
