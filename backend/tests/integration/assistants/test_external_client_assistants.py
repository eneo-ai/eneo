"""Assistants offered to other clients, and the context such a client sends.

``GET /assistants/external/`` lists what another client may offer the caller:
assistants a space admin has made available, that are published, and that the
caller may read under the ordinary space rule. ``POST /conversations/`` takes
``context`` apart from the question: it is stored as a quote that opens the
question, while the conversation's name and inject-mode retrieval use the
question alone.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import psycopg2
import pytest
import sqlalchemy as sa

from eneo.ai_models.completion_models.completion_model import (
    Completion,
    CompletionModelResponse,
    ResponseType,
)
from eneo.assistants.references import ReferencesService
from eneo.audit.application import audit_service as audit_service_module
from eneo.completion_models.infrastructure.completion_service import CompletionService
from eneo.database.database import sessionmanager
from eneo.database.tables.assistant_table import Assistants, AssistantsGroups
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import SpacesCompletionModels, SpacesUsers
from eneo.main.config import get_settings, set_settings
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.services.service import DatastoreResult
from eneo.users.user import UserAdd, UserInDB, UserState
from init_db import add_tenant_user
from tests.integration.test_federation_tenant_admin import SECRET, _idp, _register

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

LISTING = "/api/v1/assistants/external/"
CLIENT = "operator-client"
API = "eneo-api"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _user(db_container, tenant_id: UUID, *permissions: Permission) -> UserInDB:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"external-{uuid4().hex[:8]}",
                permissions=list(permissions),
                tenant_id=tenant_id,
            )
        )
        return await container.user_repo().add(
            UserAdd(
                email=f"external-{uuid4().hex[:8]}@example.com",
                username=f"external_{uuid4().hex[:8]}",
                state=UserState.ACTIVE,
                tenant_id=tenant_id,
                roles=[ModelId(id=role.id)],
            )
        )


async def _token(db_container, user: UserInDB) -> str:
    async with db_container() as container:
        return container.auth_service().create_access_token_for_user(user)


async def _join(space_id: str, user: UserInDB, role: str) -> None:
    async with sessionmanager.session() as db, db.begin():
        await db.execute(
            sa.insert(SpacesUsers).values(
                space_id=UUID(space_id), user_id=user.id, role=role
            )
        )


@pytest.fixture
async def admin_headers(
    admin_user_api_key, transcription_model_factory, db_container
) -> dict[str, str]:
    async with db_container() as container:
        await transcription_model_factory(
            container.session(), "fixture-whisper", is_default=True
        )
    return {"X-API-Key": admin_user_api_key.key}


@pytest.fixture
async def space(
    client, admin_headers, db_container, completion_model_factory
) -> dict[str, str]:
    """A shared space with a completion model its assistants can use."""
    created = await client.post(
        "/api/v1/spaces/",
        json={"name": f"Bygglov {uuid4().hex[:6]}"},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    async with db_container() as container:
        session = container.session()
        model = await completion_model_factory(
            session, f"external-{uuid4().hex[:8]}", is_default=True
        )
        session.add(
            SpacesCompletionModels(
                space_id=UUID(created.json()["id"]), completion_model_id=model.id
            )
        )
        model_id = str(model.id)
    return {
        "id": created.json()["id"],
        "name": created.json()["name"],
        "model": model_id,
    }


async def _assistant(
    client,
    headers: dict[str, str],
    space: dict[str, str],
    name: str,
    *,
    published: bool = True,
    external: bool = True,
) -> str:
    created = await client.post(
        "/api/v1/assistants/",
        json={"name": name, "space_id": space["id"]},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    assistant_id = created.json()["id"]
    assert created.json()["external_clients_enabled"] is False
    body: dict[str, Any] = {
        "completion_model": {"id": space["model"]},
        "description": f"Om {name}",
    }
    if external:
        body["external_clients_enabled"] = True
    updated = await client.post(
        f"/api/v1/assistants/{assistant_id}/", json=body, headers=headers
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["external_clients_enabled"] is external
    if published:
        publish = await client.post(
            f"/api/v1/assistants/{assistant_id}/publish/?published=true",
            headers=headers,
        )
        assert publish.status_code == 200, publish.text
    return assistant_id


@pytest.fixture
async def member(db_container, admin_user, space, patch_auth_service_jwt) -> UserInDB:
    """A person who may use assistants and views the space."""
    user = await _user(db_container, admin_user.tenant_id, Permission.ASSISTANTS)
    await _join(space["id"], user, "viewer")
    return user


@pytest.fixture
async def other_tenant_token(
    db_container, test_settings, patch_auth_service_jwt
) -> str:
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    email = f"other-{uuid4().hex[:8]}@example.com"
    add_tenant_user(
        conn,
        tenant_name=f"other_tenant_{uuid4().hex[:8]}",
        quota_limit=1000000,
        user_name=f"other_{uuid4().hex[:8]}",
        user_email=email,
        user_password="TenantFixturePass123!",
    )
    conn.close()
    async with db_container() as container:
        user = await container.user_repo().get_user_by_email(email)
    return await _token(db_container, user)


async def _listed(client, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = await client.get(LISTING, headers=headers)
    assert response.status_code == 200, response.text
    assert set(response.json()) == {"items"}
    return response.json()["items"]


async def test_an_anonymous_caller_is_refused(client, space, admin_headers):
    await _assistant(client, admin_headers, space, "Bygglovshjälpen")

    response = await client.get(LISTING)

    assert response.status_code == 401, response.text


async def test_a_member_is_offered_the_available_published_assistant_and_no_more(
    client, db_container, space, admin_headers, member
):
    offered = await _assistant(client, admin_headers, space, "Bygglovshjälpen")
    await _assistant(client, admin_headers, space, "Inte delad", external=False)
    await _assistant(client, admin_headers, space, "Utkast", published=False)

    items = await _listed(client, _bearer(await _token(db_container, member)))

    # Exactly these fields: no prompt, knowledge or model leaves Eneo here.
    assert items == [
        {
            "id": offered,
            "name": "Bygglovshjälpen",
            "description": "Om Bygglovshjälpen",
            "space": {"id": space["id"], "name": space["name"]},
        }
    ]


async def test_unpublishing_or_withdrawing_the_assistant_stops_the_offer(
    client, db_container, space, admin_headers, member
):
    assistant_id = await _assistant(client, admin_headers, space, "Bygglovshjälpen")
    headers = _bearer(await _token(db_container, member))
    assert [item["id"] for item in await _listed(client, headers)] == [assistant_id]

    unpublished = await client.post(
        f"/api/v1/assistants/{assistant_id}/publish/?published=false",
        headers=admin_headers,
    )
    assert unpublished.status_code == 200, unpublished.text
    assert await _listed(client, headers) == []

    republished = await client.post(
        f"/api/v1/assistants/{assistant_id}/publish/?published=true",
        headers=admin_headers,
    )
    assert republished.status_code == 200, republished.text
    withdrawn = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"external_clients_enabled": False},
        headers=admin_headers,
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["external_clients_enabled"] is False
    assert await _listed(client, headers) == []


async def test_an_assistant_without_a_completion_model_is_not_offered(
    client, db_container, space, admin_headers, member
):
    assistant_id = await _assistant(client, admin_headers, space, "Utan modell")
    async with sessionmanager.session() as db, db.begin():
        await db.execute(
            sa.update(Assistants)
            .where(Assistants.id == UUID(assistant_id))
            .values(completion_model_id=None)
        )

    assert await _listed(client, _bearer(await _token(db_container, member))) == []


async def test_a_person_outside_the_space_is_offered_nothing(
    client, db_container, admin_user, space, admin_headers, patch_auth_service_jwt
):
    await _assistant(client, admin_headers, space, "Bygglovshjälpen")
    outsider = await _user(db_container, admin_user.tenant_id, Permission.ASSISTANTS)

    assert await _listed(client, _bearer(await _token(db_container, outsider))) == []


async def test_a_member_without_the_assistants_permission_is_offered_nothing(
    client, db_container, admin_user, space, admin_headers, patch_auth_service_jwt
):
    # The ordinary read rule: a space role alone does not open assistants.
    await _assistant(client, admin_headers, space, "Bygglovshjälpen")
    person = await _user(db_container, admin_user.tenant_id, Permission.PERSONAL_CHAT)
    await _join(space["id"], person, "viewer")

    assert await _listed(client, _bearer(await _token(db_container, person))) == []


async def test_another_tenant_is_offered_nothing(
    client, space, admin_headers, other_tenant_token
):
    await _assistant(client, admin_headers, space, "Bygglovshjälpen")

    assert await _listed(client, _bearer(other_tenant_token)) == []


async def test_only_a_space_admin_makes_an_assistant_available(
    client, db_container, admin_user, space, admin_headers, patch_auth_service_jwt
):
    assistant_id = await _assistant(
        client, admin_headers, space, "Bygglovshjälpen", external=False
    )
    editor = await _user(db_container, admin_user.tenant_id, Permission.ASSISTANTS)
    await _join(space["id"], editor, "editor")
    headers = _bearer(await _token(db_container, editor))

    refused = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"external_clients_enabled": True},
        headers=headers,
    )
    renamed = await client.post(
        f"/api/v1/assistants/{assistant_id}/",
        json={"name": "Bygglov"},
        headers=headers,
    )

    assert refused.status_code == 403, refused.text
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["external_clients_enabled"] is False


async def test_a_default_assistant_cannot_be_made_available(
    client, space, admin_headers
):
    read = await client.get(f"/api/v1/spaces/{space['id']}/", headers=admin_headers)
    assert read.status_code == 200, read.text
    default_assistant = read.json()["default_assistant"]["id"]

    response = await client.post(
        f"/api/v1/assistants/{default_assistant}/",
        json={"external_clients_enabled": True},
        headers=admin_headers,
    )

    assert response.status_code == 400, response.text


@pytest.fixture
async def provider_token(
    client, super_admin_token, fake_idp, test_tenant, member, monkeypatch, db_container
) -> AsyncIterator[str]:
    """The member's access token from the tenant's identity provider, with
    Eneo accepting such tokens as a resource server."""

    async def enqueue(task, job_id, params):  # noqa: ARG001
        return None

    # Binding the identity is audited through the queue; no worker runs here.
    monkeypatch.setattr(audit_service_module.job_manager, "enqueue", enqueue)
    idp = _idp(f"external-{uuid4().hex[:8]}")
    provider = fake_idp(
        issuer=idp["issuer"],
        client_id=CLIENT,
        client_secret=SECRET,
        token_claims={"email": member.email},
    )
    await _register(
        client,
        super_admin_token,
        test_tenant.id,
        idp,
        canonical_public_origin="https://test.local",
    )
    current = get_settings()
    set_settings(
        current.model_copy(
            update={
                "oidc_resource_server_enabled": True,
                "oidc_accepted_issuer": provider.issuer,
                "oidc_accepted_audience": API,
                # The keys come from the issuer's own discovery here, whatever
                # the environment the tests run in says.
                "oidc_accepted_jwks_uri": None,
                "oidc_tenant_id": str(test_tenant.id),
            }
        )
    )
    try:
        token = provider.access_token(
            audience=API,
            client_id=CLIENT,
            email=member.email,
            sub=f"person-{uuid4().hex[:8]}",
        )
        # A token's first use binds the identity to the account, which
        # writes. Done here so the listing is seen to change nothing.
        async with db_container() as container:
            await container.user_service().authenticate(token=token)
        yield token
    finally:
        set_settings(current)


async def test_an_identity_provider_access_token_is_offered_the_same(
    raw_client, client, space, admin_headers, provider_token
):
    offered = await _assistant(client, admin_headers, space, "Bygglovshjälpen")

    response = await raw_client.get(LISTING, headers=_bearer(provider_token))

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [offered]


# Context sent with a question.


@pytest.fixture
def model_calls(monkeypatch) -> dict[str, list[str]]:
    """What the model was sent and what knowledge was searched with."""
    calls: dict[str, list[str]] = {"model": [], "retrieval": []}

    async def fake_get_response(self: CompletionService, **kwargs: Any):
        calls["model"].append(kwargs["text_input"])
        return CompletionModelResponse(
            completion=Completion(text="answer", response_type=ResponseType.TEXT),
            model=kwargs["model"],
            extended_logging=None,
            total_token_count=1,
            usage=None,
        )

    async def fake_get_references(self: ReferencesService, **kwargs: Any):
        calls["retrieval"].append(kwargs["question"])
        return DatastoreResult(chunks=[], no_duplicate_chunks=[], info_blobs=[])

    monkeypatch.setattr(CompletionService, "get_response", fake_get_response)
    monkeypatch.setattr(ReferencesService, "get_references", fake_get_references)
    return calls


async def _with_injected_knowledge(
    client, headers: dict[str, str], space: dict[str, str], assistant_id: str
) -> None:
    group = await client.post(
        f"/api/v1/spaces/{space['id']}/knowledge/groups/",
        json={"name": "Riktlinjer"},
        headers=headers,
    )
    assert group.status_code == 201, group.text
    async with sessionmanager.session() as db, db.begin():
        await db.execute(
            sa.update(Assistants)
            .where(Assistants.id == UUID(assistant_id))
            .values(knowledge_mode="inject")
        )
        db.add(
            AssistantsGroups(
                assistant_id=UUID(assistant_id), group_id=UUID(group.json()["id"])
            )
        )


CONTEXT = [
    {"label": "Ärende BN 2026-104", "text": "Ansökan om bygglov\nför garage"},
    {"label": "Kalender", "text": "Syn på plats 12 maj"},
]
QUESTION = "Vad saknas i ansökan?"
COMPOSED = (
    "> Ansökan om bygglov\n> för garage\n> (Ärende BN 2026-104)\n>\n"
    "> Syn på plats 12 maj\n> (Kalender)\n\nVad saknas i ansökan?"
)


async def test_context_is_stored_as_a_quote_and_the_question_alone_names_and_retrieves(
    client, space, admin_headers, model_calls
):
    assistant_id = await _assistant(client, admin_headers, space, "Bygglovshjälpen")
    await _with_injected_knowledge(client, admin_headers, space, assistant_id)

    response = await client.post(
        "/api/v1/conversations/",
        json={
            "question": QUESTION,
            "assistant_id": assistant_id,
            "context": CONTEXT,
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]
    # The model reads the context; knowledge is searched with the question.
    assert model_calls == {"model": [COMPOSED], "retrieval": [QUESTION]}
    # History replays the composed question, as both frontends expect it.
    history = await client.get(
        f"/api/v1/conversations/{session_id}/", headers=admin_headers
    )
    assert history.status_code == 200, history.text
    assert [message["question"] for message in history.json()["messages"]] == [COMPOSED]
    assert history.json()["name"] == QUESTION
    async with sessionmanager.session() as db, db.begin():
        assert (
            await db.scalar(
                sa.select(Sessions.name).where(Sessions.id == UUID(session_id))
            )
            == QUESTION
        )


async def test_a_follow_up_with_context_is_stored_as_a_quote_too(
    client, space, admin_headers, model_calls
):
    assistant_id = await _assistant(client, admin_headers, space, "Bygglovshjälpen")
    await _with_injected_knowledge(client, admin_headers, space, assistant_id)
    first = await client.post(
        "/api/v1/conversations/",
        json={"question": "Hej", "assistant_id": assistant_id, "stream": False},
        headers=admin_headers,
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        "/api/v1/conversations/",
        json={
            "question": QUESTION,
            "session_id": first.json()["session_id"],
            "context": CONTEXT[:1],
            "stream": False,
        },
        headers=admin_headers,
    )

    assert second.status_code == 200, second.text
    composed = (
        "> Ansökan om bygglov\n> för garage\n> (Ärende BN 2026-104)\n\n"
        "Vad saknas i ansökan?"
    )
    # Without context the question takes the path it always took.
    assert model_calls == {"model": ["Hej", composed], "retrieval": ["Hej", QUESTION]}


async def test_context_outside_the_limits_is_refused_before_anything_is_stored(
    client, space, admin_headers, model_calls
):
    assistant_id = await _assistant(client, admin_headers, space, "Bygglovshjälpen")

    response = await client.post(
        "/api/v1/conversations/",
        json={
            "question": QUESTION,
            "assistant_id": assistant_id,
            "context": [{"label": "l", "text": "t"}] * 9,
            "stream": False,
        },
        headers=admin_headers,
    )

    assert response.status_code == 422, response.text
    assert model_calls == {"model": [], "retrieval": []}
    async with sessionmanager.session() as db, db.begin():
        assert (
            await db.scalar(
                sa.select(sa.func.count())
                .select_from(Sessions)
                .where(Sessions.assistant_id == UUID(assistant_id))
            )
            == 0
        )
