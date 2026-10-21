"""Documents, skipped-file and sync-progress routes of a space's integration items,
after authentication."""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from dependency_injector import providers
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from eneo.actors.actors.space_actor import SpaceAccessFacts
from eneo.authentication.auth_dependencies import get_current_active_user
from eneo.authentication.auth_models import ApiKeyOwnership, ApiKeyPermission
from eneo.embedding_models.domain.embedding_model import EmbeddingModel
from eneo.info_blobs.info_blob import InfoBlobInDBNoText
from eneo.info_blobs.info_blob_repo import IntegrationDocumentsPage
from eneo.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from eneo.integration.domain.entities.sync_log import SyncLog
from eneo.integration.domain.repositories.integration_knowledge_repo import (
    IntegrationKnowledgeLocation,
    IntegrationKnowledgeSyncingError,
)
from eneo.integration.domain.skip_reasons import NO_TEXT_LAYER_REASON
from eneo.integration.infrastructure.auth_service.org_token_provider import (
    CREDENTIALS_INVALID_MESSAGE,
    SharePointCredentialsInvalidError,
)
from eneo.integration.infrastructure.sharepoint_sync_progress import (
    sync_progress_key,
)
from eneo.jobs.job_models import JobInDb, Task
from eneo.main.container.container import Container
from eneo.main.exceptions import NotFoundException
from eneo.main.models import Status
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleInDB
from eneo.server.exception_handlers import add_exception_handlers
from eneo.spaces.api.space_models import SpaceMember, SpaceRoleValue
from eneo.spaces.api.space_router import router
from eneo.spaces.space import Space
from eneo.users.user import UserInDB
from tests.unit.api_key_test_utils import make_api_key

FOLDER = "https://contoso.sharepoint.com/sites/KS/Shared%20Documents/Protokoll"


def _embedding_model(user: UserInDB) -> EmbeddingModel:
    return EmbeddingModel(
        id=uuid4(),
        created_at=None,
        updated_at=None,
        tenant=user.tenant,
        nickname=None,
        name="multilingual-e5-large",
        family=None,
        hosting=None,
        org=None,
        stability=None,
        open_source=True,
        description=None,
        hf_link=None,
        is_deprecated=False,
        is_org_enabled=True,
        max_input=None,
        dimensions=None,
        security_classification=None,
    )


@dataclass
class DocumentsAPI:
    app: FastAPI
    user: UserInDB
    space: Space
    knowledge: IntegrationKnowledge
    space_repo: AsyncMock
    info_blobs: AsyncMock
    sync_logs: AsyncMock
    progress_redis: AsyncMock
    knowledge_repo: AsyncMock
    container: Container

    @property
    def progress_url(self) -> str:
        return f"/spaces/{self.space.id}/knowledge/integrations/sync-progress/"

    def url(self, path: str = "", knowledge_id: UUID | None = None) -> str:
        return (
            f"/spaces/{self.space.id}/knowledge/integrations/"
            f"{knowledge_id or self.knowledge.id}/documents/{path}"
        )

    def change_url(self, route: str, knowledge_id: UUID) -> str:
        return f"/spaces/{self.space.id}/knowledge/integrations/" + route.format(
            id=knowledge_id
        )


def _blob(knowledge_id: UUID, user: UserInDB, url: str, title: str):
    return InfoBlobInDBNoText(
        id=uuid4(),
        url=url,
        title=title,
        embedding_model_id=uuid4(),
        user_id=user.id,
        tenant_id=user.tenant_id,
        size=1000,
        integration_knowledge_id=knowledge_id,
        source_id=uuid4(),
        version_state="active",
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 13, tzinfo=timezone.utc),
    )


@pytest.fixture
def documents_api(user: UserInDB) -> DocumentsAPI:
    user = user.model_copy(deep=True)
    user.roles = []
    space = Space(
        id=uuid4(),
        tenant_id=user.tenant_id,
        tenant_space_id=uuid4(),
        user_id=None,
        name="Kommunstyrelsen",
        description=None,
        embedding_models=[],
        completion_models=[],
        transcription_models=[],
        mcp_servers=[],
        default_assistant=None,
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={
            user.id: SpaceMember(
                id=user.id, email=user.email, role=SpaceRoleValue.VIEWER
            )
        },
    )
    user_integration = MagicMock()
    user_integration.tenant_integration.integration.integration_type = "sharepoint"
    knowledge = IntegrationKnowledge(
        id=uuid4(),
        name="Protokoll",
        user_integration=user_integration,
        embedding_model=MagicMock(),
        tenant_id=user.tenant_id,
        space_id=space.id,
        url=FOLDER,
        folder_path="/Protokoll",
        selected_item_type="folder",
        resource_type="site",
    )
    space.integration_knowledge_list = [knowledge]
    space_repo = AsyncMock()
    space_repo.one.return_value = space
    # The routes read the caller's facts and the item ids only; both follow
    # the space as a test leaves it.
    space_repo.get_space_access_facts.side_effect = (
        lambda space_id: SpaceAccessFacts.from_space(space)
    )
    space_repo.get_visible_integration_knowledge_ids.side_effect = (
        lambda space_id, tenant_space_id: [
            item.id for item in space.integration_knowledge_list
        ]
    )
    knowledge_repo = AsyncMock()
    knowledge_repo.get_location.side_effect = lambda id: IntegrationKnowledgeLocation(
        id=id,
        integration_type="sharepoint",
        url=knowledge.url,
        folder_path=knowledge.folder_path,
        resource_type=knowledge.resource_type,
    )
    info_blobs = AsyncMock()
    info_blobs.get_integration_knowledge_page.return_value = IntegrationDocumentsPage(
        items=[], total_count=0, total_size=0
    )
    sync_logs = AsyncMock()
    sync_logs.get_by_integration_knowledge.return_value = []
    progress_redis = AsyncMock()

    # Production DI for the service and actor policy; only the edges are
    # replaced, so missing wiring fails here too.
    container = Container(
        user=providers.Object(user),
        space_repo=providers.Object(space_repo),
        info_blob_repo=providers.Object(info_blobs),
        sync_log_repo=providers.Object(sync_logs),
        user_integration_repo=providers.Object(AsyncMock()),
        tenant_integration_repo=providers.Object(AsyncMock()),
        tenant_sharepoint_app_repo=providers.Object(AsyncMock()),
        oauth_token_repo=providers.Object(AsyncMock()),
        integration_knowledge_repo=providers.Object(knowledge_repo),
        embedding_model_repo2=providers.Object(AsyncMock()),
        job_service=providers.Object(AsyncMock()),
        sharepoint_subscription_service=providers.Object(AsyncMock()),
        redis_client=providers.Object(progress_redis),
    )
    app = FastAPI()
    app.include_router(router, prefix="/spaces")
    add_exception_handlers(app)
    app.dependency_overrides[get_current_active_user] = lambda: user
    for route in router.routes:
        if isinstance(route, APIRoute):
            for dependency in route.dependant.dependencies:
                if (
                    getattr(dependency.call, "__name__", "")
                    == "_get_container_with_user"
                ):
                    app.dependency_overrides[dependency.call] = lambda: container
    return DocumentsAPI(
        app,
        user,
        space,
        knowledge,
        space_repo,
        info_blobs,
        sync_logs,
        progress_redis,
        knowledge_repo,
        container,
    )


async def _get(api: DocumentsAPI, url: str, **params):
    async with AsyncClient(
        transport=ASGITransport(app=api.app), base_url="http://test"
    ) as client:
        return await client.get(url, params=params)


async def _send(api: DocumentsAPI, method: str, url: str):
    async with AsyncClient(
        transport=ASGITransport(app=api.app), base_url="http://test"
    ) as client:
        return await client.request(method, url)


CHANGE_ROUTES = [
    pytest.param("DELETE", "remove/{id}/", id="remove"),
    pytest.param("POST", "{id}/sync/", id="sync"),
]


async def test_documents_page_lists_the_item_with_relative_paths(documents_api):
    api = documents_api
    nested = _blob(
        api.knowledge.id, api.user, f"{FOLDER}/Bilagor/2026/KS-1.pdf", "KS-1.pdf"
    )
    direct = _blob(api.knowledge.id, api.user, f"{FOLDER}/KS-2.pdf", "KS-2.pdf")
    api.info_blobs.get_integration_knowledge_page.return_value = (
        IntegrationDocumentsPage(
            items=[nested, direct], total_count=312, total_size=123456
        )
    )

    response = await _get(api, api.url(), limit=50, offset=50)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_count"] == 312
    assert data["total_size"] == 123456
    assert (data["limit"], data["offset"]) == (50, 50)
    assert [(item["title"], item["relative_path"]) for item in data["items"]] == [
        ("KS-2.pdf", ""),
        ("KS-1.pdf", "Bilagor/2026"),
    ]
    assert data["items"][1] == {
        "id": str(nested.id),
        "title": "KS-1.pdf",
        "relative_path": "Bilagor/2026",
        "url": nested.url,
        "size": 1000,
        "updated_at": "2026-10-13T00:00:00Z",
        "source_metadata": [],
    }
    api.info_blobs.get_integration_knowledge_page.assert_awaited_once_with(
        api.knowledge.id,
        q=None,
        url_anchor=FOLDER,
        sort="path",
        descending=False,
        limit=50,
        offset=50,
    )


async def test_documents_page_defaults_to_the_first_fifty_by_path(documents_api):
    api = documents_api

    response = await _get(api, api.url())

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [],
        "total_count": 0,
        "limit": 50,
        "offset": 0,
        "total_size": 0,
    }
    api.info_blobs.get_integration_knowledge_page.assert_awaited_once_with(
        api.knowledge.id,
        q=None,
        url_anchor=FOLDER,
        sort="path",
        descending=False,
        limit=50,
        offset=0,
    )


async def test_documents_page_passes_search_and_sort_to_the_query(documents_api):
    api = documents_api

    response = await _get(api, api.url(), q="bilagor", sort="size", order="desc")

    assert response.status_code == 200, response.text
    api.info_blobs.get_integration_knowledge_page.assert_awaited_once_with(
        api.knowledge.id,
        q="bilagor",
        url_anchor=FOLDER,
        sort="size",
        descending=True,
        limit=50,
        offset=0,
    )


async def test_documents_page_sorted_by_path_reorders_the_page_on_decoded_folders(
    documents_api,
):
    api = documents_api
    swedish = _blob(
        api.knowledge.id, api.user, f"{FOLDER}/%C3%85rsm%C3%B6te/KS-1.pdf", "KS-1.pdf"
    )
    plain = _blob(api.knowledge.id, api.user, f"{FOLDER}/Bilagor/KS-2.pdf", "KS-2.pdf")
    api.info_blobs.get_integration_knowledge_page.return_value = (
        IntegrationDocumentsPage(items=[swedish, plain], total_count=2, total_size=0)
    )

    ascending = await _get(api, api.url(), sort="path")
    by_size = await _get(api, api.url(), sort="size")

    assert ascending.status_code == 200, ascending.text
    assert [item["relative_path"] for item in ascending.json()["items"]] == [
        "Bilagor",
        "Årsmöte",
    ]
    assert [item["relative_path"] for item in by_size.json()["items"]] == [
        "Årsmöte",
        "Bilagor",
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"sort": "created_at"},
        {"order": "down"},
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"offset": 1_000_001},
        {"offset": 2**63},
        {"q": "x" * 201},
    ],
)
async def test_documents_page_rejects_malformed_queries(documents_api, params):
    api = documents_api

    response = await _get(api, api.url(), **params)

    assert response.status_code == 422, response.text
    api.info_blobs.get_integration_knowledge_page.assert_not_awaited()


@pytest.mark.parametrize("path", ["", "skipped/"])
async def test_item_outside_the_space_is_not_found(documents_api, path):
    api = documents_api

    response = await _get(api, api.url(path, knowledge_id=uuid4()))

    assert response.status_code == 404, response.text
    api.info_blobs.get_integration_knowledge_page.assert_not_awaited()
    api.sync_logs.get_by_integration_knowledge.assert_not_awaited()


@pytest.mark.parametrize("path", ["", "skipped/"])
async def test_non_member_is_refused_before_the_item_is_looked_up(documents_api, path):
    api = documents_api
    api.space.members = {}

    response = await _get(api, api.url(path, knowledge_id=uuid4()))

    assert response.status_code == 403, response.text
    api.info_blobs.get_integration_knowledge_page.assert_not_awaited()
    api.sync_logs.get_by_integration_knowledge.assert_not_awaited()


@pytest.mark.parametrize(("method", "route"), CHANGE_ROUTES)
async def test_non_member_is_refused_before_a_changed_item_is_looked_up(
    documents_api, method, route
):
    api = documents_api
    api.space.members = {}

    response = await _send(api, method, api.change_url(route, uuid4()))

    assert response.status_code == 403, response.text
    api.space_repo.one.assert_awaited_once_with(id=api.space.id)


@pytest.mark.parametrize(
    ("method", "route", "action"),
    [
        pytest.param(
            "DELETE", "remove/{id}/", "integration_knowledge_deleted", id="remove"
        ),
        pytest.param("POST", "{id}/sync/", "integration_knowledge_synced", id="sync"),
    ],
)
async def test_a_change_loads_its_space_once_and_audits_the_item(
    documents_api, method, route, action
):
    """The service checks access and hands back the snapshot the audit log uses."""
    api = documents_api
    api.user.roles = [
        RoleInDB(
            id=uuid4(),
            name="Importer",
            tenant_id=api.user.tenant_id,
            permissions=[Permission.INTEGRATIONS],
        )
    ]
    api.space.members[api.user.id].role = SpaceRoleValue.ADMIN
    api.knowledge.user_integration.auth_type = "user_oauth"
    api.knowledge.user_integration.id = uuid4()
    api.knowledge.site_id = "contoso.sharepoint.com,site,web"
    api.container.oauth_token_repo().one.return_value = MagicMock(id=uuid4())
    jobs = AsyncMock()
    jobs.queue_job.return_value = JobInDb(
        id=uuid4(),
        user_id=api.user.id,
        task=Task.PULL_SHAREPOINT_CONTENT,
        name=api.knowledge.name,
        status=Status.QUEUED,
    )
    api.container.job_service.override(providers.Object(jobs))
    audit = AsyncMock()
    api.container.audit_service.override(providers.Object(audit))

    response = await _send(api, method, api.change_url(route, api.knowledge.id))

    assert response.status_code in (202, 204), response.text
    api.space_repo.one.assert_awaited_once_with(id=api.space.id)
    audit.log_async.assert_awaited_once()
    logged = audit.log_async.await_args.kwargs
    assert logged["action"].value == action
    assert logged["entity_id"] == api.knowledge.id
    assert api.space.name in logged["description"]


@pytest.mark.parametrize(("method", "route"), CHANGE_ROUTES)
async def test_changing_an_item_outside_the_space_is_not_found(
    documents_api, method, route
):
    api = documents_api
    api.user.roles = [
        RoleInDB(
            id=uuid4(),
            name="Importer",
            tenant_id=api.user.tenant_id,
            permissions=[Permission.INTEGRATIONS],
        )
    ]
    api.space.members[api.user.id].role = SpaceRoleValue.ADMIN

    response = await _send(api, method, api.change_url(route, uuid4()))

    assert response.status_code == 404, response.text


async def test_distributed_item_is_readable_from_the_receiving_space(documents_api):
    api = documents_api
    api.knowledge.space_id = uuid4()

    response = await _get(api, api.url())

    assert response.status_code == 200, response.text


async def test_skipped_documents_come_from_the_newest_sync_log(documents_api):
    api = documents_api
    api.sync_logs.get_by_integration_knowledge.return_value = [
        SyncLog(
            integration_knowledge_id=api.knowledge.id,
            sync_type="full",
            status="success",
            started_at=datetime(2026, 10, 13, 7, tzinfo=timezone.utc),
            completed_at=datetime(2026, 10, 13, 8, tzinfo=timezone.utc),
            metadata={
                "skipped_details": [
                    {"file": "scan.pdf", "reason": NO_TEXT_LAYER_REASON}
                ],
                "skipped_total": 17,
                "skipped_truncated": True,
            },
        )
    ]

    response = await _get(api, api.url("skipped/"))

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [
            {
                "file": "scan.pdf",
                "reason": NO_TEXT_LAYER_REASON,
                "code": "no_text_layer",
                "params": {},
                "retry": False,
            }
        ],
        "total": 17,
        "truncated": True,
        "synced_at": "2026-10-13T08:00:00Z",
    }
    api.sync_logs.get_by_integration_knowledge.assert_awaited_once_with(
        api.knowledge.id, tenant_id=api.user.tenant_id, limit=1
    )


async def test_skipped_documents_without_a_sync_log_is_empty(documents_api):
    api = documents_api

    response = await _get(api, api.url("skipped/"))

    assert response.status_code == 200, response.text
    assert response.json() == {
        "items": [],
        "total": 0,
        "truncated": False,
        "synced_at": None,
    }


async def test_sync_progress_lists_the_space_items_that_are_syncing(documents_api):
    api = documents_api
    idle = IntegrationKnowledge(
        id=uuid4(),
        name="Riktlinjer",
        user_integration=api.knowledge.user_integration,
        embedding_model=MagicMock(),
        tenant_id=api.user.tenant_id,
        space_id=uuid4(),
    )
    api.space.integration_knowledge_list.append(idle)
    running = {
        "integration_knowledge_id": str(api.knowledge.id),
        "sync_type": "full",
        "phase": "processing",
        "started_at": "2026-10-14T09:00:00Z",
        "updated_at": "2026-10-14T09:02:00Z",
        "total": 120,
        "done": 45,
        "indexed": 30,
        "unchanged": 12,
        "skipped": 3,
        "deleted": 1,
        "current": "Protokoll.docx",
        "recent": [
            {"name": "Budget.xlsm", "outcome": "skipped", "reason": "Unsupported"},
            {"name": "Rutin.pdf", "outcome": "indexed", "reason": None},
        ],
    }
    api.progress_redis.mget.return_value = [json.dumps(running).encode(), None]

    response = await _get(api, api.progress_url)

    assert response.status_code == 200, response.text
    # The feed's entries are served with their codes, classified from the text.
    served = {
        **running,
        "recent": [
            {
                "name": "Budget.xlsm",
                "outcome": "skipped",
                "reason": "Unsupported",
                "code": "error",
                "params": {"detail": "Unsupported"},
                "retry": False,
            },
            {
                "name": "Rutin.pdf",
                "outcome": "indexed",
                "reason": None,
                "code": None,
                "params": {},
                "retry": False,
            },
        ],
    }
    assert response.json() == {"items": [served]}
    api.progress_redis.mget.assert_awaited_once_with(
        [sync_progress_key(api.knowledge.id), sync_progress_key(idle.id)]
    )
    # Polled every few seconds: never the whole space aggregate.
    api.space_repo.one.assert_not_awaited()
    api.space_repo.get_space_access_facts.assert_awaited_once_with(api.space.id)
    api.space_repo.get_visible_integration_knowledge_ids.assert_awaited_once_with(
        api.space.id, api.space.tenant_space_id
    )


async def test_sync_progress_is_refused_to_non_members(documents_api):
    api = documents_api
    api.space.members = {}

    response = await _get(api, api.progress_url)

    assert response.status_code == 403, response.text
    api.space_repo.get_visible_integration_knowledge_ids.assert_not_awaited()
    api.progress_redis.mget.assert_not_awaited()


async def test_sync_progress_of_an_unknown_space_is_not_found(documents_api):
    api = documents_api
    api.space_repo.get_space_access_facts.side_effect = NotFoundException()

    response = await _get(api, api.progress_url)

    assert response.status_code == 404, response.text
    api.progress_redis.mget.assert_not_awaited()


@pytest.mark.parametrize("path", ["", "skipped/"])
async def test_documents_routes_check_access_without_the_space_aggregate(
    documents_api, path
):
    """The source page asks once per folder; the aggregate loads every member,
    assistant and attachment of the space."""
    api = documents_api

    response = await _get(api, api.url(path))

    assert response.status_code == 200, response.text
    api.space_repo.one.assert_not_awaited()
    api.space_repo.get_space_access_facts.assert_awaited_once_with(api.space.id)
    api.space_repo.get_visible_integration_knowledge_ids.assert_awaited_once_with(
        api.space.id, api.space.tenant_space_id
    )


@pytest.mark.parametrize("path", ["", "skipped/"])
async def test_documents_routes_of_an_unknown_space_are_not_found(documents_api, path):
    api = documents_api
    api.space_repo.get_space_access_facts.side_effect = NotFoundException()

    response = await _get(api, api.url(path))

    assert response.status_code == 404, response.text
    api.space_repo.get_visible_integration_knowledge_ids.assert_not_awaited()
    api.knowledge_repo.get_location.assert_not_awaited()


_SIGNED_URL = (
    "https://contoso.sharepoint.com/sites/KS/_layouts/15/download.aspx"
    "?UniqueId=abc&tempauth=v1.eyJhdWQiOiJ4In0.c2lnbmF0dXJl"
)


async def test_skipped_documents_written_before_the_cleanup_are_served_clean(
    documents_api,
):
    api = documents_api
    api.sync_logs.get_by_integration_knowledge.return_value = [
        SyncLog(
            integration_knowledge_id=api.knowledge.id,
            sync_type="delta",
            status="success",
            started_at=datetime(2026, 10, 13, 7, tzinfo=timezone.utc),
            metadata={
                "skipped_details": [
                    {
                        "file": "a.docx",
                        "reason": f"Error: 403, message='Forbidden', url='{_SIGNED_URL}'",
                    }
                ],
                "skipped_total": 1,
            },
        )
    ]

    response = await _get(api, api.url("skipped/"))

    assert response.status_code == 200, response.text
    assert response.json()["items"] == [
        {
            "file": "a.docx",
            "reason": "Error: HTTP 403 Forbidden",
            "code": "http_error",
            "params": {"status": 403, "message": "Forbidden"},
            "retry": False,
        }
    ]
    assert "tempauth" not in response.text


async def test_sync_progress_written_before_the_cleanup_is_served_clean(
    documents_api,
):
    api = documents_api
    running = {
        "integration_knowledge_id": str(api.knowledge.id),
        "sync_type": "delta",
        "phase": "processing",
        "started_at": "2026-10-14T09:00:00Z",
        "updated_at": "2026-10-14T09:02:00Z",
        "total": None,
        "done": 1,
        "indexed": 0,
        "unchanged": 0,
        "skipped": 1,
        "deleted": 0,
        "current": None,
        "recent": [
            {
                "name": "a.docx",
                "outcome": "skipped",
                "reason": f"Error: 403, message='Forbidden', url='{_SIGNED_URL}'",
            }
        ],
    }
    api.progress_redis.mget.return_value = [json.dumps(running).encode()]

    response = await _get(api, api.progress_url)

    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["recent"] == [
        {
            "name": "a.docx",
            "outcome": "skipped",
            "reason": "Error: HTTP 403 Forbidden",
            "code": "http_error",
            "params": {"status": 403, "message": "Forbidden"},
            "retry": False,
        }
    ]


def _organization_item(api: DocumentsAPI) -> None:
    """Make the item one the organization's SharePoint app imported, and the
    caller an admin who may sync it."""
    api.user.roles = [
        RoleInDB(
            id=uuid4(),
            name="Admin",
            tenant_id=api.user.tenant_id,
            permissions=[Permission.ADMIN, Permission.INTEGRATIONS],
        )
    ]
    api.space.members[api.user.id].role = SpaceRoleValue.ADMIN
    api.knowledge.user_integration.auth_type = "tenant_app"
    api.knowledge.user_integration.tenant_app_id = uuid4()
    api.knowledge.site_id = "contoso.sharepoint.com,site,web"


async def test_refused_organization_credentials_are_a_400_with_a_stable_code(
    documents_api,
):
    """An expired app secret made a sync a 500."""
    api = documents_api
    _organization_item(api)
    tokens = AsyncMock()
    tokens.get_access_token.side_effect = SharePointCredentialsInvalidError(
        "AADSTS7000222: The provided client secret keys are expired."
    )
    jobs = AsyncMock()
    api.container.org_token_provider.override(providers.Object(tokens))
    api.container.job_service.override(providers.Object(jobs))

    response = await _send(api, "POST", api.change_url("{id}/sync/", api.knowledge.id))

    assert response.status_code == 400, response.text
    body = response.json()
    assert body["code"] == "sharepoint_credentials_invalid"
    assert body["message"] == CREDENTIALS_INVALID_MESSAGE
    assert "AADSTS" not in response.text
    jobs.queue_job.assert_not_awaited()


@pytest.mark.parametrize(
    ("method", "route", "body"),
    [
        pytest.param(
            "POST",
            "add/{id}/",
            {
                "name": "Protokoll",
                "embedding_model": {"id": str(uuid4())},
                "url": "https://contoso.sharepoint.com/sites/KS",
                "key": "contoso.sharepoint.com,site,web",
            },
            id="add",
        ),
        pytest.param(
            "POST",
            "add/{id}/batch/",
            {
                "embedding_model": {"id": str(uuid4())},
                "items": [
                    {
                        "name": "Protokoll",
                        "url": "https://contoso.sharepoint.com/sites/KS",
                        "key": "contoso.sharepoint.com,site,web",
                    }
                ],
            },
            id="batch",
        ),
        pytest.param("POST", "{id}/sync/", None, id="sync"),
    ],
)
async def test_service_keys_cannot_queue_imports_or_syncs(
    documents_api, method, route, body
):
    """The queued job belongs to the caller; a service key has no user row."""
    api = documents_api
    api.user.active_api_key = make_api_key(
        ownership=ApiKeyOwnership.SERVICE,
        owner_user_id=None,
        permission=ApiKeyPermission.ADMIN,
        tenant_id=api.user.tenant_id,
    )
    jobs = AsyncMock()
    api.container.job_service.override(providers.Object(jobs))

    async with AsyncClient(
        transport=ASGITransport(app=api.app), base_url="http://test"
    ) as client:
        response = await client.request(
            method, api.change_url(route, api.knowledge.id), json=body
        )

    assert response.status_code == 403, response.text
    # The production app flattens this detail; this app serves it as raised.
    assert response.json()["detail"]["code"] == "service_key_cannot_create_resources"
    jobs.queue_job.assert_not_awaited()
    api.space_repo.one.assert_not_awaited()


@pytest.mark.parametrize(
    "route, body",
    [
        pytest.param("{id}/", {"name": "  Protokoll KS  "}, id="item"),
        pytest.param("wrappers/{wrapper}/", {"name": "Kommunstyrelsen"}, id="wrapper"),
    ],
)
async def test_a_rename_serves_the_item_with_its_permissions(
    documents_api, route, body
):
    """The rename responses used to serve no permissions at all."""
    api = documents_api
    api.user.roles = [
        RoleInDB(
            id=uuid4(),
            name="Importer",
            tenant_id=api.user.tenant_id,
            permissions=[Permission.INTEGRATIONS],
        )
    ]
    api.space.members[api.user.id].role = SpaceRoleValue.ADMIN
    api.knowledge.wrapper_id = uuid4()
    api.knowledge.embedding_model = _embedding_model(api.user)
    api.knowledge.user_integration.id = uuid4()
    api.knowledge.user_integration.auth_type = "user_oauth"
    api.knowledge_repo.one.return_value = api.knowledge
    api.knowledge_repo.get_by_ids.return_value = [api.knowledge]

    async with AsyncClient(
        transport=ASGITransport(app=api.app), base_url="http://test"
    ) as client:
        response = await client.patch(
            f"/spaces/{api.space.id}/knowledge/integrations/"
            + route.format(id=api.knowledge.id, wrapper=api.knowledge.wrapper_id),
            json=body,
        )

    assert response.status_code == 200, response.text
    served = response.json()
    item = served[0] if isinstance(served, list) else served
    # As the space response lists them for an item the space owns.
    assert item["permissions"] == ["edit", "delete"]
    if route == "{id}/":
        api.knowledge_repo.rename.assert_awaited_once_with(
            api.knowledge.id, "Protokoll KS"
        )


@pytest.mark.parametrize("name", ["", "   ", "x" * 256])
@pytest.mark.parametrize("route", ["{id}/", "wrappers/{wrapper}/"])
async def test_a_rename_to_a_blank_or_overlong_name_is_refused(
    documents_api, route, name
):
    api = documents_api

    async with AsyncClient(
        transport=ASGITransport(app=api.app), base_url="http://test"
    ) as client:
        response = await client.patch(
            f"/spaces/{api.space.id}/knowledge/integrations/"
            + route.format(id=api.knowledge.id, wrapper=uuid4()),
            json={"name": name},
        )

    assert response.status_code == 422, response.text
    api.knowledge_repo.rename.assert_not_awaited()
    api.knowledge_repo.rename_wrapper.assert_not_awaited()


async def test_a_batch_the_caller_may_not_import_into_is_refused_whole(documents_api):
    """A viewer got a 202 with every item reported failed."""
    api = documents_api
    api.knowledge_repo.add = AsyncMock()

    async with AsyncClient(
        transport=ASGITransport(app=api.app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/spaces/{api.space.id}/knowledge/integrations/add/{uuid4()}/batch/",
            json={
                "embedding_model": {"id": str(uuid4())},
                "items": [
                    {
                        "name": "Protokoll",
                        "url": "https://contoso.sharepoint.com/sites/KS",
                        "key": "contoso.sharepoint.com,site,web",
                    }
                ],
            },
        )

    assert response.status_code == 403, response.text
    api.knowledge_repo.add.assert_not_awaited()


@pytest.mark.parametrize(
    "method, route, body",
    [
        pytest.param("PATCH", "{id}/", {"name": "Protokoll KS"}, id="rename"),
        pytest.param("DELETE", "remove/{id}/", None, id="delete"),
    ],
)
async def test_a_change_to_a_syncing_source_is_a_409(
    documents_api, method, route, body
):
    api = documents_api
    api.user.roles = [
        RoleInDB(
            id=uuid4(),
            name="Importer",
            tenant_id=api.user.tenant_id,
            permissions=[Permission.INTEGRATIONS],
        )
    ]
    api.space.members[api.user.id].role = SpaceRoleValue.ADMIN
    api.knowledge.user_integration.auth_type = "user_oauth"
    api.knowledge.sharepoint_subscription_id = None
    api.knowledge_repo.rename.side_effect = IntegrationKnowledgeSyncingError()
    api.knowledge_repo.remove.side_effect = IntegrationKnowledgeSyncingError()

    async with AsyncClient(
        transport=ASGITransport(app=api.app), base_url="http://test"
    ) as client:
        response = await client.request(
            method, api.change_url(route, api.knowledge.id), json=body
        )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "integration_knowledge_syncing"
    assert "try again" in response.json()["message"]
