"""Outbound headers through the admin API, against a real database.

Covers the secret contract across routes (storage, GET, PUT, preview, audit),
destination checks that follow the endpoint the request actually uses, audit
under concurrent edits, and the unsupported-provider-type refusal. Wire behaviour is covered by the transport
capture tests in tests/unit/model_providers/infrastructure.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text, update

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.users_table import Users
from eneo.main.config import get_settings
from eneo.model_providers.domain.model_provider_service import ModelProviderService
from eneo.model_providers.presentation.model_provider_models import (
    ModelProviderUpdate,
)
from eneo.model_providers.presentation.model_provider_router import update_provider
from eneo.scim.constants import SCIM_ENTERPRISE_USER_URN
from eneo.settings.encryption_service import EncryptionService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

BASE = "/api/v1/admin/model-providers"
ENDPOINT = "https://gateway.internal/v1"
MASK = "********"


@pytest.fixture
def auth(admin_user_api_key: Any) -> dict[str, str]:
    return {"X-API-Key": admin_user_api_key.key}


@pytest.fixture
def audit_calls(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    recorder = AsyncMock(return_value=None)
    monkeypatch.setattr(AuditService, "log_async", recorder)
    return recorder


def _audited(recorder: AsyncMock, action: ActionType) -> list[dict[str, Any]]:
    return [
        call.kwargs
        for call in recorder.await_args_list
        if call.kwargs["action"] == action
    ]


def _headers() -> list[dict[str, Any]]:
    return [
        {"name": "X-Org-Unit", "value": "{{user.department}}"},
        {
            "name": "X-Credential",
            "value": "sk-bf-aGVsbG8=",
            "encoding": "none",
            "secret": True,
        },
    ]


async def _create(
    client: Any,
    auth: dict[str, str],
    *,
    provider_type: str = "hosted_vllm",
    headers: list[dict[str, Any]] | None = None,
    config: dict[str, Any] | None = None,
    credentials: dict[str, Any] | None = None,
) -> Any:
    return await client.post(
        f"{BASE}/",
        headers=auth,
        json={
            "name": f"gateway-{uuid4().hex[:8]}",
            "provider_type": provider_type,
            "credentials": credentials if credentials is not None else {},
            "config": config if config is not None else {"endpoint": ENDPOINT},
            "outbound_headers": _headers() if headers is None else headers,
        },
    )


async def _stored(db_session: Any, provider_id: str) -> list[dict[str, Any]]:
    async with db_session() as session:
        row = (
            await session.execute(
                select(ModelProviders).where(ModelProviders.id == UUID(provider_id))
            )
        ).scalar_one()
        return list(row.outbound_headers or [])


def _by_name(headers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {header["name"]: header for header in headers}


def _kept(public: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What an editor sends back: every header, secret values omitted."""
    return [
        {key: value for key, value in header.items() if key != "value"}
        if header["secret"]
        else header
        for header in public
    ]


def _re_entered(public: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {**header, "value": "sk-bf-new"} if header["secret"] else header
        for header in public
    ]


async def test_options_list_the_registry_and_supported_types(client, auth):
    response = await client.get(f"{BASE}/outbound-headers/options/", headers=auth)

    assert response.status_code == 200
    body = response.json()
    assert body["supported_provider_types"] == ["hosted_vllm", "vllm"]
    assert {value["token"] for value in body["dynamic_values"]} == {
        "user.employeeNumber",
        "user.externalId",
        "user.costCenter",
        "user.department",
        "user.division",
        "user.organization",
    }


async def test_secret_is_encrypted_at_rest_and_masked_on_every_read(
    client, auth, db_session, encryption_service, audit_calls
):
    created = await _create(client, auth)
    assert created.status_code == 200, created.text
    provider = created.json()

    for body in (
        provider,
        (await client.get(f"{BASE}/{provider['id']}/", headers=auth)).json(),
    ):
        headers = _by_name(body["outbound_headers"])
        assert headers["X-Credential"]["value"] == MASK
        assert headers["X-Org-Unit"]["value"] == "{{user.department}}"
        assert "sk-bf-aGVsbG8=" not in str(body)

    stored = _by_name(await _stored(db_session, provider["id"]))
    assert stored["X-Credential"]["value"].startswith("enc:fernet:v1:")
    assert (
        encryption_service.decrypt(stored["X-Credential"]["value"]) == "sk-bf-aGVsbG8="
    )
    assert stored["X-Org-Unit"]["value"] == "{{user.department}}"

    [audit] = _audited(audit_calls, ActionType.MODEL_PROVIDER_HEADERS_UPDATED)
    assert "sk-bf-aGVsbG8=" not in str(audit)


async def test_get_put_get_round_trip_keeps_the_secret(
    client, auth, db_session, encryption_service, audit_calls
):
    provider = (await _create(client, auth)).json()
    ciphertext = _by_name(await _stored(db_session, provider["id"]))["X-Credential"][
        "value"
    ]

    for _ in range(2):
        current = (await client.get(f"{BASE}/{provider['id']}/", headers=auth)).json()
        # What a client does: send entries back, omitting the masked value.
        writes = [
            {
                key: value
                for key, value in header.items()
                if not (header["secret"] and key == "value")
            }
            for header in current["outbound_headers"]
        ]
        response = await client.put(
            f"{BASE}/{provider['id']}/", headers=auth, json={"outbound_headers": writes}
        )
        assert response.status_code == 200, response.text

    stored = _by_name(await _stored(db_session, provider["id"]))["X-Credential"][
        "value"
    ]
    assert stored == ciphertext
    assert encryption_service.decrypt(stored) == "sk-bf-aGVsbG8="


async def test_submitting_the_mask_back_is_rejected(
    client, auth, db_session, audit_calls
):
    provider = (await _create(client, auth)).json()
    before = await _stored(db_session, provider["id"])

    response = await client.put(
        f"{BASE}/{provider['id']}/",
        headers=auth,
        json={"outbound_headers": provider["outbound_headers"]},  # includes the mask
    )

    assert response.status_code == 400
    assert await _stored(db_session, provider["id"]) == before


async def test_declassifying_without_the_value_is_rejected(
    client, auth, db_session, audit_calls
):
    provider = (await _create(client, auth)).json()
    before = await _stored(db_session, provider["id"])
    writes = [
        {
            "id": header["id"],
            "name": header["name"],
            "encoding": header["encoding"],
            "secret": False,
        }
        if header["secret"]
        else header
        for header in provider["outbound_headers"]
    ]

    response = await client.put(
        f"{BASE}/{provider['id']}/", headers=auth, json={"outbound_headers": writes}
    )

    assert response.status_code == 400
    assert "re-enter the value" in response.text
    assert await _stored(db_session, provider["id"]) == before


async def test_unsupported_provider_type_is_refused(client, auth, audit_calls):
    response = await _create(
        client,
        auth,
        provider_type="openai",
        credentials={"api_key": "sk-test-12345678"},
    )

    assert response.status_code == 400
    assert "does not support outbound headers" in response.text


async def test_destination_check_follows_an_endpoint_shadowed_in_credentials(
    client, auth, monkeypatch, audit_calls
):
    """The request resolves `endpoint` from credentials before config; the
    check must validate the same value, not the visible config one."""
    monkeypatch.setattr(
        get_settings(), "outbound_headers_allowed_destinations", [ENDPOINT]
    )

    visible_only = await _create(client, auth)
    shadowed = await _create(
        client, auth, credentials={"endpoint": "https://elsewhere.example/v1"}
    )

    assert visible_only.status_code == 200, visible_only.text
    assert shadowed.status_code == 400
    assert "allowed destinations" in shadowed.text


async def test_moving_the_endpoint_is_rechecked_and_audited(
    client, auth, monkeypatch, audit_calls
):
    monkeypatch.setattr(
        get_settings(),
        "outbound_headers_allowed_destinations",
        [ENDPOINT, "https://gateway-2.internal/v1"],
    )
    provider = (await _create(client, auth)).json()

    blocked = await client.put(
        f"{BASE}/{provider['id']}/",
        headers=auth,
        json={"config": {"endpoint": "https://unapproved.example/v1"}},
    )
    moved = await client.put(
        f"{BASE}/{provider['id']}/",
        headers=auth,
        json={
            "config": {"endpoint": "https://gateway-2.internal/v1"},
            "outbound_headers": _re_entered(provider["outbound_headers"]),
        },
    )

    assert blocked.status_code == 400
    assert moved.status_code == 200, moved.text
    [audit] = _audited(audit_calls, ActionType.MODEL_PROVIDER_DESTINATION_CHANGED)
    assert audit["metadata"]["changes"]["endpoint"] == {
        "old": ENDPOINT,
        "new": "https://gateway-2.internal/v1",
    }


async def test_destination_audit_never_keeps_url_credentials(client, auth, audit_calls):
    # Credentials are only refused while headers exist, so the endpoint before
    # the edit that adds them may still carry some.
    provider = (
        await _create(
            client,
            auth,
            headers=[],
            config={"endpoint": "https://user:pass@gateway-old.internal/v1"},
        )
    ).json()

    response = await client.put(
        f"{BASE}/{provider['id']}/",
        headers=auth,
        json={"config": {"endpoint": ENDPOINT}, "outbound_headers": _headers()},
    )

    assert response.status_code == 200, response.text
    [audit] = _audited(audit_calls, ActionType.MODEL_PROVIDER_DESTINATION_CHANGED)
    assert audit["metadata"]["changes"]["endpoint"] == {
        "old": "https://gateway-old.internal/v1",
        "new": ENDPOINT,
    }
    assert "user:pass" not in str(audit)


async def test_a_secret_header_does_not_follow_the_endpoint(
    client, auth, db_session, audit_calls
):
    """The provider has no API key; only the secret header authenticates it.
    Like a key, that secret must be entered again for a new destination."""
    provider = (await _create(client, auth)).json()
    before = await _stored(db_session, provider["id"])

    for body in (
        {"config": {"endpoint": "https://gateway-2.internal/v1"}},
        {
            "config": {"endpoint": "https://gateway-2.internal/v1"},
            "outbound_headers": _kept(provider["outbound_headers"]),
        },
        # The request resolves `endpoint` from credentials before config.
        {"credentials": {"endpoint": "https://gateway-2.internal/v1"}},
    ):
        response = await client.put(
            f"{BASE}/{provider['id']}/", headers=auth, json=body
        )
        assert response.status_code == 400, response.text
        assert "X-Credential" in response.text

    current = (await client.get(f"{BASE}/{provider['id']}/", headers=auth)).json()
    assert current["config"]["endpoint"] == ENDPOINT
    assert await _stored(db_session, provider["id"]) == before
    assert _audited(audit_calls, ActionType.MODEL_PROVIDER_DESTINATION_CHANGED) == []


@pytest.mark.parametrize("re_enter", [True, False])
async def test_re_entering_or_removing_the_secret_allows_the_move(
    client, auth, db_session, encryption_service, audit_calls, re_enter: bool
):
    provider = (await _create(client, auth)).json()
    writes = (
        _re_entered(provider["outbound_headers"])
        if re_enter
        else [header for header in provider["outbound_headers"] if not header["secret"]]
    )

    response = await client.put(
        f"{BASE}/{provider['id']}/",
        headers=auth,
        json={
            "config": {"endpoint": "https://gateway-2.internal/v1"},
            "outbound_headers": writes,
        },
    )

    assert response.status_code == 200, response.text
    stored = _by_name(await _stored(db_session, provider["id"]))
    if re_enter:
        assert encryption_service.decrypt(stored["X-Credential"]["value"]) == (
            "sk-bf-new"
        )
    else:
        assert set(stored) == {"X-Org-Unit"}


@pytest.mark.parametrize("keep_headers", [True, False])
async def test_a_key_that_no_longer_decrypts_can_be_replaced(
    client, auth, db_session, monkeypatch, audit_calls, keep_headers: bool
):
    """After ENCRYPTION_KEY changes, the stored key no longer decrypts. The
    edit replacing it must commit: the destination is resolved without it."""
    provider = (
        await _create(
            client,
            auth,
            headers=[{"name": "X-Org-Unit", "value": "{{user.department}}"}],
            credentials={"api_key": "sk-old-12345678"},
        )
    ).json()
    new_key = Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "encryption_key", new_key)

    response = await client.put(
        f"{BASE}/{provider['id']}/",
        headers=auth,
        json={
            "credentials": {"api_key": "sk-new-12345678"},
            "outbound_headers": provider["outbound_headers"] if keep_headers else [],
        },
    )

    assert response.status_code == 200, response.text
    async with db_session() as session:
        row = (
            await session.execute(
                select(ModelProviders).where(ModelProviders.id == UUID(provider["id"]))
            )
        ).scalar_one()
        assert EncryptionService(new_key).decrypt(row.credentials["api_key"]) == (
            "sk-new-12345678"
        )
        assert [header["name"] for header in row.outbound_headers or []] == (
            ["X-Org-Unit"] if keep_headers else []
        )
    assert _audited(audit_calls, ActionType.MODEL_PROVIDER_DESTINATION_CHANGED) == []


async def test_header_name_ending_in_a_newline_is_refused(
    client, auth, db_session, audit_calls
):
    invalid = [{"name": "X-Test\n", "value": "eu-north"}]
    listed = len((await client.get(f"{BASE}/", headers=auth)).json())

    created = await _create(client, auth, headers=invalid)

    assert created.status_code == 400
    assert "valid HTTP header name" in created.text
    assert len((await client.get(f"{BASE}/", headers=auth)).json()) == listed

    provider = (await _create(client, auth)).json()
    before = await _stored(db_session, provider["id"])

    updated = await client.put(
        f"{BASE}/{provider['id']}/", headers=auth, json={"outbound_headers": invalid}
    )

    assert updated.status_code == 400
    assert "valid HTTP header name" in updated.text
    assert await _stored(db_session, provider["id"]) == before


async def _wait_until_waiting_for_a_lock(db_session: Any, pid: int) -> None:
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        async with db_session() as session:
            wait_event_type = await session.scalar(
                text(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"
                ).bindparams(pid=pid)
            )
        if wait_event_type == "Lock":
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"Database session {pid} did not wait for the provider lock")


async def test_concurrent_edits_are_audited_against_the_state_each_replaced(
    client, auth, db_container, db_session, admin_user, user_factory, audit_calls
):
    """Both edits start at A; the first moves the provider to B and the second
    back to A. Each is audited as the change it made, by its own actor."""
    moved_to = "https://gateway-2.internal/v1"
    provider_id = UUID(
        (
            await _create(
                client, auth, headers=[{"name": "X-Org", "value": "eu-north"}]
            )
        ).json()["id"]
    )
    async with db_container() as container:
        row = await user_factory(container.session())
        second_actor = await container.user_repo().get_user_by_id(row.id)
    assert second_actor is not None

    first_holds_lock = asyncio.Event()
    release_first = asyncio.Event()
    second_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def edit(actor: Any, endpoint: str, *, hold: bool) -> None:
        async with db_container(user=actor) as container:
            if not hold:
                second_pid.set_result(
                    await container.session().scalar(text("SELECT pg_backend_pid()"))
                )
            await update_provider(
                provider_id=provider_id,
                data=ModelProviderUpdate(config={"endpoint": endpoint}),
                user=actor,
                service=ModelProviderService(
                    container.model_provider_repository(),
                    container.encryption_service(),
                ),
                audit=container.audit_service(),
            )
            if hold:
                # The transaction, and its row lock, stay open until released.
                first_holds_lock.set()
                await release_first.wait()

    first = asyncio.create_task(edit(admin_user, moved_to, hold=True))
    held = asyncio.create_task(first_holds_lock.wait())
    await asyncio.wait({first, held}, timeout=5, return_when=asyncio.FIRST_COMPLETED)
    if first.done():
        await first  # surfaces why it never held the lock
    assert held.done(), "the first edit did not reach its open transaction"

    second = asyncio.create_task(edit(second_actor, ENDPOINT, hold=False))
    await _wait_until_waiting_for_a_lock(
        db_session, await asyncio.wait_for(second_pid, timeout=5)
    )
    release_first.set()
    await asyncio.gather(first, second)

    moves = [
        (call["user"].id, call["metadata"]["changes"]["endpoint"])
        for call in _audited(audit_calls, ActionType.MODEL_PROVIDER_DESTINATION_CHANGED)
    ]
    assert moves == [
        (admin_user.id, {"old": ENDPOINT, "new": moved_to}),
        (second_actor.id, {"old": moved_to, "new": ENDPOINT}),
    ]


async def test_secret_flag_flip_is_audited_masked(client, auth, audit_calls):
    provider = (await _create(client, auth)).json()
    audit_calls.reset_mock()
    writes = [
        {**header, "secret": False, "value": "now-public"}
        if header["secret"]
        else header
        for header in provider["outbound_headers"]
    ]

    response = await client.put(
        f"{BASE}/{provider['id']}/", headers=auth, json={"outbound_headers": writes}
    )

    assert response.status_code == 200, response.text
    [audit] = _audited(audit_calls, ActionType.MODEL_PROVIDER_HEADERS_UPDATED)
    [change] = audit["metadata"]["changes"]["updated"]
    assert change["old"]["value"] == change["new"]["value"] == MASK
    assert (change["old"]["secret"], change["new"]["secret"]) == (True, False)
    assert "sk-bf-aGVsbG8=" not in str(audit) and "now-public" not in str(audit)


async def test_preview_resolves_for_a_tenant_user_and_never_returns_secrets(
    client, auth, db_session, admin_user, audit_calls
):
    async with db_session() as session:
        await session.execute(
            update(Users)
            .where(Users.id == admin_user.id)
            .values(scim_extensions={SCIM_ENTERPRISE_USER_URN: {"department": "Miljö"}})
        )
    provider = (await _create(client, auth)).json()

    response = await client.post(
        f"{BASE}/{provider['id']}/outbound-headers/preview/",
        headers=auth,
        json={"user_id": str(admin_user.id)},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    items = _by_name(body["headers"])
    assert items["X-Org-Unit"]["state"] == "resolved"
    assert items["X-Org-Unit"]["value"] == "Milj%C3%B6"
    assert items["X-Credential"] == {
        "name": "X-Credential",
        "secret": True,
        "state": "resolved",
        "value": None,
        "policy": None,
        "reason": None,
        "missing_dynamic_values": [],
    }
    assert body["blocked"] is False
    assert body["blocked_reason"] is None
    assert "sk-bf-aGVsbG8=" not in response.text

    [audit] = _audited(audit_calls, ActionType.MODEL_PROVIDER_HEADERS_PREVIEWED)
    assert audit["metadata"]["extra"]["previewed_user_id"] == str(admin_user.id)
    assert "Milj" not in str(audit)


async def test_preview_of_an_unknown_user_is_404(client, auth, audit_calls):
    provider = (await _create(client, auth)).json()

    response = await client.post(
        f"{BASE}/{provider['id']}/outbound-headers/preview/",
        headers=auth,
        json={"user_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert _audited(audit_calls, ActionType.MODEL_PROVIDER_HEADERS_PREVIEWED) == []


async def test_provider_without_headers_is_unchanged(
    client, auth, db_session, audit_calls
):
    response = await _create(client, auth, headers=[])

    assert response.status_code == 200, response.text
    assert response.json()["outbound_headers"] == []
    assert await _stored(db_session, response.json()["id"]) == []
    assert _audited(audit_calls, ActionType.MODEL_PROVIDER_HEADERS_UPDATED) == []
