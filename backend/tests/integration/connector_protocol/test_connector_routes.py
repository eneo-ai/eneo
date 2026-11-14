"""Eneo served as a connector: the routes another system's installation calls.

An administrator adds the installation and gets a shared key. From then on a
call is answered only when it carries that key, an assertion the installation
signed for exactly this request, and the person's own identity-provider token.
The person then lists and asks the assistants they may already use that a
space admin made available to other clients, and nothing else.
"""

import json
import time
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
import sqlalchemy as sa
from cryptography.hazmat.primitives.asymmetric import rsa

from eneo.ai_models.completion_models.completion_model import Completion, ResponseType
from eneo.assistants.api.assistant_models import AssistantResponse
from eneo.assistants.assistant_service import AssistantService
from eneo.audit.application import audit_service as audit_service_module
from eneo.connector_protocol.verification import body_digest, key_digest
from eneo.database.database import sessionmanager
from eneo.database.tables.connector_installations_table import ConnectorInstallations
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.main.config import get_settings, set_settings
from eneo.questions.question import UseTools
from eneo.roles.permissions import Permission
from eneo.server.dependencies import connector_auth
from tests.integration.assistants.test_external_client_assistants import (  # noqa: F401
    _assistant,
    _join,
    _token,
    _user,
    admin_headers,
    member,
    other_tenant_token,
    provider_token,
    space,
)

BASE = "/api/v1/connector"
ADMIN = "/api/v1/admin/connector-installations/"
ASSISTANTS = f"{BASE}/clew/capabilities/eneo.assistants"
ASK = f"{BASE}/clew/ask"
KID = "installation-key-1"
ACTOR = {
    "id": "p1",
    "name": "Anna Andersson",
    "unitId": "u1",
    "unitLabel": "Bygglov",
    "role": "employee",
}


@pytest.fixture(scope="module")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def installation_keys(monkeypatch, signing_key) -> list[str]:
    """Serve the installation's public key in place of fetching it."""
    asked: list[str] = []
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    keys = {"keys": [{**jwk, "kid": KID, "alg": "RS256", "use": "sig"}]}

    async def fetched(base_url: str, kid: str) -> dict[str, Any]:  # noqa: ARG001
        asked.append(base_url)
        return keys

    monkeypatch.setattr(connector_auth, "installation_keys", fetched)
    return asked


@pytest.fixture
async def installation(client, admin_headers, installation_keys) -> dict[str, Any]:  # noqa: F811
    created = await client.post(
        ADMIN,
        json={"name": "Startsidan", "base_url": "https://start.example/"},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


def _assertion(
    key: rsa.RSAPrivateKey,
    body: bytes,
    *,
    capability: str | None,
    **changes: Any,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": "clew",
        "aud": "eneo",
        "sub": ACTOR["id"],
        "iat": now,
        "exp": now + 60,
        "jti": uuid4().hex,
        "actor": ACTOR,
        "body": body_digest(body),
        **({"capability": capability} if capability is not None else {}),
        **changes,
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": KID})


async def _post(
    client,
    path: str,
    payload: dict[str, Any],
    *,
    key: str | None,
    signing_key: rsa.RSAPrivateKey,
    token: str | None = None,
    sent: bytes | None = None,
    **claims: Any,
):
    """A call as the installation makes it: the assertion is over the bytes of
    ``payload``; ``sent`` posts other bytes than the ones signed."""
    body = json.dumps({"actor": ACTOR, **payload}).encode()
    capability = claims.pop(
        "capability", path.rsplit("/", 1)[1] if "/capabilities/" in path else None
    )
    headers = {
        "Authorization": "Bearer "
        + _assertion(signing_key, body, capability=capability, **claims),
        "Content-Type": "application/json",
    }
    if key is not None:
        headers["X-Clew-Connector-Key"] = key
    if token is not None:
        headers["X-Clew-Delegated-Token"] = token
    return await client.post(
        path, content=body if sent is None else sent, headers=headers
    )


def _events(text: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data:") :])
        for line in text.splitlines()
        if line.startswith("data:")
    ]


@pytest.fixture
def asked(monkeypatch) -> list[dict[str, Any]]:
    """Replace the model call with a canned answer that cites nothing.

    Everything before it (both credentials, the offer check, session
    ownership) and after it (the event stream) runs for real.
    """
    calls: list[dict[str, Any]] = []

    async def fake_ask(self, *, question, assistant_id, session_id=None, **kwargs):
        calls.append(
            {"question": question, "assistant_id": assistant_id, **kwargs}
            | {"session_id": session_id, "user_id": self.user.id}
        )
        if session_id is None:
            session = await self.session_service.create_session(
                name=question, assistant_id=assistant_id
            )
        else:
            session = await self.session_service.get_session_by_uuid(
                id=session_id, assistant_id=assistant_id
            )
        question_id = await self.session_service.question_repo.session.scalar(
            sa.insert(Questions)
            .values(
                session_id=session.id,
                tenant_id=self.user.tenant_id,
                assistant_id=assistant_id,
                question=question,
                answer="Du har 25 dagar.",
                num_tokens_question=1,
                num_tokens_answer=1,
            )
            .returning(Questions.id)
        )

        async def answer():
            for text in ("Du har ", "25 dagar."):
                yield Completion(text=text, response_type=ResponseType.TEXT)

        return AssistantResponse.model_construct(
            session=session,
            question=question,
            question_id=question_id,
            files=[],
            answer=answer(),
            info_blobs=[],
            completion_model=None,
            tools=UseTools(assistants=[]),
        )

    monkeypatch.setattr(AssistantService, "ask", fake_ask)
    return calls


@pytest.fixture
def audited(monkeypatch) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    async def enqueue(task, job_id, params):  # noqa: ARG001
        entries.append(params)

    monkeypatch.setattr(audit_service_module.job_manager, "enqueue", enqueue)
    return entries


def _denied(response, status: int) -> None:
    assert response.status_code == status, response.text
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == "denied"


# The administrator's side.


async def test_the_surface_is_absent_until_an_installation_is_added(
    client,
    admin_headers,  # noqa: F811
    installation_keys,
):
    before = await client.get(f"{BASE}/clew/manifest")
    assert before.status_code == 404, before.text
    assert before.json()["error"]["code"] == "not-found"

    created = await client.post(
        ADMIN,
        json={"name": "Startsidan", "base_url": "https://start.example"},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text

    manifest = await client.get(f"{BASE}/clew/manifest")
    assert manifest.status_code == 200, manifest.text
    body = manifest.json()
    assert (body["protocol"], body["id"], body["kind"]) == (3, "eneo", "passthrough")
    assert body["delegation"] == {"audience": "eneo"}
    assert body["assistants"] == {"list": "eneo.assistants"}
    assert [c["name"] for c in body["capabilities"]] == ["eneo.assistants"]
    assert body["scan"] is False and body["areas"] == []


async def test_the_key_is_shown_once_and_only_its_digest_is_kept(
    client,
    admin_headers,  # noqa: F811
    installation,
):
    assert set(installation) == {
        "id",
        "created_at",
        "updated_at",
        "name",
        "base_url",
        "key",
    }
    assert installation["base_url"] == "https://start.example"
    assert len(installation["key"]) >= 40

    listed = await client.get(ADMIN, headers=admin_headers)
    assert listed.status_code == 200, listed.text
    assert [set(item) for item in listed.json()["items"]] == [
        {"id", "created_at", "updated_at", "name", "base_url"}
    ]
    async with sessionmanager.session() as db, db.begin():
        stored = await db.scalar(
            sa.select(ConnectorInstallations.key_digest).where(
                ConnectorInstallations.id == UUID(installation["id"])
            )
        )
    assert stored == key_digest(installation["key"])
    assert installation["key"] not in listed.text


async def test_only_a_tenant_administrator_manages_installations(
    client,
    db_container,
    member,  # noqa: F811
    installation,
):
    headers = {"Authorization": f"Bearer {await _token(db_container, member)}"}

    listed = await client.get(ADMIN, headers=headers)
    added = await client.post(
        ADMIN,
        json={"name": "Egen", "base_url": "https://mine.example"},
        headers=headers,
    )
    removed = await client.delete(f"{ADMIN}{installation['id']}/", headers=headers)

    assert (listed.status_code, added.status_code, removed.status_code) == (
        403,
        403,
        403,
    )


async def test_an_installation_of_another_tenant_cannot_be_removed(
    client,
    installation,
    other_tenant_token,  # noqa: F811
):
    response = await client.delete(
        f"{ADMIN}{installation['id']}/",
        headers={"Authorization": f"Bearer {other_tenant_token}"},
    )

    assert response.status_code == 404, response.text


@pytest.mark.parametrize(
    "base_url",
    ["http://start.example", "https://user@start.example", "start.example", ""],
)
async def test_an_address_that_cannot_be_trusted_is_refused(
    client,
    admin_headers,  # noqa: F811
    base_url,
):
    response = await client.post(
        ADMIN, json={"name": "Startsidan", "base_url": base_url}, headers=admin_headers
    )

    assert response.status_code == 422, response.text


async def test_the_same_address_is_added_once(
    client,
    admin_headers,  # noqa: F811
    installation,
):
    response = await client.post(
        ADMIN,
        json={"name": "Igen", "base_url": installation["base_url"]},
        headers=admin_headers,
    )

    assert response.status_code == 400, response.text


async def test_adding_and_removing_are_audited_without_the_key(
    client,
    admin_headers,  # noqa: F811
    installation_keys,
    audited,
):
    created = await client.post(
        ADMIN,
        json={"name": "Startsidan", "base_url": "https://start.example"},
        headers=admin_headers,
    )
    removed = await client.delete(
        f"{ADMIN}{created.json()['id']}/", headers=admin_headers
    )

    assert removed.status_code == 204, removed.text
    assert [
        entry["action"] for entry in audited if entry["action"].startswith("connector_")
    ] == ["connector_installation_added", "connector_installation_removed"]
    assert created.json()["key"] not in json.dumps(audited, default=str)
    assert key_digest(created.json()["key"]) not in json.dumps(audited, default=str)


# The calling installation's own credentials.


async def test_a_person_lists_the_assistants_they_may_ask(
    raw_client,
    client,
    space,  # noqa: F811
    admin_headers,  # noqa: F811
    installation,
    installation_keys,
    provider_token,  # noqa: F811
    signing_key,
):
    offered = await _assistant(client, admin_headers, space, "Bygglovshjälpen")
    await _assistant(client, admin_headers, space, "Inte delad", external=False)
    await _assistant(client, admin_headers, space, "Utkast", published=False)

    response = await _post(
        raw_client,
        ASSISTANTS,
        {"input": {}},
        key=installation["key"],
        signing_key=signing_key,
        token=provider_token,
    )

    assert response.status_code == 200, response.text
    # Exactly these fields: no prompt, knowledge, model or space leaves Eneo.
    assert response.json() == {
        "output": {
            "assistants": [
                {
                    "ref": offered,
                    "name": "Bygglovshjälpen",
                    "description": "Om Bygglovshjälpen",
                }
            ]
        }
    }
    # The keys were read from the address the administrator registered.
    assert set(installation_keys) == {"https://start.example"}


@pytest.mark.parametrize(
    "case",
    [
        "no key",
        "another key",
        "signed by another key",
        "body changed after signing",
        "signed for another capability",
        "the installation's own call",
        "expired",
        "another audience",
    ],
)
async def test_a_call_without_the_installations_credentials_gets_no_data(
    raw_client,
    client,
    space,  # noqa: F811
    admin_headers,  # noqa: F811
    installation,
    provider_token,  # noqa: F811
    signing_key,
    case,
):
    await _assistant(client, admin_headers, space, "Bygglovshjälpen")
    key: str | None = installation["key"]
    signer = signing_key
    sent: bytes | None = None
    claims: dict[str, Any] = {}
    if case == "no key":
        key = None
    elif case == "another key":
        key = "x" * len(installation["key"])
    elif case == "signed by another key":
        signer = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    elif case == "body changed after signing":
        sent = json.dumps({"actor": ACTOR, "input": {}, "about": "x"}).encode()
    elif case == "signed for another capability":
        claims = {"capability": "eneo.search"}
    elif case == "the installation's own call":
        claims = {"caller": "installation", "sub": "clew:installation"}
    elif case == "expired":
        claims = {"iat": int(time.time()) - 300, "exp": int(time.time()) - 200}
    elif case == "another audience":
        claims = {"aud": "another-connector"}

    response = await _post(
        raw_client,
        ASSISTANTS,
        {"input": {}},
        key=key,
        signing_key=signer,
        token=provider_token,
        sent=sent,
        **claims,
    )

    _denied(response, 401)
    assert "Bygglovshjälpen" not in response.text


async def test_an_assertion_for_a_capability_does_not_open_the_ask_route(
    raw_client,
    client,
    space,  # noqa: F811
    admin_headers,  # noqa: F811
    installation,
    provider_token,  # noqa: F811
    signing_key,
    asked,
):
    assistant_id = await _assistant(client, admin_headers, space, "Bygglovshjälpen")

    response = await _post(
        raw_client,
        ASK,
        {"ask": {"assistant": assistant_id, "question": "Hej"}},
        key=installation["key"],
        signing_key=signing_key,
        token=provider_token,
        capability="eneo.assistants",
    )

    _denied(response, 401)
    assert asked == []


async def test_a_removed_installation_is_refused_from_the_next_call(
    raw_client,
    client,
    admin_headers,  # noqa: F811
    installation,
    provider_token,  # noqa: F811
    signing_key,
):
    removed = await client.delete(
        f"{ADMIN}{installation['id']}/", headers=admin_headers
    )
    assert removed.status_code == 204, removed.text

    response = await _post(
        raw_client,
        ASSISTANTS,
        {"input": {}},
        key=installation["key"],
        signing_key=signing_key,
        token=provider_token,
    )

    _denied(response, 401)


# The person's credential.


async def test_without_the_persons_token_nothing_is_read(
    raw_client,
    client,
    space,  # noqa: F811
    admin_headers,  # noqa: F811
    installation,
    signing_key,
):
    await _assistant(client, admin_headers, space, "Bygglovshjälpen")

    response = await _post(
        raw_client,
        ASSISTANTS,
        {"input": {}},
        key=installation["key"],
        signing_key=signing_key,
    )

    _denied(response, 403)


async def test_eneos_own_token_is_not_a_delegated_token(
    raw_client,
    client,
    db_container,
    space,  # noqa: F811
    admin_headers,  # noqa: F811
    installation,
    member,  # noqa: F811
    provider_token,  # noqa: F811
    signing_key,
):
    await _assistant(client, admin_headers, space, "Bygglovshjälpen")

    response = await _post(
        raw_client,
        ASSISTANTS,
        {"input": {}},
        key=installation["key"],
        signing_key=signing_key,
        token=await _token(db_container, member),
    )

    _denied(response, 403)


async def test_a_person_is_refused_behind_another_tenants_installation(
    raw_client,
    client,
    space,  # noqa: F811
    admin_headers,  # noqa: F811
    installation_keys,
    other_tenant_token,  # noqa: F811
    provider_token,  # noqa: F811
    signing_key,
    db_container,
):
    await _assistant(client, admin_headers, space, "Bygglovshjälpen")
    # The other tenant's administrator trusts an installation of their own.
    created = await client.post(
        ADMIN,
        json={"name": "Grannens", "base_url": "https://neighbour.example"},
        headers={"Authorization": f"Bearer {other_tenant_token}"},
    )
    assert created.status_code == 201, created.text

    response = await _post(
        raw_client,
        ASSISTANTS,
        {"input": {}},
        key=created.json()["key"],
        signing_key=signing_key,
        token=provider_token,
    )

    _denied(response, 403)
    assert "Bygglovshjälpen" not in response.text


async def test_the_surface_needs_eneo_to_accept_identity_provider_tokens(
    raw_client,
    installation,
    provider_token,  # noqa: F811
    signing_key,
):
    current = get_settings()
    set_settings(current.model_copy(update={"oidc_resource_server_enabled": False}))
    try:
        response = await _post(
            raw_client,
            ASSISTANTS,
            {"input": {}},
            key=installation["key"],
            signing_key=signing_key,
            token=provider_token,
        )
    finally:
        set_settings(current)

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "unavailable"


async def test_an_unknown_capability_and_unexpected_input_are_refused(
    raw_client,
    installation,
    provider_token,  # noqa: F811
    signing_key,
):
    unknown = await _post(
        raw_client,
        f"{BASE}/clew/capabilities/eneo.search",
        {"input": {"query": "semester"}},
        key=installation["key"],
        signing_key=signing_key,
        token=provider_token,
    )
    with_input = await _post(
        raw_client,
        ASSISTANTS,
        {"input": {"query": "semester"}},
        key=installation["key"],
        signing_key=signing_key,
        token=provider_token,
    )

    assert unknown.status_code == 404, unknown.text
    assert unknown.json()["error"]["code"] == "not-found"
    assert with_input.status_code == 400, with_input.text
    assert with_input.json()["error"]["code"] == "invalid"


# Asking.


@pytest.fixture
def public_origin(provider_token):  # noqa: F811
    current = get_settings()
    set_settings(current.model_copy(update={"public_origin": "https://eneo.example"}))
    yield "https://eneo.example"
    set_settings(current)


async def test_a_question_is_answered_as_the_person_and_can_be_followed_up(
    raw_client,
    client,
    space,  # noqa: F811
    admin_headers,  # noqa: F811
    installation,
    member,  # noqa: F811
    provider_token,  # noqa: F811
    public_origin,
    signing_key,
    asked,
    audited,
):
    assistant_id = await _assistant(client, admin_headers, space, "Bygglovshjälpen")
    context = [{"label": "Ärende BN 2026-104", "text": "Ansökan om bygglov"}]

    first = await _post(
        raw_client,
        ASK,
        {
            "ask": {
                "assistant": assistant_id,
                "question": "Hur många dagar?",
                "context": context,
            }
        },
        key=installation["key"],
        signing_key=signing_key,
        token=provider_token,
    )

    assert first.status_code == 200, first.text
    assert first.headers["content-type"].startswith("text/event-stream")
    events = _events(first.text)
    session_id = events[-1]["session"]
    assert events == [
        {"type": "text", "delta": "Du har "},
        {"type": "text", "delta": "25 dagar."},
        {
            "type": "done",
            "session": session_id,
            "link": f"{public_origin}/dashboard/{assistant_id}/{session_id}",
        },
    ]
    # The whole assistant answered, as the person, without what the calling
    # system cannot carry: generated files and tool approvals.
    call = asked[-1]
    assert call["question"] == "Hur många dagar?"
    assert call["assistant_id"] == UUID(assistant_id)
    assert call["user_id"] == member.id
    assert call["stream"] is True
    assert call["require_tool_approval"] is False
    assert set(call["disabled_capabilities"]) == {
        "image_generation",
        "file_creation",
        "file_analysis",
        "compute",
        "charts",
    }
    assert [(item.label, item.text) for item in call["context"]] == [
        ("Ärende BN 2026-104", "Ansökan om bygglov")
    ]
    # The conversation is the person's own, in their Eneo history.
    async with sessionmanager.session() as db, db.begin():
        owner = await db.scalar(
            sa.select(Sessions.user_id).where(Sessions.id == UUID(session_id))
        )
    assert owner == member.id
    # Which installation the question came through is recorded, not its text.
    entry = next(e for e in audited if e["action"] == "connector_question_asked")
    assert entry["entity_id"] == assistant_id
    assert entry["metadata"]["extra"]["installation_id"] == installation["id"]
    assert entry["metadata"]["extra"]["session_id"] == session_id
    assert "Hur många dagar?" not in json.dumps(entry, default=str)

    second = await _post(
        raw_client,
        ASK,
        {
            "ask": {
                "assistant": assistant_id,
                "session": session_id,
                "question": "Och nästa år?",
            }
        },
        key=installation["key"],
        signing_key=signing_key,
        token=provider_token,
    )

    assert second.status_code == 200, second.text
    assert _events(second.text)[-1]["session"] == session_id
    assert asked[-1]["session_id"] == UUID(session_id)


async def test_an_assistant_that_is_not_offered_cannot_be_asked_by_its_id(
    raw_client,
    client,
    space,  # noqa: F811
    admin_headers,  # noqa: F811
    installation,
    provider_token,  # noqa: F811
    signing_key,
    asked,
):
    unflagged = await _assistant(
        client, admin_headers, space, "Inte delad", external=False
    )
    draft = await _assistant(client, admin_headers, space, "Utkast", published=False)

    for assistant_id in (unflagged, draft, str(uuid4())):
        response = await _post(
            raw_client,
            ASK,
            {"ask": {"assistant": assistant_id, "question": "Hej"}},
            key=installation["key"],
            signing_key=signing_key,
            token=provider_token,
        )

        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "not-found"
    assert asked == []


async def test_a_conversation_that_is_not_the_persons_cannot_be_continued(
    raw_client,
    client,
    db_container,
    admin_user,
    space,  # noqa: F811
    admin_headers,  # noqa: F811
    installation,
    provider_token,  # noqa: F811
    signing_key,
    asked,
):
    assistant_id = await _assistant(client, admin_headers, space, "Bygglovshjälpen")
    other = await _assistant(client, admin_headers, space, "Miljöhjälpen")
    colleague = await _user(db_container, admin_user.tenant_id, Permission.ASSISTANTS)
    await _join(space["id"], colleague, "viewer")
    async with sessionmanager.session() as db, db.begin():
        theirs = await db.scalar(
            sa.insert(Sessions)
            .values(user_id=colleague.id, assistant_id=UUID(assistant_id), name="Hej")
            .returning(Sessions.id)
        )
    own = await _post(
        raw_client,
        ASK,
        {"ask": {"assistant": other, "question": "Hej"}},
        key=installation["key"],
        signing_key=signing_key,
        token=provider_token,
    )
    own_session = _events(own.text)[-1]["session"]
    asked.clear()

    for session_id in (str(theirs), own_session, str(uuid4())):
        # A colleague's conversation, the person's own with another assistant,
        # and one that does not exist.
        response = await _post(
            raw_client,
            ASK,
            {
                "ask": {
                    "assistant": assistant_id,
                    "session": session_id,
                    "question": "Och sen?",
                }
            },
            key=installation["key"],
            signing_key=signing_key,
            token=provider_token,
        )

        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "not-found"
    assert asked == []


@pytest.mark.parametrize(
    "ask",
    [
        pytest.param({"question": ""}, id="empty question"),
        pytest.param({"question": "x" * 4001}, id="question over the limit"),
        pytest.param(
            {"question": "Hej", "context": [{"label": "l", "text": "t"}] * 9},
            id="too many context items",
        ),
        pytest.param(
            {"question": "Hej", "context": [{"label": "l", "text": "t" * 12_001}]},
            id="context text over the limit",
        ),
        pytest.param(
            {"question": "Hej", "context": [{"label": "", "text": "t"}]},
            id="context without a label",
        ),
        pytest.param({"question": "Hej", "session": "not-a-uuid"}, id="bad session"),
        pytest.param({"question": "Hej", "files": ["x"]}, id="a field it has not got"),
    ],
)
async def test_a_question_outside_the_protocols_limits_is_refused(
    raw_client,
    client,
    space,  # noqa: F811
    admin_headers,  # noqa: F811
    installation,
    provider_token,  # noqa: F811
    signing_key,
    asked,
    ask,
):
    assistant_id = await _assistant(client, admin_headers, space, "Bygglovshjälpen")

    response = await _post(
        raw_client,
        ASK,
        {"ask": {"assistant": assistant_id, **ask}},
        key=installation["key"],
        signing_key=signing_key,
        token=provider_token,
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid"
    assert asked == []


async def test_asking_without_the_persons_token_is_refused(
    raw_client,
    client,
    space,  # noqa: F811
    admin_headers,  # noqa: F811
    installation,
    signing_key,
    asked,
):
    assistant_id = await _assistant(client, admin_headers, space, "Bygglovshjälpen")

    response = await _post(
        raw_client,
        ASK,
        {"ask": {"assistant": assistant_id, "question": "Hej"}},
        key=installation["key"],
        signing_key=signing_key,
    )

    _denied(response, 403)
    assert asked == []
