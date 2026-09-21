"""Persistence contracts: real transactions, cascades and concurrent writers."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.database import sessionmanager
from eneo.database.tables.base_class import Base
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.widgets_table import Widgets
from eneo.main.exceptions import BadRequestException
from eneo.widgets.application.visitor_token_service import VisitorTokenService
from eneo.widgets.application.widget_limits import BudgetReservation, WidgetBudget
from eneo.widgets.application.widget_retention import purge_expired_widget_sessions
from eneo.widgets.domain.exceptions import (
    VisitorTokenStaleError,
    WidgetBudgetExhaustedError,
    WidgetRevisionConflictError,
)
from eneo.widgets.domain.widget import Widget, WidgetStatus, generate_public_id
from eneo.widgets.infrastructure.widget_overview_repo_impl import WidgetOverviewRepoImpl
from eneo.widgets.infrastructure.widget_repo_impl import WidgetRepoImpl
from eneo.widgets.infrastructure.widget_usage_repo_impl import WidgetUsageRepoImpl


async def _load_widget(widget_id: str):
    async with sessionmanager.session() as session, session.begin():
        widget = await WidgetRepoImpl(session).get(UUID(widget_id))
        assert widget is not None
        return widget


async def test_concurrent_budget_admission_and_exactly_once_completion(active_widget):
    widget = await _load_widget(active_widget["id"])
    widget.limits.daily_token_budget = 10_000
    budget = WidgetBudget()
    results = await asyncio.gather(
        budget.reserve(widget, 8_000),
        budget.reserve(widget, 8_000),
        return_exceptions=True,
    )
    receipts = [result for result in results if isinstance(result, BudgetReservation)]
    assert len(receipts) == 1
    assert (
        sum(isinstance(result, WidgetBudgetExhaustedError) for result in results) == 1
    )
    assert await budget.used_today(widget) == 8_000

    await asyncio.gather(
        budget.settle(receipts[0], 2_000, 500), budget.settle(receipts[0], 2_000, 500)
    )
    await budget.release(receipts[0])  # a late cleanup must not refund settled use
    # Fresh service instance: no Redis state is required for recovery.
    assert await WidgetBudget().used_today(widget) == 2_500
    async with sessionmanager.session() as session, session.begin():
        days = await WidgetUsageRepoImpl(session).list_days(
            widget.id, days=1, today=budget.today()
        )
    assert days[0].questions == 1
    assert (days[0].input_tokens, days[0].output_tokens) == (2_000, 500)


async def test_release_is_idempotent_and_old_days_do_not_charge_today(active_widget):
    widget = await _load_widget(active_widget["id"])
    budget = WidgetBudget()
    receipt = await budget.reserve(widget, 8_000)
    await asyncio.gather(budget.release(receipt), budget.release(receipt))
    await budget.settle(receipt, 5_000, 2_000)
    assert await budget.used_today(widget) == 0

    yesterday = budget.today() - timedelta(days=1)
    previous_id = uuid4()
    async with sessionmanager.session() as session, session.begin():
        assert await WidgetUsageRepoImpl(session).reserve(
            previous_id, widget.id, yesterday, tokens=8_000, limit=10_000
        )
    await budget.settle(
        BudgetReservation(previous_id, widget.id, yesterday, 8_000), 100, 50
    )
    assert await budget.used_today(widget) == 0


async def test_stale_writer_cannot_undo_pause_or_revive_tokens(active_widget):
    widget_id = UUID(active_widget["id"])
    async with sessionmanager.session() as first, sessionmanager.session() as second:
        async with first.begin():
            stale = await WidgetRepoImpl(first).get(widget_id)
            assert stale is not None
            async with second.begin():
                paused = await WidgetRepoImpl(second).get(widget_id)
                assert paused is not None
                paused.pause()
                await WidgetRepoImpl(second).update(paused)
            stale.apply_update({"name": "Stale edit"})
            with pytest.raises(WidgetRevisionConflictError):
                await WidgetRepoImpl(first).update(stale)
    saved = await _load_widget(active_widget["id"])
    assert saved.status == WidgetStatus.PAUSED
    assert saved.token_generation == active_widget["token_generation"] + 1
    assert saved.name != "Stale edit"


async def _wait_until_blocked(session, racer: "asyncio.Task") -> None:
    """Return once the racer waits for a row lock held by ``session``'s
    transaction, so that transaction is released only after the racer has
    lined up behind it. (The racer's query text is not visible here: asyncpg
    reports the statement it is blocked in as the transaction's BEGIN.)"""
    for _ in range(200):
        if racer.done():
            raise AssertionError(
                f"racer finished before the lock was released: {racer.exception()!r}"
            )
        blocked = await session.scalar(
            sa.text(
                "SELECT count(*) FROM pg_stat_activity"
                " WHERE datname = current_database()"
                " AND pid <> pg_backend_pid()"
                " AND wait_event_type = 'Lock'"
            )
        )
        if blocked:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"the racer never waited for the lock: {racer!r}")


async def _pause_via_service(db_container, widget_id: UUID) -> Widget:
    async with db_container() as container:
        return (await container.widget_service().pause_widget(widget_id)).widget


async def test_pause_revokes_tokens_minted_after_a_concurrent_rules_change(
    db_container, active_widget
):
    # A rules save commits while the pause is in flight. The pause must bump
    # the generation that save left, not write the same one back, or the
    # visitor tokens minted after the save would survive the pause and be
    # accepted again once the widget is resumed.
    widget_id = UUID(active_widget["id"])
    tokens = VisitorTokenService()
    async with db_container() as editor:
        edited = (
            await editor.widget_service().update_widget(
                widget_id,
                {
                    "revision": active_widget["revision"],
                    "allowed_origins": ["https://www.kommun.se", "https://e.kommun.se"],
                },
            )
        ).widget
        assert edited.token_generation == active_widget["token_generation"] + 1
        visitor_token, _ = tokens.mint(edited, uuid4())
        pause = asyncio.create_task(_pause_via_service(db_container, widget_id))
        await _wait_until_blocked(editor.session(), pause)
        assert not pause.done()
    paused = await pause
    assert paused.status == WidgetStatus.PAUSED
    assert paused.token_generation == edited.token_generation + 1

    async with db_container() as admin:
        resumed = (await admin.widget_service().activate_widget(widget_id)).widget
    assert resumed.token_generation == paused.token_generation
    with pytest.raises(VisitorTokenStaleError):
        tokens.verify(visitor_token, resumed)


async def test_pause_cannot_overwrite_a_committed_archive(db_container, active_widget):
    widget_id = UUID(active_widget["id"])
    async with db_container() as admin:
        archived = (await admin.widget_service().archive_widget(widget_id)).widget
        pause = asyncio.create_task(_pause_via_service(db_container, widget_id))
        await _wait_until_blocked(admin.session(), pause)
        assert not pause.done()
    # The pause sees the archive once it gets the row and refuses it.
    with pytest.raises(BadRequestException):
        await pause
    saved = await _load_widget(active_widget["id"])
    assert saved.status == WidgetStatus.ARCHIVED
    assert saved.token_generation == archived.token_generation


async def test_draft_save_cannot_roll_back_a_concurrent_publication(db_container):
    async with db_container() as container:
        template = await container.widget_template_service().create_template(
            name="Kommunblå"
        )
    assert template.id is not None

    async def save_draft():
        async with db_container() as container:
            return await container.widget_template_service().update_template(
                template.id, {"description": "Färger för kommunens sajter"}
            )

    async with db_container() as publisher:
        published = (
            await publisher.widget_template_service().publish_template(template.id)
        ).template
        save = asyncio.create_task(save_draft())
        await _wait_until_blocked(publisher.session(), save)
        assert not save.done()
    saved = await save
    assert saved.description == "Färger för kommunens sajter"
    assert saved.published == published.published
    assert saved.published_at is not None

    async with db_container() as reader:
        stored = await reader.widget_template_service().get_template(template.id)
    assert stored.published == published.published
    assert stored.description == saved.description


@pytest.mark.parametrize("how", ["link", "create"])
async def test_following_a_template_during_its_publication_takes_that_release(
    db_container, active_widget, how
):
    async with db_container() as container:
        templates = container.widget_template_service()
        template = await templates.create_template(name="Kommunblå")
        template = (await templates.publish_template(template.id)).template
    assert template.id is not None
    template_id = template.id

    async def follow() -> Widget:
        async with db_container() as container:
            service = container.widget_service()
            if how == "link":
                view = await service.link_template(
                    UUID(active_widget["id"]),
                    template_id,
                    revision=active_widget["revision"],
                )
            else:
                view = await service.create_widget(
                    space_id=UUID(active_widget["space_id"]),
                    target_id=UUID(active_widget["target_id"]),
                    name="Ny webbchatt",
                    template_id=template_id,
                )
            return view.widget

    async with db_container() as publisher:
        service = publisher.widget_template_service()
        await service.update_template(
            template_id,
            {"texts": template.texts.model_copy(update={"title": "Fråga kommunen"})},
        )
        release = (await service.publish_template(template_id)).template.published
        follower = asyncio.create_task(follow())
        await _wait_until_blocked(publisher.session(), follower)
        assert not follower.done()
    widget = await follower
    assert release is not None
    assert widget.template_id == template_id
    assert widget.texts.title == "Fråga kommunen"
    assert widget.texts.subtitle == release.texts.subtitle
    assert widget.theme == release.theme


async def test_stale_http_revision_is_rejected(client, admin_token, active_widget):
    url = f"/api/v1/widgets/{active_widget['id']}/"
    headers = {"Authorization": f"Bearer {admin_token}"}
    body = {"revision": active_widget["revision"], "name": "First"}
    assert (await client.patch(url, json=body, headers=headers)).status_code == 200
    response = await client.patch(url, json={**body, "name": "Second"}, headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "widget_revision_conflict"
    assert (await client.get(url, headers=headers)).json()["name"] == "First"


@pytest.mark.parametrize("retention_days", [0, 30])
async def test_retention_deletes_owned_logs_and_preserves_other_content(
    active_widget, retention_days
):
    widget = await _load_widget(active_widget["id"])
    logs = Base.metadata.tables["logging"]
    expired_id, kept_id = uuid4(), uuid4()
    expired_log, kept_log = uuid4(), uuid4()
    # The kept conversation belongs to a different widget in the same space.
    async with sessionmanager.session() as session, session.begin():
        other = widget.model_copy(deep=True)
        other.public_id = generate_public_id()
        other = await WidgetRepoImpl(session).add(other)
        await session.execute(
            sa.update(Widgets)
            .where(Widgets.id == widget.id)
            .values(privacy={"retention_days": retention_days})
        )
        for session_id, owner, log_id in [
            (expired_id, widget.id, expired_log),
            (kept_id, other.id, kept_log),
        ]:
            await session.execute(
                sa.insert(Sessions).values(
                    id=session_id,
                    widget_id=owner,
                    visitor_id=uuid4(),
                    name="Conversation",
                    assistant_id=widget.target_id,
                    created_at=datetime.now(timezone.utc)
                    - timedelta(days=31 if owner == widget.id else 0),
                )
            )
            await session.execute(
                sa.insert(logs).values(id=log_id, json_body='[{"content":"private"}]')
            )
            await session.execute(
                sa.insert(Questions).values(
                    session_id=session_id,
                    tenant_id=widget.tenant_id,
                    question="Question",
                    answer="Answer",
                    num_tokens_question=1,
                    num_tokens_answer=1,
                    logging_details_id=log_id,
                )
            )

    result = await purge_expired_widget_sessions()
    assert result["errors"] == 0
    async with sessionmanager.session() as session, session.begin():
        assert (
            await session.scalar(
                sa.select(Sessions.id).where(Sessions.id == expired_id)
            )
            is None
        )
        assert (
            await session.scalar(sa.select(logs.c.id).where(logs.c.id == expired_log))
            is None
        )
        assert (
            await session.scalar(sa.select(Sessions.id).where(Sessions.id == kept_id))
            == kept_id
        )
        assert (
            await session.scalar(sa.select(logs.c.id).where(logs.c.id == kept_log))
            == kept_log
        )


async def test_overview_includes_durable_inflight_budget_without_per_widget_reads(
    active_widget,
):
    widget = await _load_widget(active_widget["id"])
    budget = WidgetBudget()
    await budget.reserve(widget, 8_000)
    async with sessionmanager.session() as session, session.begin():
        foreign_tenant = uuid4()
        await session.execute(
            sa.insert(Tenants).values(
                id=foreign_tenant,
                name=f"Other-{foreign_tenant}",
                quota_limit=0,
            )
        )
        foreign_space = await session.scalar(
            sa.insert(Spaces)
            .values(tenant_id=foreign_tenant, name="Other space")
            .returning(Spaces.id)
        )
        assert foreign_space is not None
        foreign = Widget.create(
            tenant_id=foreign_tenant,
            space_id=foreign_space,
            target_id=uuid4(),
            name="Other widget",
        )
        foreign = await WidgetRepoImpl(session).add(foreign)
        await WidgetUsageRepoImpl(session).record(
            foreign.id,
            budget.today(),
            questions=999,
            input_tokens=999_999,
        )
        statements: list[str] = []

        def record_statement(
            connection, cursor, statement, parameters, context, executemany
        ):
            statements.append(statement)

        connection = await session.connection()
        sa.event.listen(
            connection.sync_connection, "before_cursor_execute", record_statement
        )
        rows = await WidgetOverviewRepoImpl(session).list_tenant(
            widget.tenant_id, today=budget.today()
        )
        sa.event.remove(
            connection.sync_connection, "before_cursor_execute", record_statement
        )
        assert len(statements) == 1
    assert {row.id for row in rows} == {widget.id}
    row = next(row for row in rows if row.id == widget.id)
    assert row.budget_used_today == 8_000
    assert row.questions_30d == 0
    assert row.last_activity is None
