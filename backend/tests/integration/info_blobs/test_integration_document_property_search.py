"""Document search over SharePoint properties, as Postgres evaluates the path."""

from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

from eneo.database.tables.info_blobs_table import InfoBlobs, InfoBlobVersionState
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.spaces_table import Spaces

PROPERTIES = {
    "Beslut.pdf": [
        {"name": "Arkiverad", "label": "Arkiverad", "value": "true", "kind": "boolean"},
        {"name": "Typ", "label": "Typ", "value": "Protokoll", "kind": "choice"},
    ],
    "Rutin.docx": [
        {"name": "Giltig", "label": "Giltig", "value": "false", "kind": "boolean"},
        {
            "name": "Taggar",
            "label": "Taggar",
            "value": ["Rutin", "true crime"],
            "kind": "text",
        },
    ],
    "Mall.docx": [
        {
            "name": "Fastställd",
            "label": "Fastställd",
            "value": "2026-10-01T00:00:00Z",
            "kind": "date",
        },
        # Written before properties carried a kind.
        {"name": "Ägare", "label": "Ägare", "value": "Kommunstyrelsen"},
    ],
}


async def test_property_search_matches_values_but_not_yes_no_columns(
    db_container,
    admin_user,
    tenant_factory,
    user_integration_factory,
    embedding_model_factory,
):
    async with db_container(user=admin_user) as container:
        session = container.session()
        # A fresh tenant, whose organization space this can be.
        tenant_id = (await tenant_factory(session)).id
        space = Spaces(
            name=f"Search {uuid4().hex[:8]}",
            tenant_id=tenant_id,
            user_id=None,
            tenant_space_id=None,
        )
        session.add(space)
        model = await embedding_model_factory(session)
        connection = await user_integration_factory(session, tenant_id=tenant_id)
        await session.flush()
        knowledge = IntegrationKnowledge(
            name="Protokoll",
            url="https://contoso.sharepoint.com/sites/KS/Protokoll",
            space_id=space.id,
            tenant_id=tenant_id,
            embedding_model_id=model.id,
            user_integration_id=connection.id,
        )
        session.add(knowledge)
        await session.flush()
        for title, properties in PROPERTIES.items():
            text = f"{title} body"
            session.add(
                InfoBlobs(
                    title=title,
                    text=text,
                    url=f"{knowledge.url}/{title}",
                    size=len(text),
                    content_hash=sha256(text.encode()).digest(),
                    source_id=uuid4(),
                    version_state=InfoBlobVersionState.ACTIVE.value,
                    user_id=admin_user.id,
                    tenant_id=tenant_id,
                    integration_knowledge_id=knowledge.id,
                    embedding_model_id=model.id,
                    source_metadata=properties,
                )
            )
        await session.flush()
        repo = container.info_blob_repo()

        async def matching(q: str) -> list[str]:
            page = await repo.get_integration_knowledge_page(
                knowledge.id, q=q, url_anchor=knowledge.url, sort="name", limit=50
            )
            return [item.title or "" for item in page.items]

        # Stored true/false is shown as yes/no, so it is never matched; "true"
        # in a text value still is.
        assert await matching("true") == ["Rutin.docx"]
        assert await matching("false") == []
        assert await matching("protokoll") == ["Beslut.pdf"]
        assert await matching("crime") == ["Rutin.docx"]
        # A date-only value as the page shows it, and an entry without a kind.
        assert await matching("2026-10-01") == ["Mall.docx"]
        assert await matching("kommunstyrelsen") == ["Mall.docx"]
