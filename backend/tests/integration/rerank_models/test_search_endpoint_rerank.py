"""The collection search endpoint switches reranking on per call.

With ``rerank: true`` the router resolves the collection's space, asks the
rerank service for a spec, and hands it to the datastore. Without the flag
the datastore gets no spec and runs today's path.
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from eneo.collections.application.collection_crud_service import (
    CollectionCRUDService,
)
from eneo.embedding_models.infrastructure.datastore import Datastore
from eneo.rerank_models.application.rerank_service import RerankService
from eneo.spaces.space_service import SpaceService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

SPEC = object()


@pytest.fixture
def wired(monkeypatch):
    """Stub the pieces behind the router and record what it passes on."""
    seen: dict[str, object] = {}
    collection = MagicMock(id=uuid4(), space_id=uuid4(), embedding_model=MagicMock())
    space = MagicMock(security_classification=MagicMock(name="classification"))

    async def get_collection(self, id):  # noqa: ARG001
        return collection

    async def get_space(self, id):  # noqa: ARG001
        seen["space_id"] = id
        return space

    async def spec_for_default(self, query, security_classification):  # noqa: ARG001
        seen["query"] = query
        seen["classification"] = security_classification
        return SPEC

    async def semantic_search(self, *args, **kwargs):  # noqa: ARG001
        seen["rerank"] = kwargs.get("rerank")
        return []

    monkeypatch.setattr(CollectionCRUDService, "get_collection", get_collection)
    monkeypatch.setattr(SpaceService, "get_space", get_space)
    monkeypatch.setattr(RerankService, "spec_for_default", spec_for_default)
    monkeypatch.setattr(Datastore, "semantic_search", semantic_search)
    return seen, collection, space


async def test_rerank_flag_hands_the_default_spec_to_the_datastore(
    client, tenant_user_token, wired
):
    seen, collection, space = wired

    response = await client.post(
        f"/api/v1/groups/{collection.id}/searches/",
        json={"search_string": "what does the policy say", "rerank": True},
        headers={"Authorization": f"Bearer {tenant_user_token}"},
    )

    assert response.status_code == 200, response.text
    assert seen["rerank"] is SPEC
    assert seen["query"] == "what does the policy say"
    assert seen["space_id"] == collection.space_id
    assert seen["classification"] is space.security_classification


async def test_without_the_flag_no_spec_is_built(client, tenant_user_token, wired):
    seen, collection, _ = wired

    response = await client.post(
        f"/api/v1/groups/{collection.id}/searches/",
        json={"search_string": "what does the policy say"},
        headers={"Authorization": f"Bearer {tenant_user_token}"},
    )

    assert response.status_code == 200, response.text
    assert seen["rerank"] is None
    assert "query" not in seen


async def test_a_default_reranker_whose_provider_is_disabled_still_answers(
    client, tenant_user_token, db_container, rerank_model_factory, monkeypatch
):
    """The real rerank service with a default model behind a disabled provider:
    no spec reaches the datastore, and the search answers with vector order."""
    from sqlalchemy import update

    from eneo.database.tables.model_providers_table import ModelProviders

    async with db_container() as container:
        session = container.session()
        model = await rerank_model_factory(session, "default-rerank", is_default=True)
        await session.execute(
            update(ModelProviders)
            .where(ModelProviders.id == model.provider_id)
            .values(is_active=False)
        )
        await session.commit()

    seen: dict[str, object] = {}
    collection = MagicMock(id=uuid4(), space_id=uuid4(), embedding_model=MagicMock())
    space = MagicMock(security_classification=None)

    async def get_collection(self, id):  # noqa: ARG001
        return collection

    async def get_space(self, id):  # noqa: ARG001
        return space

    async def semantic_search(self, *args, **kwargs):  # noqa: ARG001
        seen["rerank"] = kwargs.get("rerank")
        return []

    monkeypatch.setattr(CollectionCRUDService, "get_collection", get_collection)
    monkeypatch.setattr(SpaceService, "get_space", get_space)
    monkeypatch.setattr(Datastore, "semantic_search", semantic_search)

    response = await client.post(
        f"/api/v1/groups/{collection.id}/searches/",
        json={"search_string": "what does the policy say", "rerank": True},
        headers={"Authorization": f"Bearer {tenant_user_token}"},
    )

    assert response.status_code == 200, response.text
    assert seen["rerank"] is None
