"""Confluence sync records its outcome on the knowledge row like SharePoint does."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from eneo.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from eneo.integration.domain.entities.oauth_token import ConfluenceToken
from eneo.integration.domain.value_objects import IntegrationType
from eneo.integration.infrastructure.content_service.confluence_content_service import (
    ConfluenceContentService,
)

_CLIENT = (
    "eneo.integration.infrastructure.content_service.confluence_content_service."
    "ConfluenceContentClient"
)


@pytest.fixture
def knowledge() -> IntegrationKnowledge:
    return IntegrationKnowledge(
        id=uuid4(),
        name="Wiki",
        user_integration=MagicMock(),
        embedding_model=MagicMock(),
        tenant_id=uuid4(),
        space_id=uuid4(),
    )


@pytest.fixture
def token() -> ConfluenceToken:
    return ConfluenceToken(
        id=uuid4(),
        access_token="at",
        refresh_token="rt",
        token_type=IntegrationType.Confluence,
        user_integration=MagicMock(),
        resources=[{"id": "cloud-1", "url": "https://example.atlassian.net"}],
    )


@pytest.fixture
def service(user, knowledge, token):
    knowledge_repo = AsyncMock()
    knowledge_repo.one.return_value = knowledge
    knowledge_repo.update.side_effect = lambda obj: obj
    token_repo = AsyncMock()
    token_repo.one.return_value = token
    info_blob_service = AsyncMock()
    info_blob_service.repo.get_total_size_of_integration_knowledge = AsyncMock(
        return_value=12
    )
    return ConfluenceContentService(
        job_service=AsyncMock(),
        oauth_token_repo=token_repo,
        user_integration_repo=AsyncMock(),
        user=user,
        info_blob_service=info_blob_service,
        integration_knowledge_repo=knowledge_repo,
        oauth_token_service=AsyncMock(),
    )


def _client(get_content: AsyncMock) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get_content = get_content
    return client


async def test_completed_sync_is_marked_succeeded(service, knowledge, token):
    page = {"results": [{"title": "Page", "body": {}, "_links": {"webui": "/p/1"}}]}
    get_content = AsyncMock(side_effect=[page, {"results": []}])

    with patch(_CLIENT, return_value=_client(get_content)):
        await service.pull_content(
            token_id=token.id, space_key="DOCS", integration_knowledge_id=knowledge.id
        )

    assert knowledge.last_sync_status == "success"
    assert knowledge.last_sync_error is None
    assert knowledge.last_synced_at is not None
    assert knowledge.last_sync_attempted_at is not None
    assert knowledge.size == 12
    assert service.integration_knowledge_repo.update.await_args.kwargs["obj"] is (
        knowledge
    )


async def test_failed_sync_is_marked_failed_before_reraise(service, knowledge, token):
    get_content = AsyncMock(side_effect=RuntimeError("Confluence unreachable"))
    update = service.integration_knowledge_repo.update

    with patch(_CLIENT, return_value=_client(get_content)):
        with pytest.raises(RuntimeError, match="Confluence unreachable"):
            await service.pull_content(
                token_id=token.id,
                space_key="DOCS",
                integration_knowledge_id=knowledge.id,
            )

    assert knowledge.last_sync_status == "error"
    assert knowledge.last_sync_error == "Confluence unreachable"
    assert knowledge.last_synced_at is None
    assert update.await_args.kwargs["obj"] is knowledge
    assert update.await_args.kwargs["obj"].last_sync_status == "error"
