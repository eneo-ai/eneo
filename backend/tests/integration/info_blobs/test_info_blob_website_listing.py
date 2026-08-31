from hashlib import sha256
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from eneo.database.tables.spaces_table import SpacesUsers
from eneo.database.tables.websites_table import Websites
from eneo.websites.domain.crawl_run import CrawlType

pytestmark = pytest.mark.integration

_ACTIVE_WEBSITE_CURSOR_INDEX = "ix_info_blobs_active_website_cursor"
_WEBSITE_INDEX = "ix_info_blobs_website_id"


def _plan_index_names(plan: dict[str, object]) -> set[str]:
    pending = [plan]
    index_names: set[str] = set()
    while pending:
        node = pending.pop()
        if index_name := node.get("Index Name"):
            assert isinstance(index_name, str)
            index_names.add(index_name)
        child_plans = node.get("Plans", [])
        assert isinstance(child_plans, list)
        pending.extend(child_plans)
    return index_names


@pytest.fixture
async def admin_token(db_container, patch_auth_service_jwt, admin_user) -> str:
    async with db_container(user=admin_user) as container:
        return container.auth_service().create_access_token_for_user(admin_user)


async def test_website_listing_loads_the_source_without_async_lazy_io(
    db_container,
) -> None:
    async with db_container() as container:
        session = container.session()
        user = container.user()
        embedding_model_id = await session.scalar(
            sa.select(EmbeddingModels.id).limit(1)
        )
        assert embedding_model_id is not None

        website = Websites(
            name="Municipal website",
            url="https://municipality.example",
            download_files=False,
            crawl_type=CrawlType.CRAWL,
            update_interval="never",
            size=0,
            tenant_id=user.tenant_id,
            user_id=user.id,
            embedding_model_id=embedding_model_id,
        )
        session.add(website)
        await session.flush()

        text = "Indexed municipal information"
        blob = InfoBlobs(
            title="Information",
            url="https://municipality.example/information",
            text=text,
            size=len(text.encode()),
            content_hash=sha256(text.encode()).digest(),
            source_id=uuid4(),
            version_state=InfoBlobVersionState.ACTIVE.value,
            user_id=user.id,
            tenant_id=user.tenant_id,
            website_id=website.id,
            embedding_model_id=embedding_model_id,
        )
        session.add(blob)
        await session.flush()
        website_id = website.id
        blob_id = blob.id

    async with db_container() as container:
        page = await container.info_blob_repo().get_by_website(
            website_id,
            limit=100,
        )

        assert [item.id for item in page.items] == [blob_id]
        assert page.total_count == 1
        assert page.next_cursor is None
        assert not hasattr(page.items[0], "text")
        assert page.items[0].website is not None
        assert page.items[0].website.id == website_id


async def test_website_info_blob_endpoint_uses_a_stable_bounded_cursor_page(
    client,
    db_container,
    admin_user,
    admin_token: str,
    space_factory,
) -> None:
    blob_ids = [UUID(int=value) for value in (101, 102, 103)]
    async with db_container(user=admin_user) as container:
        session = container.session()
        embedding_model_id = await session.scalar(
            sa.select(EmbeddingModels.id).limit(1)
        )
        assert embedding_model_id is not None
        space = await space_factory(session, f"Website listing {uuid4()}")
        session.add(SpacesUsers(space_id=space.id, user_id=admin_user.id, role="admin"))
        website = Websites(
            name="Municipal website",
            url="https://municipality.example",
            download_files=False,
            crawl_type=CrawlType.CRAWL,
            update_interval="never",
            size=0,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            space_id=space.id,
        )
        session.add(website)
        await session.flush()
        for position, blob_id in enumerate(blob_ids):
            text = f"Indexed municipal information {position}"
            session.add(
                InfoBlobs(
                    id=blob_id,
                    title=f"Information {position}",
                    url=f"https://municipality.example/information/{position}",
                    text=text,
                    size=len(text.encode()),
                    content_hash=sha256(text.encode()).digest(),
                    source_id=uuid4(),
                    version_state=InfoBlobVersionState.ACTIVE.value,
                    user_id=admin_user.id,
                    tenant_id=admin_user.tenant_id,
                    website_id=website.id,
                    embedding_model_id=embedding_model_id,
                )
            )
        website_id = website.id

    headers = {"Authorization": f"Bearer {admin_token}"}
    first_response = await client.get(
        f"/api/v1/websites/{website_id}/info-blobs/?limit=2",
        headers=headers,
    )

    assert first_response.status_code == 200, first_response.text
    first_page = first_response.json()
    assert [item["id"] for item in first_page["items"]] == [
        str(blob_ids[0]),
        str(blob_ids[1]),
    ]
    assert all("text" not in item for item in first_page["items"])
    assert first_page["count"] == 2
    assert first_page["limit"] == 2
    assert first_page["total_count"] == 3
    assert first_page["next_cursor"] == str(blob_ids[1])

    second_response = await client.get(
        f"/api/v1/websites/{website_id}/info-blobs/",
        params={"limit": 2, "cursor": first_page["next_cursor"]},
        headers=headers,
    )

    assert second_response.status_code == 200, second_response.text
    second_page = second_response.json()
    assert [item["id"] for item in second_page["items"]] == [str(blob_ids[2])]
    assert second_page["total_count"] == 3
    assert second_page["next_cursor"] is None


async def test_deep_website_cursor_page_uses_the_active_composite_index(
    db_container,
) -> None:
    async with db_container() as container:
        session = container.session()
        user = container.user()
        embedding_model_id = await session.scalar(
            sa.select(EmbeddingModels.id).limit(1)
        )
        assert embedding_model_id is not None
        websites = [
            Websites(
                name=f"Municipal website {position}",
                url=f"https://municipality-{position}.example",
                download_files=False,
                crawl_type=CrawlType.CRAWL,
                update_interval="never",
                size=0,
                tenant_id=user.tenant_id,
                user_id=user.id,
                embedding_model_id=embedding_model_id,
            )
            for position in range(100)
        ]
        session.add_all(websites)
        await session.flush()

        first_id = 1_000_000
        rows = []
        for position in range(200):
            for website_offset, website in enumerate(websites):
                item_number = first_id + position * len(websites) + website_offset
                rows.append(
                    {
                        "id": UUID(int=item_number),
                        "title": f"Information {item_number}",
                        "url": f"https://municipality.example/{item_number}",
                        "text": "x",
                        "size": 1,
                        "source_id": UUID(int=10_000_000 + item_number),
                        "version_state": InfoBlobVersionState.ACTIVE.value,
                        "user_id": user.id,
                        "tenant_id": user.tenant_id,
                        "website_id": website.id,
                        "embedding_model_id": embedding_model_id,
                    }
                )
        await session.execute(sa.insert(InfoBlobs), rows)
        await session.execute(sa.text("ANALYZE info_blobs"))

        cursor = UUID(int=first_id + 50 * len(websites))
        explain = await session.scalar(
            sa.text(
                """
                EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                SELECT id
                FROM info_blobs
                WHERE website_id = :website_id
                  AND version_state = 'active'
                  AND id > :cursor
                ORDER BY id
                LIMIT 101
                """
            ),
            {"website_id": websites[0].id, "cursor": cursor},
        )
        assert isinstance(explain, list)
        plan = explain[0]["Plan"]

        assert _ACTIVE_WEBSITE_CURSOR_INDEX in _plan_index_names(plan)
        assert plan["Actual Rows"] == 101

        count_explain = await session.scalar(
            sa.text(
                """
                EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                SELECT count(id)
                FROM info_blobs
                WHERE website_id = :website_id
                  AND version_state = 'active'
                """
            ),
            {"website_id": websites[0].id},
        )
        assert isinstance(count_explain, list)
        count_plan = count_explain[0]["Plan"]
        assert _WEBSITE_INDEX in _plan_index_names(count_plan)
        assert count_plan["Actual Rows"] == 1
