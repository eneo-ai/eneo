import json
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from eneo.database.tables.spaces_table import SpacesUsers
from eneo.database.tables.websites_table import Websites
from eneo.users.user import UserAdd, UserState
from eneo.websites.domain.crawl_run import CrawlType

pytestmark = pytest.mark.integration

_ACTIVE_WEBSITE_CURSOR_INDEX = "ix_info_blobs_active_website_cursor"
_ACTIVE_WEBSITE_PATH_INDEX = "ix_info_blobs_active_website_path"
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
        page = await container.info_blob_repo().get_by_website_page(
            website_id,
            limit=100,
        )

        assert [item.id for item in page.items] == [blob_id]
        assert page.total_count == 1
        assert page.next_cursor is None
        assert not hasattr(page.items[0], "text")
        assert page.items[0].website is not None
        assert page.items[0].website.id == website_id


async def test_website_info_blob_endpoints_preserve_list_and_cursor_contracts(
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
    legacy_response = await client.get(
        f"/api/v1/websites/{website_id}/info-blobs/",
        headers=headers,
    )

    assert legacy_response.status_code == 200, legacy_response.text
    legacy_page = legacy_response.json()
    assert set(legacy_page) == {"items", "count"}
    assert [item["id"] for item in legacy_page["items"]] == [
        str(blob_id) for blob_id in blob_ids
    ]
    assert legacy_page["count"] == 3

    first_response = await client.get(
        f"/api/v1/websites/{website_id}/info-blobs/page/?limit=2",
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
        f"/api/v1/websites/{website_id}/info-blobs/page/",
        params={"limit": 2, "cursor": first_page["next_cursor"]},
        headers=headers,
    )

    assert second_response.status_code == 200, second_response.text
    second_page = second_response.json()
    assert [item["id"] for item in second_page["items"]] == [str(blob_ids[2])]
    assert second_page["total_count"] == 3
    assert second_page["next_cursor"] is None


async def test_content_folder_endpoint_contract(
    client,
    db_container,
    admin_user,
    admin_token: str,
    space_factory,
) -> None:
    origin = "https://municipality.example/"
    async with db_container(user=admin_user) as container:
        session = container.session()
        embedding_model_id = await session.scalar(
            sa.select(EmbeddingModels.id).limit(1)
        )
        assert embedding_model_id is not None
        space = await space_factory(session, f"Website folders {uuid4()}")
        session.add(SpacesUsers(space_id=space.id, user_id=admin_user.id, role="admin"))
        website = Websites(
            name="Municipal website",
            url=origin,
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
        for position in range(2):
            session.add(
                InfoBlobs(
                    id=UUID(int=201 + position),
                    title=f"Document {position}",
                    url=f"{origin}docs/{position}",
                    text="text",
                    size=4,
                    source_id=uuid4(),
                    version_state=InfoBlobVersionState.ACTIVE.value,
                    user_id=admin_user.id,
                    tenant_id=admin_user.tenant_id,
                    website_id=website.id,
                    embedding_model_id=embedding_model_id,
                )
            )
        website_id = website.id
        # Same tenant, not a member of the space.
        outsider = await container.user_repo().add(
            UserAdd(
                email=f"outsider-{uuid4()}@example.com",
                username=f"outsider-{uuid4().hex[:8]}",
                tenant_id=admin_user.tenant_id,
                state=UserState.ACTIVE,
            )
        )
        outsider_token = container.auth_service().create_access_token_for_user(outsider)

    endpoint = f"/api/v1/websites/{website_id}/content-folders/"
    headers = {"Authorization": f"Bearer {admin_token}"}

    roots = await client.get(endpoint, headers=headers)
    assert roots.status_code == 200, roots.text
    assert roots.json() == {
        "items": [{"path": origin, "count": 2, "has_children": True}],
        "next_cursor": None,
    }

    level = await client.get(endpoint, params={"prefix": origin}, headers=headers)
    assert level.status_code == 200, level.text
    assert level.json()["items"] == [
        {"path": f"{origin}docs/", "count": 2, "has_children": False}
    ]

    invalid = await client.get(endpoint, params={"prefix": "docs/"}, headers=headers)
    assert invalid.status_code == 422, invalid.text

    missing = await client.get(
        f"/api/v1/websites/{uuid4()}/content-folders/", headers=headers
    )
    assert missing.status_code == 404, missing.text

    forbidden = await client.get(
        endpoint, headers={"Authorization": f"Bearer {outsider_token}"}
    )
    assert forbidden.status_code == 403, forbidden.text


async def test_website_directories_and_search_cover_the_active_index(db_container):
    origin = "https://municipality.example/"
    async with db_container() as container:
        session = container.session()
        user = container.user()
        model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
        website = Websites(
            name="URL navigation",
            url=origin,
            download_files=True,
            crawl_type=CrawlType.CRAWL,
            update_interval="never",
            size=0,
            tenant_id=user.tenant_id,
            user_id=user.id,
            embedding_model_id=model_id,
        )
        session.add(website)
        await session.flush()
        website_id = website.id
        paths = [
            "A/first",
            "A/nested/guide.pdf",
            "A/nested/index?redirect=/other/path",
            "a/lowercase",
            "A%20B_100%25/literal",
            "AxBz100zz/decoy",
            "%C3%85rsplan/guide",
            "root?download=/ignored/path",
        ]
        for index, path in enumerate(paths + ["A/obsolete"]):
            session.add(
                InfoBlobs(
                    id=UUID(int=9001 + index),
                    title=f"Resource {index}",
                    url=origin + path,
                    text="sample",
                    size=6,
                    source_id=uuid4(),
                    version_state="superseded" if path == "A/obsolete" else "active",
                    user_id=user.id,
                    tenant_id=user.tenant_id,
                    website_id=website_id,
                    embedding_model_id=model_id,
                )
            )
        await session.flush()
        repo = container.info_blob_repo()

        roots = await repo.get_website_folders(website_id)
        assert [(item.path, item.count, item.has_children) for item in roots.items] == [
            (origin, 8, True)
        ]
        # Directory pagination must preserve case-sensitive distinct prefixes.
        first = await repo.get_website_folders(website_id, prefix=origin, limit=2)
        assert len(first.items) == 2
        second = await repo.get_website_folders(
            website_id, prefix=origin, cursor=first.next_cursor, limit=100
        )
        folders = {item.path: item for item in first.items + second.items}
        assert len(folders) == 5
        assert folders[origin + "A/"].count == 3
        assert folders[origin + "a/"].count == 1
        assert folders[origin + "A/"].has_children
        assert not folders[origin + "a/"].has_children
        assert all("ignored" not in path and "other" not in path for path in folders)

        nested = await repo.get_website_folders(website_id, prefix=origin + "A/")
        assert [
            (item.path, item.count, item.has_children) for item in nested.items
        ] == [(origin + "A/nested/", 2, False)]
        documents = await repo.get_by_website_page(
            website_id, prefix=origin + "A/", limit=1
        )
        assert documents.total_count == 3
        remaining = await repo.get_by_website_page(
            website_id, prefix=origin + "A/", cursor=documents.next_cursor, limit=100
        )
        assert remaining.total_count == 3
        assert len(remaining.items) == 2
        assert all(item.url.startswith(origin + "A/") for item in remaining.items)
        literal = await repo.get_by_website_page(
            website_id, prefix=origin + "A%20B_100%25/", limit=100
        )
        assert [item.title for item in literal.items] == ["Resource 4"]
        encoded = await repo.get_by_website_page(website_id, q="Årsplan", limit=100)
        assert [item.title for item in encoded.items] == ["Resource 6"]
        combined = await repo.get_by_website_page(
            website_id, prefix=origin + "A/", q="guide", limit=100
        )
        assert [item.title for item in combined.items] == ["Resource 1"]
        # The scheme and host are never searched, so the website's own name
        # matches nothing; below a directory only the remainder is searched.
        for host_query in ("municipality", "https"):
            host = await repo.get_by_website_page(website_id, q=host_query, limit=100)
            assert host.items == []
        scoped = await repo.get_by_website_page(
            website_id, prefix=origin + "A/", q="A/", limit=100
        )
        assert scoped.items == []
        below = await repo.get_by_website_page(
            website_id, prefix=origin + "A/", q="nested", limit=100
        )
        assert sorted(item.title for item in below.items) == [
            "Resource 1",
            "Resource 2",
        ]
        other = await repo.get_website_folders(uuid4(), prefix=origin)
        assert other.items == []


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


def _sql_literal(value: object) -> str:
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


async def _prepared_plan(session, statement) -> dict[str, object]:
    """How PostgreSQL plans ``statement`` as asyncpg sends it: prepared, then
    executed with its bound values. A literal-bound copy would hide an
    expression that only matches the index once parameters are inlined."""
    compiled = statement.compile(dialect=session.get_bind().dialect)
    values = ", ".join(
        _sql_literal(compiled.params[name]) for name in compiled.positiontup or ()
    )
    connection = await session.connection()
    await connection.exec_driver_sql(f"PREPARE website_content AS {compiled}")
    try:
        explain = (
            await connection.exec_driver_sql(
                f"EXPLAIN (FORMAT JSON) EXECUTE website_content({values})"
            )
        ).scalar()
    finally:
        await connection.exec_driver_sql("DEALLOCATE website_content")
    if isinstance(explain, str):
        explain = json.loads(explain)
    return explain[0]["Plan"]


async def test_directory_queries_range_over_the_website_path_index(
    db_container, monkeypatch
) -> None:
    origin = "https://municipality.example/"
    async with db_container() as container:
        session = container.session()
        user = container.user()
        model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
        website = Websites(
            name="Large municipal website",
            url=origin,
            download_files=False,
            crawl_type=CrawlType.CRAWL,
            update_interval="never",
            size=0,
            tenant_id=user.tenant_id,
            user_id=user.id,
            embedding_model_id=model_id,
        )
        session.add(website)
        await session.flush()
        await session.execute(
            sa.insert(InfoBlobs),
            [
                {
                    "id": UUID(int=2_000_000 + position),
                    "title": f"Page {position}",
                    "url": f"{origin}section-{position % 40}/sub-{position % 3}/"
                    f"page-{position}",
                    "text": "x",
                    "size": 1,
                    "source_id": uuid4(),
                    "version_state": InfoBlobVersionState.ACTIVE.value,
                    "user_id": user.id,
                    "tenant_id": user.tenant_id,
                    "website_id": website.id,
                    "embedding_model_id": model_id,
                }
                for position in range(4000)
            ],
        )
        await session.execute(sa.text("ANALYZE info_blobs"))

        statements: list[object] = []
        for method in ("scalar", "scalars", "execute"):
            original = getattr(session, method)

            async def capture(statement, *args, _original=original, **kwargs):
                # scalar() and scalars() may delegate to execute(): keep each once.
                if not any(seen is statement for seen in statements):
                    statements.append(statement)
                return await _original(statement, *args, **kwargs)

            monkeypatch.setattr(session, method, capture)

        repo = container.info_blob_repo()
        directory = f"{origin}section-7/"
        page = await repo.get_by_website_page(website.id, prefix=directory, limit=20)
        folders = await repo.get_website_folders(website.id, prefix=directory)
        monkeypatch.undo()

        assert page.total_count == 100
        assert all(item.url.startswith(directory) for item in page.items)
        in_directory = [position for position in range(4000) if position % 40 == 7]
        assert [(folder.path, folder.count) for folder in folders.items] == [
            (
                f"{directory}sub-{part}/",
                sum(position % 3 == part for position in in_directory),
            )
            for part in range(3)
        ]
        count_query, page_query, folder_query = statements
        for statement in (count_query, page_query, folder_query):
            plan = await _prepared_plan(session, statement)
            assert _ACTIVE_WEBSITE_PATH_INDEX in _plan_index_names(plan), plan
