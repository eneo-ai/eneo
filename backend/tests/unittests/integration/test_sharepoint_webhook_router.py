"""HTTP contract of the public Graph webhook endpoint."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient

from eneo.integration.domain.entities.sharepoint_subscription import (
    SharePointSubscription,
)
from eneo.integration.infrastructure.sharepoint_webhook_service import (
    SharepointWebhookService,
)
from eneo.integration.presentation.sharepoint_webhook_router import (
    MAX_WEBHOOK_BODY_BYTES,
    router,
)

CLIENT_STATE = "webhook-secret"
WEBHOOK = "/integrations/sharepoint/webhook/"


@dataclass
class WebhookApi:
    client: AsyncClient
    service: SharepointWebhookService
    session: AsyncMock
    subscription_repo: AsyncMock
    subscription: SharePointSubscription
    job_service: AsyncMock


@pytest.fixture
async def api():
    session = AsyncMock()
    session.begin = MagicMock()
    subscription = SharePointSubscription(
        id=uuid4(),
        user_integration_id=uuid4(),
        site_id="site-1",
        subscription_id="sub-known",
        drive_id="drive-1",
        expires_at=datetime.now(timezone.utc) + timedelta(days=10),
    )
    subscription_repo = AsyncMock()
    subscription_repo.get_by_subscription_id.side_effect = (
        lambda subscription_id: subscription if subscription_id == "sub-known" else None
    )
    change_keys = AsyncMock()
    change_keys.should_process.return_value = True
    settings = MagicMock(sharepoint_webhook_client_state=CLIENT_STATE)
    with patch(
        "eneo.integration.infrastructure.sharepoint_webhook_service.get_settings",
        return_value=settings,
    ):
        service = SharepointWebhookService(
            session=session,
            oauth_token_repo=AsyncMock(),
            job_repo=AsyncMock(),
            user_repo=AsyncMock(),
            change_key_service=change_keys,
            sharepoint_subscription_repo=subscription_repo,
        )

    container = MagicMock()
    container.session.return_value = session
    container.sharepoint_webhook_service.return_value = service
    app = FastAPI()
    app.include_router(router, prefix="/integrations")
    for route in router.routes:
        if isinstance(route, APIRoute):
            for dependency in route.dependant.dependencies:
                if getattr(dependency.call, "__name__", "") == "_get_container":
                    app.dependency_overrides[dependency.call] = lambda: container

    job_service = AsyncMock()
    with patch(
        "eneo.integration.infrastructure.sharepoint_webhook_service.JobService",
        return_value=job_service,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield WebhookApi(
                client, service, session, subscription_repo, subscription, job_service
            )


def test_the_webhook_opens_no_transaction_before_the_body_is_read():
    for route in router.routes:
        if isinstance(route, APIRoute) and route.path.endswith("/webhook/"):
            if "POST" in route.methods:
                names = {
                    getattr(sub.call, "__name__", "")
                    for dependency in route.dependant.dependencies
                    for sub in dependency.dependencies
                }
                assert "get_session" in names
                assert "get_session_with_transaction" not in names
                return
    raise AssertionError("POST webhook route not found")


async def test_a_body_exactly_at_the_cap_is_accepted(api):
    body = (
        b'{"value":[]' + b" " * (MAX_WEBHOOK_BODY_BYTES - len(b'{"value":[]}')) + b"}"
    )
    assert len(body) == MAX_WEBHOOK_BODY_BYTES

    response = await api.client.post(
        WEBHOOK, content=body, headers={"content-type": "application/json"}
    )

    assert response.status_code == 202


def _notification(subscription_id: str = "sub-known") -> dict[str, object]:
    return {
        "subscriptionId": subscription_id,
        "clientState": CLIENT_STATE,
        "resource": "sites/site-1/drives/drive-1/root",
        "changeType": "updated",
        "resourceData": {"id": "item-1", "changeKey": "ck-1"},
    }


def _knowledge_rows(count: int):
    rows = []
    for _ in range(count):
        knowledge = MagicMock()
        knowledge.id = uuid4()
        knowledge.site_id = "site-1"
        knowledge.drive_id = None
        knowledge.resource_type = "site"
        knowledge.folder_id = None
        knowledge.folder_path = None
        knowledge.selected_item_type = "site_root"
        knowledge.delta_token = None
        knowledge.name = "Knowledge"
        user_integration = MagicMock()
        user_integration.id = uuid4()
        user_integration.user_id = uuid4()
        user_integration.tenant_id = uuid4()
        user_integration.auth_type = "user_oauth"
        rows.append((knowledge, user_integration))
    return rows


@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_handshake_echoes_the_validation_token_as_plain_text(api, method):
    response = await api.client.request(
        method, WEBHOOK, params={"validationToken": "abc 123"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "abc 123"


@pytest.mark.parametrize(
    "body, headers",
    [
        pytest.param(
            b"{not json", {"content-type": "application/json"}, id="malformed"
        ),
        pytest.param(b"[]", {"content-type": "application/json"}, id="not-an-object"),
        pytest.param(
            json.dumps({"value": "nope"}).encode(),
            {"content-type": "application/json"},
            id="value-not-a-list",
        ),
        pytest.param(
            b"{" + b" " * MAX_WEBHOOK_BODY_BYTES + b"}",
            {"content-type": "application/json"},
            id="oversized-body",
        ),
        pytest.param(
            b"{}",
            {"content-type": "application/json", "content-length": str(10**9)},
            id="oversized-declared",
        ),
    ],
)
async def test_bad_bodies_are_refused_before_any_lookup(api, body, headers):
    response = await api.client.post(WEBHOOK, content=body, headers=headers)

    assert response.status_code == 400
    assert "detail" in response.json()
    api.subscription_repo.get_by_subscription_id.assert_not_called()
    api.session.begin.assert_not_called()
    api.session.execute.assert_not_called()


async def test_unknown_subscription_is_acknowledged_but_ignored(api):
    response = await api.client.post(
        WEBHOOK, json={"value": [_notification("sub-unknown")]}
    )

    assert response.status_code == 202
    api.session.execute.assert_not_called()
    api.job_service.queue_job.assert_not_awaited()


async def test_valid_notification_queues_exactly_the_referencing_knowledge(api):
    result = MagicMock()
    result.all.return_value = _knowledge_rows(2)
    api.session.execute.return_value = result
    api.service.oauth_token_repo.one_or_none.return_value = MagicMock(id=uuid4())
    api.service.user_repo.get_user_by_id.return_value = MagicMock(id=uuid4())

    response = await api.client.post(WEBHOOK, json={"value": [_notification()]})

    assert response.status_code == 202
    api.session.begin.assert_called_once()
    statement = api.session.execute.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert f"sharepoint_subscription_id = '{api.subscription.id.hex}'" in sql
    queued = [
        call.kwargs["task_params"] for call in api.job_service.queue_job.await_args_list
    ]
    assert {params.integration_knowledge_id for params in queued} == {
        knowledge.id for knowledge, _ in result.all.return_value
    }
    assert api.subscription.last_webhook_received_at is not None
