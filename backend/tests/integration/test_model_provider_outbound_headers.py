"""Outbound headers through the admin API, against a real database.

Covers the secret contract across routes (storage, GET, PUT, preview, audit),
destination checks that follow the endpoint the request actually uses, and the
unsupported-provider-type refusal. Wire behaviour is covered by the transport
capture tests in tests/unit/model_providers/infrastructure.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update

from eneo.audit.application.audit_service import AuditService
from eneo.audit.domain.action_types import ActionType
from eneo.database.tables.model_providers_table import ModelProviders
from eneo.database.tables.users_table import Users
from eneo.main.config import get_settings
from eneo.scim.constants import SCIM_ENTERPRISE_USER_URN

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
        json={"config": {"endpoint": "https://gateway-2.internal/v1"}},
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
