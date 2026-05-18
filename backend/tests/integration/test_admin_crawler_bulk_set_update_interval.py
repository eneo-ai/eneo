"""Tenant admin bulk interval change for many crawler websites at once.

Drives the Webbplatser admin tab's "Apply interval to N selected"
toolbar action. Wire shape is 200 + structured payload (applied /
unchanged / failed) instead of 207 so generated clients can consume a
single typed response shape.

The endpoint loops the existing per-row setter so the auto-disabled
resume invariant (clears `consecutive_failures` + `next_retry_at`
when previous=NEVER + counters ≥ threshold + new=recurring) holds
without drift. Each `applied` row gets the same per-website audit
row as the per-row endpoint, so audit-log search by
`EntityType.WEBSITE` entity_id remains the audit-trail primary key.

Cap is enforced by Pydantic (`Field(max_length=100)`); requests
above the cap surface as 422 without entering the repo loop.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.database.tables.ai_models_table import EmbeddingModels
from intric.database.tables.tenant_table import Tenants
from intric.database.tables.users_table import Users
from intric.database.tables.websites_table import Websites
from intric.websites.domain.bulk_crawl_interval_change import (
    BULK_INTERVAL_MAX_WEBSITE_IDS,
    BulkIntervalRowFailureCode,
)
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import (
    WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
    UpdateInterval,
)

_BULK_INTERVAL_PATH = "/api/v1/admin/crawler/websites/bulk-interval"


async def _embedding_model_id(session) -> UUID:
    embedding_model_id = await session.scalar(sa.select(EmbeddingModels.id).limit(1))
    assert embedding_model_id is not None
    return embedding_model_id


async def _create_website(
    session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    embedding_model_id: UUID,
    update_interval: UpdateInterval,
    name: str | None,
    consecutive_failures: int = 0,
) -> Websites:
    website = Websites(
        name=name,
        url=f"https://bulk-interval-{uuid4()}.example.com",
        download_files=True,
        crawl_type=CrawlType.CRAWL,
        update_interval=update_interval,
        size=0,
        tenant_id=tenant_id,
        user_id=user_id,
        embedding_model_id=embedding_model_id,
        consecutive_failures=consecutive_failures,
    )
    session.add(website)
    await session.flush()
    return website


async def _create_tenant_user(session) -> Users:
    tenant = Tenants(
        name=f"bulk-tenant-{uuid4().hex}",
        display_name="Bulk interval tenant isolation",
        slug=f"bulk-tenant-{uuid4().hex[:20]}",
        quota_limit=1_000_000,
    )
    session.add(tenant)
    await session.flush()

    user = Users(
        email=f"bulk-tenant-{uuid4().hex}@example.com",
        tenant_id=tenant.id,
        state="active",
    )
    session.add(user)
    await session.flush()
    return user


def _install_audit_recorder(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, object]]:
    audit_calls: list[dict[str, object]] = []

    async def record_audit(
        self: AuditService,
        **kwargs: object,
    ) -> UUID | None:
        audit_calls.append(kwargs)
        return uuid4()

    monkeypatch.setattr(AuditService, "log_async", record_audit)
    return audit_calls


def _interval_audit_calls(
    audit_calls: list[dict[str, object]],
) -> list[dict[str, object]]:
    return [
        audit_call
        for audit_call in audit_calls
        if audit_call.get("action") == ActionType.WEBSITE_CRAWL_INTERVAL_CHANGED
    ]


def _audit_extra(audit_call: dict[str, object]) -> dict[str, object]:
    metadata = audit_call["metadata"]
    assert isinstance(metadata, dict)
    extra = metadata["extra"]
    assert isinstance(extra, dict)
    return extra


@pytest.mark.asyncio
@pytest.mark.integration
async def test_bulk_set_update_interval_applies_to_changed_rows_only(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    """Three websites in the tenant — one is already on the target
    interval, the other two are not. The endpoint should return
    `applied` for the two that changed and `unchanged` for the third,
    with audit emission scoped to the two changed rows."""
    audit_calls = _install_audit_recorder(monkeypatch)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        change_a = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
            name="Bulk A",
        )
        change_b = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.WEEKLY,
            name="Bulk B",
        )
        already_target = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.NEVER,
            name="Bulk C (already paused)",
        )
        change_a_id = change_a.id
        change_b_id = change_b.id
        already_target_id = already_target.id
        await session.commit()

    response = await client.post(
        _BULK_INTERVAL_PATH,
        headers={"X-API-Key": admin_user_api_key.key},
        json={
            "website_ids": [
                str(change_a_id),
                str(change_b_id),
                str(already_target_id),
            ],
            "update_interval": UpdateInterval.NEVER.value,
        },
    )

    assert response.status_code == 200
    payload = response.json()

    applied_ids = {row["website_id"] for row in payload["applied"]}
    unchanged_ids = {row["website_id"] for row in payload["unchanged"]}
    assert applied_ids == {str(change_a_id), str(change_b_id)}
    assert unchanged_ids == {str(already_target_id)}
    assert payload["failed"] == []

    for applied_row in payload["applied"]:
        assert applied_row["new_update_interval"] == UpdateInterval.NEVER.value
        assert applied_row["failure_state_cleared"] is False

    async with db_session() as session:
        rows = (
            await session.execute(
                sa.select(Websites.id, Websites.update_interval).where(
                    Websites.id.in_([change_a_id, change_b_id, already_target_id])
                )
            )
        ).all()

    assert {(row.id, row.update_interval) for row in rows} == {
        (change_a_id, UpdateInterval.NEVER.value),
        (change_b_id, UpdateInterval.NEVER.value),
        (already_target_id, UpdateInterval.NEVER.value),
    }

    interval_calls = _interval_audit_calls(audit_calls)
    assert len(interval_calls) == 2
    audited_entity_ids = {call["entity_id"] for call in interval_calls}
    assert audited_entity_ids == {change_a_id, change_b_id}
    for call in interval_calls:
        assert call["tenant_id"] == admin_user.tenant_id
        assert call["actor_id"] == admin_user.id
        assert call["entity_type"] == EntityType.WEBSITE
        extra = _audit_extra(call)
        assert extra["new_update_interval"] == UpdateInterval.NEVER.value
        assert extra["bulk"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_bulk_set_update_interval_preserves_auto_disable_resume(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    """Bulk updates must not bypass the auto-disabled resume invariant.

    A NEVER + counters ≥ threshold row included in the bulk apply must
    clear its counters exactly like the single-row endpoint, and the
    audit row must surface `failure_state_cleared=True`.
    """
    audit_calls = _install_audit_recorder(monkeypatch)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        disabled = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.NEVER,
            consecutive_failures=WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD,
            name="Auto-disabled site",
        )
        plain = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
            name="Plain site",
        )
        disabled_id = disabled.id
        plain_id = plain.id
        await session.commit()

    response = await client.post(
        _BULK_INTERVAL_PATH,
        headers={"X-API-Key": admin_user_api_key.key},
        json={
            "website_ids": [str(disabled_id), str(plain_id)],
            "update_interval": UpdateInterval.WEEKLY.value,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["applied"]) == 2

    applied_by_id = {row["website_id"]: row for row in payload["applied"]}
    assert applied_by_id[str(disabled_id)]["failure_state_cleared"] is True
    assert applied_by_id[str(plain_id)]["failure_state_cleared"] is False

    async with db_session() as session:
        disabled_row = (
            await session.execute(
                sa.select(
                    Websites.update_interval,
                    Websites.consecutive_failures,
                    Websites.next_retry_at,
                ).where(Websites.id == disabled_id)
            )
        ).one()
        plain_row = (
            await session.execute(
                sa.select(
                    Websites.update_interval,
                    Websites.consecutive_failures,
                ).where(Websites.id == plain_id)
            )
        ).one()

    assert disabled_row.update_interval == UpdateInterval.WEEKLY.value
    assert disabled_row.consecutive_failures == 0
    assert disabled_row.next_retry_at is None
    assert plain_row.update_interval == UpdateInterval.WEEKLY.value

    interval_calls = _interval_audit_calls(audit_calls)
    cleared_calls = [
        call for call in interval_calls if call["entity_id"] == disabled_id
    ]
    assert len(cleared_calls) == 1
    cleared_extra = _audit_extra(cleared_calls[0])
    assert cleared_extra["failure_state_cleared"] is True
    assert (
        cleared_extra["previous_consecutive_failures"]
        == WEBSITE_AUTO_DISABLE_FAILURE_THRESHOLD
    )

    plain_calls = [call for call in interval_calls if call["entity_id"] == plain_id]
    assert len(plain_calls) == 1
    plain_extra = _audit_extra(plain_calls[0])
    assert plain_extra["failure_state_cleared"] is False
    assert plain_extra["previous_consecutive_failures"] == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_bulk_set_update_interval_reports_failed_for_unknown_id(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    """An id that doesn't exist in any tenant (concurrent delete) is
    reported as a `failed` row with `code=NOT_FOUND`, NOT as a 404.
    Avoiding 404 here keeps the bulk path's "partial success is OK"
    semantics intact — the operator gets the structured report and
    can drill into the failure rather than losing the whole batch."""
    audit_calls = _install_audit_recorder(monkeypatch)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        existing = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
            name="Existing",
        )
        existing_id = existing.id
        await session.commit()

    missing_id = uuid4()

    response = await client.post(
        _BULK_INTERVAL_PATH,
        headers={"X-API-Key": admin_user_api_key.key},
        json={
            "website_ids": [str(existing_id), str(missing_id)],
            "update_interval": UpdateInterval.WEEKLY.value,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert {row["website_id"] for row in payload["applied"]} == {str(existing_id)}
    assert payload["unchanged"] == []
    assert payload["failed"] == [
        {
            "website_id": str(missing_id),
            "code": BulkIntervalRowFailureCode.NOT_FOUND.value,
        }
    ]

    interval_calls = _interval_audit_calls(audit_calls)
    assert {call["entity_id"] for call in interval_calls} == {existing_id}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_bulk_set_update_interval_does_not_touch_other_tenant(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    """A cross-tenant id must surface as `failed/NOT_FOUND` — same as
    a deleted id — never as a successful update. Verifies the
    `tenant_id` filter on the underlying setter holds under the
    bulk loop. Cross-tenant leak via the bulk path is the canonical
    P0 risk per the audit/tenancy gate."""
    audit_calls = _install_audit_recorder(monkeypatch)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        own = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
            name="Own",
        )
        own_id = own.id

        other_user = await _create_tenant_user(session)
        other = await _create_website(
            session,
            tenant_id=other_user.tenant_id,
            user_id=other_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
            name="Other tenant",
        )
        other_id = other.id
        await session.commit()

    response = await client.post(
        _BULK_INTERVAL_PATH,
        headers={"X-API-Key": admin_user_api_key.key},
        json={
            "website_ids": [str(own_id), str(other_id)],
            "update_interval": UpdateInterval.WEEKLY.value,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert {row["website_id"] for row in payload["applied"]} == {str(own_id)}
    assert payload["failed"] == [
        {
            "website_id": str(other_id),
            "code": BulkIntervalRowFailureCode.NOT_FOUND.value,
        }
    ]

    async with db_session() as session:
        other_interval = await session.scalar(
            sa.select(Websites.update_interval).where(Websites.id == other_id)
        )

    assert other_interval == UpdateInterval.DAILY.value

    interval_calls = _interval_audit_calls(audit_calls)
    assert {call["entity_id"] for call in interval_calls} == {own_id}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_bulk_set_update_interval_dedupes_duplicate_ids(
    client,
    db_session,
    admin_user,
    admin_user_api_key,
    monkeypatch,
):
    """A duplicated id in the request body should count as one row in
    the response — and emit exactly one audit row. Otherwise a
    careless client could double-bill the audit trail."""
    audit_calls = _install_audit_recorder(monkeypatch)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
            name="Dedupe target",
        )
        website_id = website.id
        await session.commit()

    response = await client.post(
        _BULK_INTERVAL_PATH,
        headers={"X-API-Key": admin_user_api_key.key},
        json={
            "website_ids": [str(website_id), str(website_id)],
            "update_interval": UpdateInterval.NEVER.value,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["applied"]) == 1
    assert payload["applied"][0]["website_id"] == str(website_id)
    assert payload["unchanged"] == []
    assert payload["failed"] == []

    interval_calls = _interval_audit_calls(audit_calls)
    assert len(interval_calls) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_bulk_set_update_interval_rejects_cap_overflow(
    client,
    admin_user_api_key,
    monkeypatch,
):
    """Request bodies above `BULK_INTERVAL_MAX_WEBSITE_IDS` are
    rejected by Pydantic with 422 — no DB touch, no audit emission,
    no enumeration risk."""
    audit_calls = _install_audit_recorder(monkeypatch)

    over_cap = [str(uuid4()) for _ in range(BULK_INTERVAL_MAX_WEBSITE_IDS + 1)]

    response = await client.post(
        _BULK_INTERVAL_PATH,
        headers={"X-API-Key": admin_user_api_key.key},
        json={
            "website_ids": over_cap,
            "update_interval": UpdateInterval.NEVER.value,
        },
    )

    assert response.status_code == 422
    assert _interval_audit_calls(audit_calls) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_bulk_set_update_interval_rejects_empty_list(
    client,
    admin_user_api_key,
    monkeypatch,
):
    """An empty body is also a 422 — there is nothing to act on and
    we'd rather force the client to surface the no-selection state
    on its side than emit a no-op 200."""
    audit_calls = _install_audit_recorder(monkeypatch)

    response = await client.post(
        _BULK_INTERVAL_PATH,
        headers={"X-API-Key": admin_user_api_key.key},
        json={
            "website_ids": [],
            "update_interval": UpdateInterval.NEVER.value,
        },
    )

    assert response.status_code == 422
    assert _interval_audit_calls(audit_calls) == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_bulk_set_update_interval_rejects_non_admin_user(
    client,
    db_container,
    db_session,
    user_factory,
    admin_user,
    monkeypatch,
):
    """A non-admin caller cannot hit the bulk endpoint — the router
    requires `Permission.ADMIN` like every other write here."""
    audit_calls = _install_audit_recorder(monkeypatch)

    async with db_session() as session:
        embedding_model_id = await _embedding_model_id(session)
        website = await _create_website(
            session,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
            embedding_model_id=embedding_model_id,
            update_interval=UpdateInterval.DAILY,
            name="Admin-protected",
        )
        website_id = website.id
        regular_user = await user_factory(
            session,
            tenant_id=admin_user.tenant_id,
            email=f"regular-bulk-{uuid4()}@example.com",
        )
        regular_user_id = regular_user.id
        await session.commit()

    async with db_container() as container:
        api_key = await container.auth_service().create_user_api_key(
            prefix="test", user_id=regular_user_id, delete_old=True
        )

    response = await client.post(
        _BULK_INTERVAL_PATH,
        headers={"X-API-Key": api_key.key},
        json={
            "website_ids": [str(website_id)],
            "update_interval": UpdateInterval.NEVER.value,
        },
    )

    assert response.status_code == 403
    assert _interval_audit_calls(audit_calls) == []
