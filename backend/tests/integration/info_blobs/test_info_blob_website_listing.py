from hashlib import sha256
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.ai_models_table import EmbeddingModels
from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from eneo.database.tables.spaces_table import SpacesUsers
from eneo.database.tables.websites_table import Websites
from eneo.websites.domain.crawl_run import CrawlType


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

    # A fresh session has no website row cached, so the listing must carry
    # the relationship itself instead of relying on a lazy load.
    async with db_container() as container:
        blobs = await container.info_blob_repo().get_by_website(website_id)

        assert [item.id for item in blobs] == [blob_id]
        assert not hasattr(blobs[0], "text")
        assert blobs[0].website is not None
        assert blobs[0].website.id == website_id


async def test_website_info_blob_endpoint_lists_indexed_pages(
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

    response = await client.get(
        f"/api/v1/websites/{website_id}/info-blobs/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200, response.text
    page = response.json()
    assert set(page) == {"items", "count"}
    assert [item["id"] for item in page["items"]] == [
        str(blob_id) for blob_id in blob_ids
    ]
    assert all("text" not in item for item in page["items"])
    assert page["count"] == 3
