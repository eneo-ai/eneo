from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.authentication.auth_models import (
    ApiKeyOwnership,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyState,
    ApiKeyType,
    ApiKeyV2InDB,
)
from eneo.database.tables.ai_models_table import CompletionModels, EmbeddingModels
from eneo.database.tables.app_table import Apps
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.spaces_table import SpacesUserGroups, SpacesUsers
from eneo.database.tables.user_groups_table import UserGroups
from eneo.database.tables.users_table import Users
from eneo.database.tables.websites_table import CrawlRuns, Websites
from eneo.main.exceptions import UnauthorizedException
from eneo.users.user import UserGroupInDBRead
from eneo.websites.domain.crawl_run import CrawlType

pytestmark = pytest.mark.integration


@pytest.fixture
async def website_id(db_container, admin_user, space_factory) -> UUID:
    async with db_container(user=admin_user) as container:
        session = container.session()
        space = await space_factory(session, f"Latest crawl {uuid4()}")
        session.add(
            SpacesUsers(space_id=space.id, user_id=admin_user.id, role="editor")
        )
        model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
        website = Websites(
            name="Municipal website",
            url="https://example.test",
            size=0,
            download_files=False,
            crawl_type=CrawlType.CRAWL,
            update_interval="never",
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            space_id=space.id,
            embedding_model_id=model_id,
        )
        session.add(website)
        await session.flush()
        return website.id


@pytest.fixture
async def headers(db_container, admin_user, patch_auth_service_jwt):
    async with db_container(user=admin_user) as container:
        token = container.auth_service().create_access_token_for_user(admin_user)
    return {"Authorization": f"Bearer {token}"}


async def test_latest_crawl_returns_null_then_one_deterministic_run_without_space_hydration(
    client, db_container, admin_user, website_id, headers, monkeypatch
) -> None:
    from eneo.spaces.space_repo import SpaceRepository

    async def forbid_aggregate(*args, **kwargs):
        pytest.fail("Polling must not hydrate the space aggregate")

    monkeypatch.setattr(SpaceRepository, "_get_from_query", forbid_aggregate)
    url = f"/api/v1/websites/{website_id}/runs/latest/"
    response = await client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() is None

    async with db_container(user=admin_user) as container:
        # Equal timestamps exercise the stable ID tie-breaker with a long history.
        now = datetime.now(timezone.utc)
        run_ids = sorted(uuid4() for _ in range(1000))
        await container.session().execute(
            sa.insert(CrawlRuns),
            [
                dict(
                    id=run_id,
                    website_id=website_id,
                    tenant_id=admin_user.tenant_id,
                    created_at=now,
                    phase="terminal",
                    outcome="succeeded",
                    origin="scheduled",
                    finished_at=now,
                    pages_crawled=position,
                )
                for position, run_id in enumerate(run_ids)
            ],
        )

    response = await client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(run_ids[-1])
    assert response.json()["pages_crawled"] == 999
    assert response.json()["phase"] == "terminal"


async def test_latest_crawl_loads_only_the_callers_access_facts_in_a_large_space(
    client, db_container, admin_user, website_id, headers, monkeypatch
) -> None:
    from eneo.spaces.space_repo import SpaceRepository

    async with db_container(user=admin_user) as container:
        session = container.session()
        space_id = await session.scalar(
            sa.select(Websites.space_id).where(Websites.id == website_id)
        )
        user_ids = [uuid4() for _ in range(128)]
        group_ids = [uuid4() for _ in range(128)]
        await session.execute(
            sa.insert(Users),
            [
                dict(
                    id=id,
                    email=f"{id}@example.test",
                    tenant_id=admin_user.tenant_id,
                    state="active",
                )
                for id in user_ids
            ],
        )
        await session.execute(
            sa.insert(SpacesUsers),
            [dict(space_id=space_id, user_id=id, role="admin") for id in user_ids],
        )
        await session.execute(
            sa.insert(UserGroups),
            [
                dict(id=id, name=str(id), tenant_id=admin_user.tenant_id)
                for id in group_ids
            ],
        )
        await session.execute(
            sa.insert(SpacesUserGroups),
            [
                dict(space_id=space_id, user_group_id=id, role="admin")
                for id in group_ids
            ],
        )
        await session.execute(
            sa.insert(Assistants),
            [
                dict(
                    name=str(id),
                    space_id=space_id,
                    user_id=admin_user.id,
                    logging_enabled=False,
                    is_default=False,
                    published=False,
                )
                for id in user_ids
            ],
        )
        await session.execute(
            sa.insert(Apps),
            [
                dict(
                    name=str(id),
                    space_id=space_id,
                    user_id=admin_user.id,
                    tenant_id=admin_user.tenant_id,
                    published=False,
                )
                for id in user_ids
            ],
        )

    observed = []
    original = SpaceRepository.get_website_access_facts

    async def observe_access_facts(self, website_id):
        facts = await original(self, website_id)
        observed.append(facts)
        return facts

    monkeypatch.setattr(
        SpaceRepository, "get_website_access_facts", observe_access_facts
    )
    response = await client.get(
        f"/api/v1/websites/{website_id}/runs/latest/", headers=headers
    )
    assert response.status_code == 200, response.text
    assert len(observed) == 1
    facts = observed[0]
    assert set(facts.members) == {admin_user.id}
    assert not facts.group_members
    assert not facts.assistant_ids
    assert not facts.app_ids


async def test_latest_crawl_denies_nonmembers_and_hides_unknown_websites(
    client, db_container, admin_user, website_id, headers
) -> None:
    async with db_container(user=admin_user) as container:
        space_id = await container.session().scalar(
            sa.select(Websites.space_id).where(Websites.id == website_id)
        )
        await container.session().execute(
            sa.delete(SpacesUsers).where(SpacesUsers.space_id == space_id)
        )
    response = await client.get(
        f"/api/v1/websites/{website_id}/runs/latest/", headers=headers
    )
    assert response.status_code == 403, response.text
    response = await client.get(
        f"/api/v1/websites/{uuid4()}/runs/latest/", headers=headers
    )
    assert response.status_code == 404, response.text


async def test_latest_crawl_rejects_a_different_tenant_before_reading_runs(
    db_container, admin_user, website_id
) -> None:
    from eneo.main.exceptions import NotFoundException

    foreign_user = admin_user.model_copy(update={"tenant_id": uuid4()})
    async with db_container(user=foreign_user) as container:
        with pytest.raises(NotFoundException):
            await container.website_crud_service().get_latest_crawl_run(website_id)


@pytest.mark.parametrize(
    "role, expected", [("viewer", 403), ("editor", 200), ("admin", 200)]
)
async def test_latest_crawl_preserves_existing_space_role_permissions(
    client, db_container, admin_user, website_id, headers, role, expected
) -> None:
    async with db_container(user=admin_user) as container:
        space_id = await container.session().scalar(
            sa.select(Websites.space_id).where(Websites.id == website_id)
        )
        await container.session().execute(
            sa.update(SpacesUsers)
            .where(SpacesUsers.space_id == space_id)
            .values(role=role)
        )
    for suffix in ("runs/", "runs/latest/"):
        response = await client.get(
            f"/api/v1/websites/{website_id}/{suffix}", headers=headers
        )
        assert response.status_code == expected, response.text


@pytest.mark.parametrize("deleted", [False, True])
async def test_latest_crawl_preserves_group_membership_and_ignores_deleted_groups(
    db_container, admin_user, website_id, deleted
) -> None:
    async with db_container(user=admin_user) as container:
        session = container.session()
        space_id = await session.scalar(
            sa.select(Websites.space_id).where(Websites.id == website_id)
        )
        await session.execute(
            sa.delete(SpacesUsers).where(SpacesUsers.space_id == space_id)
        )
        group = UserGroups(
            name=f"Crawler editors {uuid4()}",
            tenant_id=admin_user.tenant_id,
            state="deleted" if deleted else None,
        )
        session.add(group)
        await session.flush()
        session.add(
            SpacesUserGroups(space_id=space_id, user_group_id=group.id, role="editor")
        )
        user = admin_user.model_copy(
            update={"user_groups": [UserGroupInDBRead.model_validate(group)]}
        )

    async with db_container(user=user) as container:
        service = container.website_crud_service()
        if deleted:
            with pytest.raises(UnauthorizedException):
                await service.get_latest_crawl_run(website_id)
            with pytest.raises(UnauthorizedException):
                await service.get_crawl_runs(website_id)
        else:
            assert await service.get_latest_crawl_run(website_id) is None
            assert await service.get_crawl_runs(website_id) == []


@pytest.mark.parametrize("ownership", list(ApiKeyOwnership))
@pytest.mark.parametrize("resource", ["assistant", "app", "default_assistant"])
@pytest.mark.parametrize("same_space", [True, False])
async def test_latest_crawl_preserves_resource_scoped_key_access(
    db_container,
    admin_user,
    website_id,
    space_factory,
    assistant_factory,
    app_factory,
    ownership,
    resource,
    same_space,
) -> None:
    async with db_container(user=admin_user) as container:
        session = container.session()
        space_id = await session.scalar(
            sa.select(Websites.space_id).where(Websites.id == website_id)
        )
        if not same_space:
            other_space = await space_factory(session, f"Other space {uuid4()}")
            space_id = other_space.id
        model_id = await session.scalar(sa.select(CompletionModels.id).limit(1))
        if resource == "app":
            target = await app_factory(
                session, "Scoped app", model_id, space_id=space_id
            )
        else:
            target = await assistant_factory(
                session,
                "Scoped assistant",
                model_id,
                space_id=space_id,
                is_default=resource == "default_assistant",
            )
        key = ApiKeyV2InDB(
            id=uuid4(),
            tenant_id=admin_user.tenant_id,
            ownership=ownership,
            owner_user_id=admin_user.id if ownership == ApiKeyOwnership.USER else None,
            name="Crawler access test",
            key_prefix="sk_test",
            key_suffix="test",
            key_type=ApiKeyType.SK,
            permission=ApiKeyPermission.WRITE,
            scope_type=ApiKeyScopeType.APP
            if resource == "app"
            else ApiKeyScopeType.ASSISTANT,
            scope_id=target.id,
            state=ApiKeyState.ACTIVE,
            key_hash="test-only",
            hash_version="hmac_sha256",
        )
    user = admin_user.model_copy(update={"active_api_key": key})
    async with db_container(user=user) as container:
        service = container.website_crud_service()
        # Preserve the full aggregate's policy, including default-assistant exclusion.
        if same_space and resource != "default_assistant":
            assert await service.get_latest_crawl_run(website_id) is None
            assert await service.get_crawl_runs(website_id) == []
        else:
            with pytest.raises(UnauthorizedException):
                await service.get_latest_crawl_run(website_id)
            with pytest.raises(UnauthorizedException):
                await service.get_crawl_runs(website_id)
