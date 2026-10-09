"""Administrators connect native transcription services; keys stay write-only."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa

from eneo.audit.application.audit_service import AuditService
from eneo.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassifications,
)
from eneo.database.tables.transcription_services_table import (
    TranscriptionServiceConnections,
)
from eneo.transcription_services import service as service_module
from eneo.transcription_services.models import (
    SERVICE_ENDPOINT_MESSAGES,
    ConnectionCheckOutcome,
    LastConnectionCheck,
)
from eneo.transcription_services.repository import (
    TranscriptionServiceConnectionRepository,
)
from tests.integration.transcription_services.conftest import BASE

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _stored(db_container, connection_id: str) -> sa.Row:
    table = TranscriptionServiceConnections
    async with db_container() as container:
        row = (
            await container.session().execute(
                sa.select(
                    table.endpoint_url,
                    table.api_key_encrypted,
                    table.is_enabled,
                    table.security_classification_id,
                ).where(table.id == UUID(connection_id))
            )
        ).one()
        return row


async def _decrypted_key(db_container, connection_id: str) -> str:
    row = await _stored(db_container, connection_id)
    async with db_container() as container:
        return container.encryption_service().decrypt(row.api_key_encrypted)


def _record_audit(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    audited: list[dict] = []
    log_async = AuditService.log_async

    async def record(self, **kwargs):
        audited.append(kwargs)
        return await log_async(self, **kwargs)

    monkeypatch.setattr(AuditService, "log_async", record)
    return audited


async def test_a_connection_stores_a_normalised_endpoint_and_an_encrypted_key(
    db_container, create_connection, monkeypatch
):
    audited = _record_audit(monkeypatch)

    connection = await create_connection(
        endpoint_url="  https://Vemsa.example.se/v1/  "
    )

    assert connection["endpoint_url"] == "https://Vemsa.example.se"
    assert connection["is_enabled"] is True
    assert "api_key" not in connection and "first-secret" not in str(connection)
    row = await _stored(db_container, connection["id"])
    assert row.api_key_encrypted != "first-secret"
    assert await _decrypted_key(db_container, connection["id"]) == "first-secret"
    [entry] = audited
    assert entry["action"].value == "transcription_service_created"
    assert "first-secret" not in str(entry["metadata"])


@pytest.mark.parametrize(
    "endpoint, problem",
    [
        ("https://user:secret@vemsa.example.se", "service_endpoint_credentials"),
        ("https://vemsa.example.se?token=x", "service_endpoint_query"),
        ("https://vemsa.example.se#jobs", "service_endpoint_query"),
        ("ftp://vemsa.example.se", "service_endpoint_not_http"),
        ("vemsa.example.se", "service_endpoint_not_http"),
        ("https://vemsa.example.se:notaport", "service_endpoint_port"),
        ("https://vemsa.example.se/" + "a" * 2050, "service_endpoint_too_long"),
    ],
)
async def test_an_unusable_endpoint_is_refused_with_its_reason(
    client, admin_headers, endpoint, problem
):
    name = f"refused-{uuid4().hex[:8]}"
    response = await client.post(
        BASE,
        json={
            "name": name,
            "endpoint_url": endpoint,
            "api_key": "secret",
        },
        headers=admin_headers,
    )

    assert response.status_code == 422, response.text
    [error] = response.json()["details"]["errors"]
    assert error["type"] == problem
    assert error["message"] == SERVICE_ENDPOINT_MESSAGES[problem]
    assert "secret" not in response.text and "token=x" not in response.text
    listed = await client.get(BASE, params={"limit": 200}, headers=admin_headers)
    assert name not in {item["name"] for item in listed.json()["items"]}


@pytest.mark.parametrize(
    "api_key", ["   ", "k" * 10241], ids=["blank", "beyond-encryption-limit"]
)
async def test_an_unusable_key_is_refused_without_touching_the_stored_one(
    client, db_container, admin_headers, create_connection, api_key
):
    created = await client.post(
        BASE,
        json={
            "name": f"key-{uuid4().hex[:8]}",
            "endpoint_url": "https://vemsa.example.se",
            "api_key": api_key,
        },
        headers=admin_headers,
    )
    connection = await create_connection()
    updated = await client.patch(
        f"{BASE}{connection['id']}/", json={"api_key": api_key}, headers=admin_headers
    )

    assert created.status_code == 422, created.text
    assert updated.status_code == 422, updated.text
    assert await _decrypted_key(db_container, connection["id"]) == "first-secret"


async def test_the_list_pages_in_name_order(client, admin_headers, create_connection):
    prefix = f"page-{uuid4().hex[:6]}"
    for suffix in ("c", "a", "b"):
        await create_connection(name=f"{prefix}-{suffix}")

    listed = await client.get(BASE, params={"limit": 200}, headers=admin_headers)
    names = [item["name"] for item in listed.json()["items"]]
    mine = [name for name in names if name.startswith(prefix)]
    assert mine == [f"{prefix}-a", f"{prefix}-b", f"{prefix}-c"]

    start = names.index(f"{prefix}-a")
    first = await client.get(
        BASE, params={"limit": 2, "offset": start}, headers=admin_headers
    )
    assert [item["name"] for item in first.json()["items"]] == [
        f"{prefix}-a",
        f"{prefix}-b",
    ]
    assert first.json()["has_more"] is True
    last = await client.get(
        BASE, params={"limit": 200, "offset": len(names) - 1}, headers=admin_headers
    )
    assert last.json()["has_more"] is False


async def test_names_are_unique_within_the_organisation(
    client, admin_headers, create_connection
):
    existing = await create_connection()

    duplicate = await client.post(
        BASE,
        json={
            "name": existing["name"],
            "endpoint_url": "https://other.example.se",
            "api_key": "secret",
        },
        headers=admin_headers,
    )
    renamed = await create_connection()
    clash = await client.patch(
        f"{BASE}{renamed['id']}/",
        json={"name": existing["name"]},
        headers=admin_headers,
    )

    assert duplicate.status_code == 409, duplicate.text
    assert clash.status_code == 409, clash.text


async def test_a_member_cannot_read_change_or_check_a_connection(
    client, db_container, member_headers, create_connection, native_service
):
    connection = await create_connection()
    url = f"{BASE}{connection['id']}/"

    responses = [
        await client.get(BASE, headers=member_headers),
        await client.post(
            BASE,
            json={
                "name": f"member-{uuid4().hex[:8]}",
                "endpoint_url": "https://vemsa.example.se",
                "api_key": "secret",
            },
            headers=member_headers,
        ),
        await client.get(url, headers=member_headers),
        await client.patch(url, json={"is_enabled": False}, headers=member_headers),
        await client.post(f"{url}check/", headers=member_headers),
        await client.delete(url, headers=member_headers),
    ]

    assert [response.status_code for response in responses] == [403] * 6
    assert native_service.requests == []
    assert (await _stored(db_container, connection["id"])).is_enabled is True


async def test_moving_the_endpoint_requires_a_new_key(
    client, db_container, admin_headers, create_connection
):
    connection = await create_connection(endpoint_url="https://vemsa-a.example.se")
    url = f"{BASE}{connection['id']}/"

    without_key = await client.patch(
        url, json={"endpoint_url": "https://vemsa-b.example.se"}, headers=admin_headers
    )
    masked = await client.patch(
        url,
        json={"endpoint_url": "https://vemsa-b.example.se", "api_key": "...cret"},
        headers=admin_headers,
    )
    assert without_key.status_code == 400, without_key.text
    assert masked.status_code == 400, masked.text
    assert (await _stored(db_container, connection["id"])).endpoint_url == (
        "https://vemsa-a.example.se"
    )

    same_place = await client.patch(
        url,
        json={"endpoint_url": "HTTPS://vemsa-a.example.se:443/v1"},
        headers=admin_headers,
    )
    assert same_place.status_code == 200, same_place.text
    assert await _decrypted_key(db_container, connection["id"]) == "first-secret"

    moved = await client.patch(
        url,
        json={"endpoint_url": "https://vemsa-b.example.se", "api_key": "second-secret"},
        headers=admin_headers,
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["endpoint_url"] == "https://vemsa-b.example.se"
    assert await _decrypted_key(db_container, connection["id"]) == "second-secret"


async def test_an_update_changes_only_what_it_sends(
    client, admin_headers, create_connection, monkeypatch
):
    connection = await create_connection()
    audited = _record_audit(monkeypatch)

    response = await client.patch(
        f"{BASE}{connection['id']}/",
        json={"is_enabled": False},
        headers=admin_headers,
    )
    refused_nulls = [
        await client.patch(
            f"{BASE}{connection['id']}/", json={field: None}, headers=admin_headers
        )
        for field in ("name", "endpoint_url", "api_key", "is_enabled")
    ]

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["is_enabled"] is False
    assert (updated["name"], updated["endpoint_url"]) == (
        connection["name"],
        connection["endpoint_url"],
    )
    assert [r.status_code for r in refused_nulls] == [422] * 4
    [entry] = audited
    assert entry["action"].value == "transcription_service_updated"
    assert set(entry["metadata"]["changes"]) == {"is_enabled"}


async def test_another_organisations_connection_is_not_found(
    client, db_container, admin_headers, tenant_factory, native_service
):
    async with db_container() as container:
        session = container.session()
        other = await tenant_factory(session)
        connection_id = await session.scalar(
            sa.insert(TranscriptionServiceConnections)
            .values(
                tenant_id=other.id,
                name="theirs",
                endpoint_url="https://theirs.example.se",
                api_key_encrypted="enc:fernet:v1:not-used",
            )
            .returning(TranscriptionServiceConnections.id)
        )
    url = f"{BASE}{connection_id}/"

    responses = [
        await client.get(url, headers=admin_headers),
        await client.patch(url, json={"is_enabled": False}, headers=admin_headers),
        await client.post(f"{url}check/", headers=admin_headers),
        await client.delete(url, headers=admin_headers),
    ]

    assert [response.status_code for response in responses] == [404] * 4
    listed = await client.get(BASE, params={"limit": 200}, headers=admin_headers)
    assert str(connection_id) not in {item["id"] for item in listed.json()["items"]}
    assert native_service.requests == []


@pytest.mark.parametrize(
    "tasks, identifies_speakers",
    [
        ({"supported_tasks": ["diarize", "align"]}, True),
        ({"supported_tasks": ["align"]}, False),
        ({}, None),
    ],
    ids=["reports-diarize", "reports-no-diarize", "reports-no-tasks"],
)
async def test_a_check_asks_the_service_with_the_stored_key_and_sends_no_audio(
    client,
    admin_headers,
    create_connection,
    native_service,
    monkeypatch,
    tasks,
    identifies_speakers,
):
    connection = await create_connection()
    native_service.answer = httpx.Response(
        200,
        json={"queue_accepting_jobs": True, "service_version": "1.4.0", **tasks},
    )
    audited = _record_audit(monkeypatch)

    response = await client.post(
        f"{BASE}{connection['id']}/check/", headers=admin_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body.pop("checked_at")
    assert body == {
        "outcome": "ready",
        "detail": "accepting jobs",
        "identifies_speakers": identifies_speakers,
        "service_version": "1.4.0",
    }
    [request] = native_service.requests
    assert (request.method, str(request.url)) == (
        "GET",
        "https://vemsa.example.se/v1/health/ready",
    )
    assert request.headers["authorization"] == "Bearer first-secret"
    [entry] = audited
    assert entry["action"].value == "transcription_service_checked"
    assert entry["metadata"]["extra"]["outcome"] == "ready"


@pytest.mark.parametrize(
    "answer, outcome, detail",
    [
        (
            httpx.Response(401),
            "credentials_rejected",
            "the service rejected the API key",
        ),
        (
            httpx.Response(200, json={"queue_accepting_jobs": False}),
            "not_accepting_jobs",
            "queue not accepting jobs",
        ),
        (httpx.Response(503, json={"status": "not_ready"}), "unavailable", "http 503"),
        (
            httpx.Response(200, json={"status": "ready"}),
            "unavailable",
            "malformed readiness response",
        ),
        (
            httpx.ConnectError("dummy-transport-secret"),
            "unavailable",
            "unreachable: ConnectError",
        ),
    ],
)
async def test_a_check_reports_what_went_wrong_without_secrets(
    client, admin_headers, create_connection, native_service, answer, outcome, detail
):
    connection = await create_connection()
    native_service.answer = answer

    response = await client.post(
        f"{BASE}{connection['id']}/check/", headers=admin_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["outcome"], body["detail"]) == (outcome, detail)
    assert body["identifies_speakers"] is None
    assert "secret" not in response.text


async def test_a_disabled_connection_can_still_be_checked(
    client, admin_headers, create_connection, native_service
):
    connection = await create_connection(is_enabled=False)

    response = await client.post(
        f"{BASE}{connection['id']}/check/", headers=admin_headers
    )

    assert response.json()["outcome"] == "ready"


async def test_a_name_clash_with_a_classification_is_a_conflict_and_changes_nothing(
    client, db_container, admin_user, admin_headers, create_connection, monkeypatch
):
    async with db_container() as container:
        session = container.session()
        level = SecurityClassifications(
            tenant_id=admin_user.tenant_id,
            name=f"level-{uuid4().hex[:6]}",
            security_level=5,
        )
        session.add(level)
        await session.flush()
        level_id = level.id
    existing = await create_connection()
    renamed = await create_connection()
    audited = _record_audit(monkeypatch)

    response = await client.patch(
        f"{BASE}{renamed['id']}/",
        json={
            "name": existing["name"],
            "security_classification": {"id": str(level_id)},
        },
        headers=admin_headers,
    )
    current = await client.get(f"{BASE}{renamed['id']}/", headers=admin_headers)

    assert response.status_code == 409, response.text
    assert current.json()["name"] == renamed["name"]
    assert audited == []


async def test_clearing_the_classification_is_explicit(
    client, db_container, admin_user, admin_headers, create_connection
):
    async with db_container() as container:
        session = container.session()
        level = SecurityClassifications(
            tenant_id=admin_user.tenant_id,
            name=f"level-{uuid4().hex[:6]}",
            security_level=5,
        )
        session.add(level)
        await session.flush()
        level_id = level.id
    connection = await create_connection(security_classification={"id": str(level_id)})
    url = f"{BASE}{connection['id']}/"

    kept = await client.patch(url, json={"is_enabled": True}, headers=admin_headers)
    cleared = await client.patch(
        url, json={"security_classification": None}, headers=admin_headers
    )

    stored = await _stored(db_container, connection["id"])
    assert kept.status_code == 200 and cleared.status_code == 200, cleared.text
    assert stored.security_classification_id is None


async def test_a_check_after_a_move_pairs_the_new_endpoint_with_the_new_key(
    client, admin_headers, create_connection, native_service
):
    connection = await create_connection(endpoint_url="https://vemsa-a.example.se")
    await client.patch(
        f"{BASE}{connection['id']}/",
        json={"endpoint_url": "https://vemsa-b.example.se", "api_key": "second-secret"},
        headers=admin_headers,
    )

    await client.post(f"{BASE}{connection['id']}/check/", headers=admin_headers)

    [request] = native_service.requests
    assert str(request.url) == "https://vemsa-b.example.se/v1/health/ready"
    assert request.headers["authorization"] == "Bearer second-secret"


async def test_an_edit_committed_during_a_check_never_pairs_an_endpoint_with_another_key(
    client, db_container, admin_headers, create_connection, native_service, monkeypatch
):
    # Commits endpoint B with key B the moment the check's first read of the
    # connection returns: a check that reads the endpoint and the key
    # separately would send key B to endpoint A.
    from sqlalchemy.ext.asyncio import AsyncSession

    connection = await create_connection(endpoint_url="https://vemsa-a.example.se")
    async with db_container() as container:
        key_b = container.encryption_service().encrypt("second-secret")
    table = TranscriptionServiceConnections
    edits: list[str] = []
    execute = AsyncSession.execute

    async def execute_then_edit(self, statement, *args, **kwargs):
        result = await execute(self, statement, *args, **kwargs)
        reads_connection = isinstance(statement, sa.Select) and (
            table.__tablename__ in str(statement)
        )
        if reads_connection and not edits:
            edits.append("committed")
            async with db_container() as other:
                await execute(
                    other.session(),
                    sa.update(table)
                    .where(table.id == UUID(connection["id"]))
                    .values(
                        endpoint_url="https://vemsa-b.example.se",
                        api_key_encrypted=key_b,
                    ),
                )
        return result

    monkeypatch.setattr(AsyncSession, "execute", execute_then_edit)

    response = await client.post(
        f"{BASE}{connection['id']}/check/", headers=admin_headers
    )

    assert response.status_code == 200, response.text
    assert edits == ["committed"]
    [request] = native_service.requests
    sent = (request.url.host, request.headers["authorization"])
    assert sent in {
        ("vemsa-a.example.se", "Bearer first-secret"),
        ("vemsa-b.example.se", "Bearer second-secret"),
    }
    # A result is kept only for the endpoint and key it tested.
    monkeypatch.setattr(AsyncSession, "execute", execute)
    kept = (
        await client.get(f"{BASE}{connection['id']}/", headers=admin_headers)
    ).json()["last_check"]
    assert (kept is not None) == (sent[0] == "vemsa-b.example.se")


async def test_a_check_is_kept_for_every_administrator_until_the_endpoint_or_key_changes(
    client, admin_headers, create_connection, native_service
):
    connection = await create_connection()
    url = f"{BASE}{connection['id']}/"
    assert connection["last_check"] is None

    checked = await client.post(f"{url}check/", headers=admin_headers)
    after_check = await client.get(url, headers=admin_headers)
    renamed = await client.patch(url, json={"name": "Vemsa"}, headers=admin_headers)
    # The stored address in another spelling is not a move.
    same_address = await client.patch(
        url, json={"endpoint_url": "https://vemsa.example.se/"}, headers=admin_headers
    )
    rekeyed = await client.patch(url, json={"api_key": "new"}, headers=admin_headers)

    assert checked.status_code == 200, checked.text
    kept = renamed.json()["last_check"]
    assert kept == {
        "outcome": "ready",
        "identifies_speakers": None,
        "service_version": None,
        "checked_at": checked.json()["checked_at"],
    }
    assert same_address.json()["last_check"] == kept
    # Recording a check is not an edit of the connection.
    assert after_check.json()["updated_at"] == connection["updated_at"]
    assert rekeyed.json()["last_check"] is None


async def test_an_earlier_check_never_replaces_a_later_kept_one(
    db_container, admin_user, create_connection
):
    # Two administrators' checks can finish in either order.
    connection_id = UUID((await create_connection())["id"])
    later = LastConnectionCheck(
        outcome=ConnectionCheckOutcome.CREDENTIALS_REJECTED,
        identifies_speakers=None,
        service_version=None,
        checked_at=datetime(2026, 10, 9, 8, 0, tzinfo=UTC),
    )
    earlier = replace(
        later,
        outcome=ConnectionCheckOutcome.READY,
        checked_at=later.checked_at - timedelta(seconds=5),
    )
    async with db_container() as container:
        repository = TranscriptionServiceConnectionRepository(
            container.session(), admin_user.tenant_id
        )
        connection, ciphertext = await repository.get_with_key(connection_id)
        for check in (later, earlier):
            await repository.record_check(
                connection_id,
                check,
                endpoint_url=connection.endpoint_url,
                api_key_encrypted=ciphertext,
            )

    async with db_container() as container:
        kept = await TranscriptionServiceConnectionRepository(
            container.session(), admin_user.tenant_id
        ).get(connection_id)
    assert kept.last_check == later


async def test_an_organisation_connects_at_most_one_page_of_services(
    client, admin_headers, create_connection, monkeypatch
):
    monkeypatch.setattr(service_module, "MAX_CONNECTIONS_PER_ORGANISATION", 1)
    await create_connection(name="Vemsa Sundsvall")

    refused = await client.post(
        BASE,
        json={
            "name": "Vemsa reserv",
            "endpoint_url": "https://vemsa-reserv.example.se/",
            "api_key": "secret",
        },
        headers=admin_headers,
    )

    assert refused.status_code == 400, refused.text
    assert refused.json()["code"] == "transcription_service_limit_reached"
