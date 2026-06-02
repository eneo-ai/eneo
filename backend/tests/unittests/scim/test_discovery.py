from httpx import AsyncClient


class TestServiceProviderConfig:
    async def test_rejects_missing_token(self, client: AsyncClient):
        res = await client.get("/scim/v2/ServiceProviderConfig")
        assert res.status_code == 401

    async def test_rejects_wrong_token(self, client: AsyncClient):
        res = await client.get(
            "/scim/v2/ServiceProviderConfig",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert res.status_code == 401

    async def test_returns_200(self, client: AsyncClient, auth_headers):
        res = await client.get("/scim/v2/ServiceProviderConfig", headers=auth_headers)
        assert res.status_code == 200

    async def test_returns_correct_schema(self, client: AsyncClient, auth_headers):
        res = await client.get("/scim/v2/ServiceProviderConfig", headers=auth_headers)
        body = res.json()
        assert (
            "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
            in body["schemas"]
        )

    async def test_declares_patch_support(self, client: AsyncClient, auth_headers):
        res = await client.get("/scim/v2/ServiceProviderConfig", headers=auth_headers)
        assert res.json()["patch"]["supported"] is True

    async def test_declares_filter_support(self, client: AsyncClient, auth_headers):
        res = await client.get("/scim/v2/ServiceProviderConfig", headers=auth_headers)
        assert res.json()["filter"]["supported"] is True

    async def test_filter_max_results_matches_enforced_cap(
        self, client: AsyncClient, auth_headers
    ):
        """The advertised filter.maxResults must equal the value the list
        endpoints actually enforce (clamp_count), or the contract lies."""
        from intric.scim.constants import SCIM_FILTER_MAX_RESULTS

        res = await client.get("/scim/v2/ServiceProviderConfig", headers=auth_headers)
        assert res.json()["filter"]["maxResults"] == SCIM_FILTER_MAX_RESULTS

    async def test_declares_sort_support(self, client: AsyncClient, auth_headers):
        res = await client.get("/scim/v2/ServiceProviderConfig", headers=auth_headers)
        assert res.json()["sort"]["supported"] is True

    async def test_declares_bulk_support(self, client: AsyncClient, auth_headers):
        res = await client.get("/scim/v2/ServiceProviderConfig", headers=auth_headers)
        assert res.json()["bulk"]["supported"] is True

    async def test_bulk_declares_max_operations(
        self, client: AsyncClient, auth_headers
    ):
        res = await client.get("/scim/v2/ServiceProviderConfig", headers=auth_headers)
        assert res.json()["bulk"]["maxOperations"] > 0


class TestSchemas:
    async def test_returns_200(self, client: AsyncClient, auth_headers):
        res = await client.get("/scim/v2/Schemas", headers=auth_headers)
        assert res.status_code == 200

    async def test_returns_list_response_schema(
        self, client: AsyncClient, auth_headers
    ):
        res = await client.get("/scim/v2/Schemas", headers=auth_headers)
        body = res.json()
        assert "urn:ietf:params:scim:api:messages:2.0:ListResponse" in body["schemas"]

    async def test_includes_user_schema(self, client: AsyncClient, auth_headers):
        res = await client.get("/scim/v2/Schemas", headers=auth_headers)
        ids = [r["id"] for r in res.json()["Resources"]]
        assert "urn:ietf:params:scim:schemas:core:2.0:User" in ids

    async def test_includes_group_schema(self, client: AsyncClient, auth_headers):
        res = await client.get("/scim/v2/Schemas", headers=auth_headers)
        ids = [r["id"] for r in res.json()["Resources"]]
        assert "urn:ietf:params:scim:schemas:core:2.0:Group" in ids

    async def test_user_schema_has_required_attributes(
        self, client: AsyncClient, auth_headers
    ):
        res = await client.get("/scim/v2/Schemas", headers=auth_headers)
        user = next(r for r in res.json()["Resources"] if r["id"].endswith(":User"))
        attr_names = {a["name"] for a in user["attributes"]}
        assert {"userName", "emails", "active", "externalId"}.issubset(attr_names)

    async def test_user_schema_username_is_required(
        self, client: AsyncClient, auth_headers
    ):
        res = await client.get("/scim/v2/Schemas", headers=auth_headers)
        user = next(r for r in res.json()["Resources"] if r["id"].endswith(":User"))
        username_attr = next(a for a in user["attributes"] if a["name"] == "userName")
        assert username_attr["required"] is True

    async def test_user_schema_emails_has_subattributes(
        self, client: AsyncClient, auth_headers
    ):
        res = await client.get("/scim/v2/Schemas", headers=auth_headers)
        user = next(r for r in res.json()["Resources"] if r["id"].endswith(":User"))
        emails_attr = next(a for a in user["attributes"] if a["name"] == "emails")
        sub_names = {s["name"] for s in emails_attr["subAttributes"]}
        assert {"value", "primary", "type"}.issubset(sub_names)

    async def test_group_schema_has_required_attributes(
        self, client: AsyncClient, auth_headers
    ):
        res = await client.get("/scim/v2/Schemas", headers=auth_headers)
        group = next(r for r in res.json()["Resources"] if r["id"].endswith(":Group"))
        attr_names = {a["name"] for a in group["attributes"]}
        assert {"displayName", "members", "externalId"}.issubset(attr_names)

    async def test_group_schema_members_has_subattributes(
        self, client: AsyncClient, auth_headers
    ):
        res = await client.get("/scim/v2/Schemas", headers=auth_headers)
        group = next(r for r in res.json()["Resources"] if r["id"].endswith(":Group"))
        members_attr = next(a for a in group["attributes"] if a["name"] == "members")
        sub_names = {s["name"] for s in members_attr["subAttributes"]}
        assert {"value", "display"}.issubset(sub_names)


class TestResourceTypes:
    async def test_returns_200(self, client: AsyncClient, auth_headers):
        res = await client.get("/scim/v2/ResourceTypes", headers=auth_headers)
        assert res.status_code == 200

    async def test_returns_list_response_schema(
        self, client: AsyncClient, auth_headers
    ):
        res = await client.get("/scim/v2/ResourceTypes", headers=auth_headers)
        body = res.json()
        assert "urn:ietf:params:scim:api:messages:2.0:ListResponse" in body["schemas"]

    async def test_includes_user_resource_type(self, client: AsyncClient, auth_headers):
        res = await client.get("/scim/v2/ResourceTypes", headers=auth_headers)
        names = [r["name"] for r in res.json()["Resources"]]
        assert "User" in names

    async def test_includes_group_resource_type(
        self, client: AsyncClient, auth_headers
    ):
        res = await client.get("/scim/v2/ResourceTypes", headers=auth_headers)
        names = [r["name"] for r in res.json()["Resources"]]
        assert "Group" in names
